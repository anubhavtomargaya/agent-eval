"""Ingestion Service - Validates and stores conversations.

This service:
- Validates incoming conversation data
- Converts to internal models
- Stores in the repository

Usage:
    service = IngestionService(repository)
    result = service.ingest_batch(conversations_json)
"""

import json
import uuid
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from src.models import (
    Conversation,
    Turn,
    ToolCall,
    Role,
    IngestionResult,
)
from src.db.repository import ConversationRepository


class ValidationError(Exception):
    """Raised when conversation validation fails."""
    pass


class IngestionService:
    """Service for ingesting and validating conversations.
    
    Handles:
    - Schema validation
    - Data normalization
    - Deduplication
    - Storage
    """
    
    def __init__(self, repository: ConversationRepository):
        self.repository = repository
    
    def ingest_single(self, conversation_data: dict[str, Any]) -> Conversation:
        """Ingest and validate a single conversation.
        
        Args:
            conversation_data: Raw conversation dictionary
            
        Returns:
            Validated and stored Conversation object
            
        Raises:
            ValidationError: If validation fails
        """
        try:
            conversation = self._validate_and_convert(conversation_data)
            conversation_id = self.repository.save_conversation(conversation)
            conversation.conversation_id = conversation_id
            return conversation
        except Exception as e:
            raise ValidationError(f"Failed to ingest conversation: {str(e)}")
    
    def ingest_batch(self, conversations: list[dict[str, Any]]) -> IngestionResult:
        """Ingest multiple conversations.
        
        Args:
            conversations: List of raw conversation dictionaries
            
        Returns:
            IngestionResult with success/failure counts
        """
        success_count = 0
        failed_count = 0
        errors = []
        conversation_ids = []
        
        for conv_data in conversations:
            try:
                conversation = self.ingest_single(conv_data)
                success_count += 1
                conversation_ids.append(conversation.conversation_id)
            except ValidationError as e:
                failed_count += 1
                errors.append(str(e))
        
        return IngestionResult(
            total=len(conversations),
            success=success_count,
            failed=failed_count,
            errors=errors,
            conversation_ids=conversation_ids,
        )
    
    def ingest_from_file(self, file_path: str | Path) -> IngestionResult:
        """Ingest conversations from a JSON file."""
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            
            # Handle various JSON structures
            if isinstance(data, dict):
                # Check for "conversations" wrapper
                if "conversations" in data:
                    conversations = data["conversations"]
                else:
                    # Single conversation object
                    conversations = [data]
            elif isinstance(data, list):
                conversations = data
            else:
                raise ValidationError(f"Invalid JSON structure in {file_path}")
            
            return self.ingest_batch(conversations)
        except json.JSONDecodeError as e:
            raise ValidationError(f"Invalid JSON in {file_path}: {str(e)}")
        except ValidationError:
            raise
        except Exception as e:
            raise ValidationError(f"Failed to read file {file_path}: {str(e)}")

    def ingest_pending(self, pending_dir: str | Path = "data/pending") -> dict[str, Any]:
        """Process all JSON files in the pending directory.
        
        Args:
            pending_dir: Directory containing pending ingestion files
            
        Returns:
            Dictionary with counts and detailed results
        """
        pending_path = Path(pending_dir)
        processed_dir = pending_path.parent / "processed"
        error_dir = pending_path.parent / "error"
        
        # Ensure directories exist
        pending_path.mkdir(parents=True, exist_ok=True)
        processed_dir.mkdir(parents=True, exist_ok=True)
        error_dir.mkdir(parents=True, exist_ok=True)
        
        results = {
            "files_processed": 0,
            "total_conversations": 0,
            "success_count": 0,
            "failed_count": 0,
            "details": []
        }
        
        # Process each JSON file
        for file_path in pending_path.glob("*.json"):
            results["files_processed"] += 1
            try:
                ingest_result = self.ingest_from_file(file_path)
                results["total_conversations"] += ingest_result.total
                results["success_count"] += ingest_result.success
                results["failed_count"] += ingest_result.failed
                
                # Move to processed
                shutil.move(str(file_path), str(processed_dir / file_path.name))
                results["details"].append({
                    "file": file_path.name,
                    "status": "success",
                    "ingested": ingest_result.success
                })
            except Exception as e:
                # Move to error
                shutil.move(str(file_path), str(error_dir / file_path.name))
                results["details"].append({
                    "file": file_path.name,
                    "status": "error",
                    "error": str(e)
                })
        
        return results
    
    def _validate_and_convert(self, data: dict[str, Any]) -> Conversation:
        """Validate and convert raw data to Conversation model.
        
        Args:
            data: Raw conversation dictionary
            
        Returns:
            Validated Conversation object
            
        Raises:
            ValidationError: If validation fails
        """
        try:
            # Generate conversation_id if not provided
            conversation_id = data.get("conversation_id") or str(uuid.uuid4())
            
            # Parse turns
            turns_data = data.get("turns", [])
            if not turns_data:
                raise ValidationError("Conversation must have at least one turn")
            
            turns = []
            for idx, turn_data in enumerate(turns_data):
                # Assign turn_id if not provided
                turn_id = turn_data.get("turn_id", idx)
                
                # Parse role
                role_str = turn_data.get("role", "").lower()
                try:
                    role = Role(role_str)
                except ValueError:
                    raise ValidationError(f"Invalid role '{role_str}' in turn {turn_id}")
                
                # Parse content
                content = turn_data.get("content", "")
                
                # Parse timestamp
                timestamp = None
                if "timestamp" in turn_data:
                    ts = turn_data["timestamp"]
                    if isinstance(ts, str):
                        try:
                            timestamp = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        except ValueError:
                            raise ValidationError(f"Invalid timestamp format in turn {turn_id}")
                    elif isinstance(ts, datetime):
                        timestamp = ts
                
                # Parse tool calls
                tool_calls = []
                for tc_data in turn_data.get("tool_calls", []):
                    tool_call = ToolCall(
                        tool_name=tc_data.get("tool_name", ""),
                        parameters=tc_data.get("parameters", {}),
                        result=tc_data.get("result"),
                        execution_time_ms=tc_data.get("execution_time_ms"),
                    )
                    tool_calls.append(tool_call)
                
                turn = Turn(
                    turn_id=turn_id,
                    role=role,
                    content=content,
                    timestamp=timestamp,
                    latency_ms=turn_data.get("latency_ms"),
                    tool_calls=tool_calls,
                )
                turns.append(turn)
            
            # Create conversation
            conversation = Conversation(
                conversation_id=conversation_id,
                turns=turns,
                metadata=data.get("metadata", {}),
                created_at=datetime.utcnow(),
            )
            
            return conversation
            
        except PydanticValidationError as e:
            raise ValidationError(f"Validation failed: {str(e)}")
        except Exception as e:
            if isinstance(e, ValidationError):
                raise
            raise ValidationError(f"Unexpected error during validation: {str(e)}")

