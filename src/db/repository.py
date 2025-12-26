from __future__ import annotations
"""Repository pattern for storing and retrieving conversations and evaluations.

This is a simple in-memory + file-based repository for the demo.
In production, this would use PostgreSQL with SQLAlchemy.

Design:
- In-memory storage for fast access during runtime
- JSON file persistence for durability
- Simple CRUD operations

Production swap:
- Replace InMemoryRepository with SQLAlchemyRepository
- Same interface, different implementation
"""

import json
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any
from functools import lru_cache

from src.models import (
    Conversation,
    FeedbackSignal,
    Turn,
    ToolCall,
    Role,
    EvaluationResult,
    EvaluatorResult,
    Issue,
    IssueType,
    IssueSeverity,
)


class ConversationRepository(ABC):
    """Abstract repository interface for conversations and evaluations."""
    
    @abstractmethod
    def save_conversation(self, conversation: Conversation) -> str:
        """Save a conversation and return its ID."""
        pass
    
    @abstractmethod
    def get_conversation(self, conversation_id: str) -> Conversation | None:
        """Get a conversation by ID."""
        pass
    
    @abstractmethod
    def list_conversations(self, limit: int = 100, offset: int = 0) -> list[Conversation]:
        """List conversations with pagination."""
        pass

    @abstractmethod
    def add_feedback(self, conversation_id: str, feedback: FeedbackSignal) -> None:
        """Append feedback to a conversation."""
        pass

    @abstractmethod
    def flag_for_review(self, conversation_id: str, reason: str | None = None) -> None:
        """Mark a conversation as needing human review."""
        pass

    @abstractmethod
    def list_feedback(self, conversation_id: str) -> list[FeedbackSignal]:
        """List feedback items for a conversation."""
        pass
    
    @abstractmethod
    def save_evaluation(self, evaluation: EvaluationResult) -> str:
        """Save an evaluation result and return its run_id."""
        pass
    
    @abstractmethod
    def get_evaluation(self, conversation_id: str) -> EvaluationResult | None:
        """Get the latest evaluation for a conversation."""
        pass
    
    @abstractmethod
    def list_evaluations(self, limit: int = 100, offset: int = 0) -> list[EvaluationResult]:
        """List evaluations with pagination."""
        pass
    
    @abstractmethod
    def get_pending_conversations(self) -> list[str]:
        """Get IDs of conversations that haven't been evaluated."""
        pass

    @abstractmethod
    def save_proposal(self, proposal: Any) -> str:
        """Save an improvement proposal."""
        pass

    @abstractmethod
    def get_proposal(self, proposal_id: str) -> Any | None:
        """Get a proposal by ID."""
        pass

    @abstractmethod
    def list_proposals(self, limit: int = 100, offset: int = 0) -> list[Any]:
        """List proposals with pagination."""
        pass


class InMemoryRepository(ConversationRepository):
    """In-memory repository with optional file persistence.
    
    Suitable for demos and testing. Data stored in memory with
    periodic flush to JSON files for durability.
    """
    
    def __init__(self, data_dir: str | Path | None = None):
        self._conversations: dict[str, Conversation] = {}
        self._evaluations: dict[str, EvaluationResult] = {}
        self._proposals: dict[str, Any] = {}
        self._proposal_types: dict[str, str] = {} # Helper for serialization mapping
        self._data_dir = Path(data_dir) if data_dir else None
        
        if self._data_dir:
            self._data_dir.mkdir(parents=True, exist_ok=True)
            self._load_from_disk()
    
    def _load_from_disk(self) -> None:
        """Load data from JSON files if they exist."""
        conv_file = self._data_dir / "conversations.json"
        eval_file = self._data_dir / "evaluations.json"
        prop_file = self._data_dir / "proposals.json"
        
        if conv_file.exists():
            try:
                data = json.loads(conv_file.read_text())
                for item in data:
                    conv = self._dict_to_conversation(item)
                    self._conversations[conv.conversation_id] = conv
            except Exception:
                pass
        
        if eval_file.exists():
            try:
                data = json.loads(eval_file.read_text())
                for item in data:
                    evaluation = self._dict_to_evaluation(item)
                    self._evaluations[evaluation.conversation_id] = evaluation
            except Exception:
                pass

        if prop_file.exists():
            try:
                # Lazy import to avoid circular dependency
                from src.analysis.models import ImprovementProposal, ImprovementType, ProposalStatus, RegressionReport, ScoreDelta
                data = json.loads(prop_file.read_text())
                for item in data:
                    # Reconstruction
                    report = None
                    if item.get("regression_report"):
                        r_data = item["regression_report"]
                        deltas = [
                            ScoreDelta(
                                metric_name=d["metric_name"],
                                old_val=d["old_val"],
                                new_val=d["new_val"],
                                is_improvement=d["is_improvement"]
                            )
                            for d in r_data.get("score_deltas", [])
                        ]
                        report = RegressionReport(
                            run_id=r_data["run_id"],
                            timestamp=datetime.fromisoformat(r_data["timestamp"]),
                            test_case_count=r_data["test_case_count"],
                            overall_improvement=r_data["overall_improvement"],
                            score_deltas=deltas
                        )

                    prop = ImprovementProposal(
                        proposal_id=item["proposal_id"],
                        type=ImprovementType(item["type"]),
                        failure_pattern=item["failure_pattern"],
                        rationale=item["rationale"],
                        original_content=item["original_content"],
                        proposed_content=item["proposed_content"],
                        status=ProposalStatus(item["status"]),
                        evidence_ids=item["evidence_ids"],
                        created_at=datetime.fromisoformat(item["created_at"]),
                        regression_report=report,
                        metadata=item.get("metadata", {})
                    )
                    self._proposals[prop.proposal_id] = prop
            except Exception:
                pass
    
    def _save_to_disk(self) -> None:
        """Save data to JSON files."""
        if not self._data_dir:
            return
        
        conv_file = self._data_dir / "conversations.json"
        eval_file = self._data_dir / "evaluations.json"
        prop_file = self._data_dir / "proposals.json"
        
        conv_data = [self._conversation_to_dict(c) for c in self._conversations.values()]
        eval_data = [self._evaluation_to_dict(e) for e in self._evaluations.values()]
        
        conv_file.write_text(json.dumps(conv_data, indent=2, default=str))
        eval_file.write_text(json.dumps(eval_data, indent=2, default=str))

        if self._proposals:
            prop_data = []
            for p in self._proposals.values():
                p_dict = {
                    "proposal_id": p.proposal_id,
                    "type": p.type.value if hasattr(p.type, "value") else p.type,
                    "failure_pattern": p.failure_pattern,
                    "rationale": p.rationale,
                    "original_content": p.original_content,
                    "proposed_content": p.proposed_content,
                    "status": p.status.value if hasattr(p.status, "value") else p.status,
                    "evidence_ids": p.evidence_ids,
                    "created_at": p.created_at.isoformat(),
                    "regression_report": None,
                    "metadata": p.metadata
                }
                
                if p.regression_report:
                    r = p.regression_report
                    p_dict["regression_report"] = {
                        "run_id": r.run_id,
                        "timestamp": r.timestamp.isoformat(),
                        "test_case_count": r.test_case_count,
                        "overall_improvement": r.overall_improvement,
                        "score_deltas": [
                            {
                                "metric_name": d.metric_name,
                                "old_val": d.old_val,
                                "new_val": d.new_val,
                                "is_improvement": d.is_improvement
                            }
                            for d in r.score_deltas
                        ]
                    }
                
                prop_data.append(p_dict)
            prop_file.write_text(json.dumps(prop_data, indent=2))
    
    def _conversation_to_dict(self, conv: Conversation) -> dict[str, Any]:
        """Convert Conversation to dictionary for JSON serialization."""
        return {
            "conversation_id": conv.conversation_id,
            "feedback": [self._feedback_to_dict(f) for f in conv.feedback],
            "metadata": conv.metadata,
            "created_at": conv.created_at.isoformat(),
            "turns": [
                {
                    "turn_id": t.turn_id,
                    "role": t.role.value,
                    "content": t.content,
                    "timestamp": t.timestamp.isoformat() if t.timestamp else None,
                    "latency_ms": t.latency_ms,
                    "tool_calls": [
                        {
                            "tool_name": tc.tool_name,
                            "parameters": tc.parameters,
                            "result": tc.result,
                            "execution_time_ms": tc.execution_time_ms,
                        }
                        for tc in t.tool_calls
                    ],
                }
                for t in conv.turns
            ],
        }

    def _feedback_to_dict(self, feedback: FeedbackSignal) -> dict[str, Any]:
        """Convert FeedbackSignal to dictionary for JSON serialization."""
        return {
            "feedback_type": feedback.feedback_type,
            "signal": feedback.signal,
            "value": feedback.value,
            "source": feedback.source,
            "timestamp": feedback.timestamp.isoformat() if feedback.timestamp else None,
            "turn_id": feedback.turn_id,
            "annotator_id": feedback.annotator_id,
            "confidence": feedback.confidence,
            "notes": feedback.notes,
        }

    def _dict_to_feedback(self, data: dict[str, Any]) -> FeedbackSignal:
        """Convert dictionary to FeedbackSignal."""
        timestamp = None
        if data.get("timestamp"):
            try:
                timestamp = datetime.fromisoformat(data["timestamp"])
            except (ValueError, TypeError):
                timestamp = None

        return FeedbackSignal(
            feedback_type=data.get("feedback_type", "explicit"),
            signal=data.get("signal", ""),
            value=data.get("value"),
            source=data.get("source", ""),
            timestamp=timestamp or datetime.utcnow(),
            turn_id=data.get("turn_id"),
            annotator_id=data.get("annotator_id"),
            confidence=data.get("confidence"),
            notes=data.get("notes"),
        )

    def _dict_to_conversation(self, data: dict[str, Any]) -> Conversation:
        """Convert dictionary to Conversation."""
        turns = []
        for t in data.get("turns", []):
            tool_calls = tuple(
                ToolCall(
                    tool_name=tc["tool_name"],
                    parameters=tc["parameters"],
                    result=tc.get("result"),
                    execution_time_ms=tc.get("execution_time_ms"),
                )
                for tc in t.get("tool_calls", [])
            )
            
            timestamp = None
            if t.get("timestamp"):
                try:
                    timestamp = datetime.fromisoformat(t["timestamp"])
                except (ValueError, TypeError):
                    pass
            
            turns.append(Turn(
                turn_id=t["turn_id"],
                role=Role(t["role"]),
                content=t["content"],
                timestamp=timestamp,
                latency_ms=t.get("latency_ms"),
                tool_calls=tool_calls,
            ))

        feedback_items = []
        for item in data.get("feedback", []):
            if isinstance(item, dict):
                feedback_items.append(self._dict_to_feedback(item))
        
        created_at = datetime.utcnow()
        if data.get("created_at"):
            try:
                created_at = datetime.fromisoformat(data["created_at"])
            except (ValueError, TypeError):
                pass
        
        return Conversation(
            conversation_id=data["conversation_id"],
            turns=tuple(turns),
            feedback=tuple(feedback_items),
            metadata=data.get("metadata", {}),
            created_at=created_at,
        )
    
    def _evaluation_to_dict(self, evaluation: EvaluationResult) -> dict[str, Any]:
        """Convert EvaluationResult to dictionary for JSON serialization."""
        evaluations_dict = {}
        for name, result in evaluation.evaluations.items():
            evaluations_dict[name] = {
                "evaluator_name": result.evaluator_name,
                "scores": result.scores,
                "confidence": result.confidence,
                "latency_ms": result.latency_ms,
                "metadata": result.metadata,
                "issues": [
                    {
                        "issue_type": issue.issue_type.value,
                        "severity": issue.severity.value,
                        "description": issue.description,
                        "turn_id": issue.turn_id,
                        "details": issue.details,
                        "suggested_fix": issue.suggested_fix,
                    }
                    for issue in result.issues
                ],
            }
        
        return {
            "conversation_id": evaluation.conversation_id,
            "run_id": evaluation.run_id,
            "timestamp": evaluation.timestamp.isoformat(),
            "aggregate_score": evaluation.aggregate_score,
            "status": evaluation.status,
            "evaluations": evaluations_dict,
            "issues": [
                {
                    "issue_type": issue.issue_type.value,
                    "severity": issue.severity.value,
                    "description": issue.description,
                    "turn_id": issue.turn_id,
                    "details": issue.details,
                    "suggested_fix": issue.suggested_fix,
                }
                for issue in evaluation.issues
            ],
        }
    
    def _dict_to_evaluation(self, data: dict[str, Any]) -> EvaluationResult:
        """Convert dictionary to EvaluationResult."""
        evaluations = {}
        for name, result_data in data.get("evaluations", {}).items():
            issues = tuple(
                Issue(
                    issue_type=IssueType(i["issue_type"]),
                    severity=IssueSeverity(i["severity"]),
                    description=i["description"],
                    turn_id=i.get("turn_id"),
                    details=i.get("details", {}),
                    suggested_fix=i.get("suggested_fix"),
                )
                for i in result_data.get("issues", [])
            )
            
            evaluations[name] = EvaluatorResult(
                evaluator_name=result_data["evaluator_name"],
                scores=result_data["scores"],
                confidence=result_data.get("confidence", 1.0),
                latency_ms=result_data.get("latency_ms"),
                metadata=result_data.get("metadata", {}),
                issues=issues,
            )
        
        all_issues = [
            Issue(
                issue_type=IssueType(i["issue_type"]),
                severity=IssueSeverity(i["severity"]),
                description=i["description"],
                turn_id=i.get("turn_id"),
                details=i.get("details", {}),
                suggested_fix=i.get("suggested_fix"),
            )
            for i in data.get("issues", [])
        ]
        
        timestamp = datetime.utcnow()
        if data.get("timestamp"):
            try:
                timestamp = datetime.fromisoformat(data["timestamp"])
            except (ValueError, TypeError):
                pass
        
        return EvaluationResult(
            conversation_id=data["conversation_id"],
            run_id=data.get("run_id", ""),
            timestamp=timestamp,
            aggregate_score=data.get("aggregate_score", 0.0),
            status=data.get("status", "completed"),
            evaluations=evaluations,
            issues=all_issues,
        )
    
    # =========================================================================
    # Repository Interface Implementation
    # =========================================================================
    
    def save_conversation(self, conversation: Conversation) -> str:
        """Save a conversation and return its ID."""
        self._conversations[conversation.conversation_id] = conversation
        self._save_to_disk()
        return conversation.conversation_id
    
    def get_conversation(self, conversation_id: str) -> Conversation | None:
        """Get a conversation by ID."""
        return self._conversations.get(conversation_id)
    
    def list_conversations(self, limit: int = 100, offset: int = 0) -> list[Conversation]:
        """List conversations with pagination."""
        conversations = list(self._conversations.values())
        # Sort by created_at descending
        conversations.sort(key=lambda c: c.created_at, reverse=True)
        return conversations[offset:offset + limit]

    def add_feedback(self, conversation_id: str, feedback: FeedbackSignal) -> None:
        """Append feedback to a conversation."""
        conversation = self._conversations.get(conversation_id)
        if conversation is None:
            return
        existing = list(conversation.feedback)
        existing.append(feedback)
        conversation.feedback = tuple(existing)
        self._save_to_disk()

    def flag_for_review(self, conversation_id: str, reason: str | None = None) -> None:
        """Mark a conversation as needing human review."""
        conversation = self._conversations.get(conversation_id)
        if conversation is None:
            return
        conversation.metadata["needs_review"] = True
        if reason:
            conversation.metadata["review_reason"] = reason
        self._save_to_disk()

    def list_feedback(self, conversation_id: str) -> list[FeedbackSignal]:
        """List feedback items for a conversation."""
        conversation = self._conversations.get(conversation_id)
        if conversation is None:
            return []
        return list(conversation.feedback)
    
    def save_evaluation(self, evaluation: EvaluationResult) -> str:
        """Save an evaluation result and return its run_id."""
        self._evaluations[evaluation.conversation_id] = evaluation
        self._save_to_disk()
        return evaluation.run_id
    
    def get_evaluation(self, conversation_id: str) -> EvaluationResult | None:
        """Get the latest evaluation for a conversation."""
        return self._evaluations.get(conversation_id)
    
    def list_evaluations(self, limit: int = 100, offset: int = 0) -> list[EvaluationResult]:
        """List evaluations with pagination."""
        evaluations = list(self._evaluations.values())
        # Sort by timestamp descending
        evaluations.sort(key=lambda e: e.timestamp, reverse=True)
        return evaluations[offset:offset + limit]
    
    def get_pending_conversations(self) -> list[str]:
        """Get IDs of conversations that haven't been evaluated."""
        evaluated_ids = set(self._evaluations.keys())
        return [
            cid for cid in self._conversations.keys()
            if cid not in evaluated_ids
        ]

    def save_proposal(self, proposal: Any) -> str:
        """Save an improvement proposal."""
        self._proposals[proposal.proposal_id] = proposal
        self._save_to_disk()
        return proposal.proposal_id

    def get_proposal(self, proposal_id: str) -> Any | None:
        """Get a proposal by ID."""
        return self._proposals.get(proposal_id)

    def list_proposals(self, limit: int = 100, offset: int = 0) -> list[Any]:
        """List proposals with pagination."""
        proposals = list(self._proposals.values())
        proposals.sort(key=lambda p: p.created_at, reverse=True)
        return proposals[offset:offset + limit]


# Global repository instance
_repository: ConversationRepository | None = None


@lru_cache
def get_repository(data_dir: str | None = None) -> ConversationRepository:
    """Get the repository instance (singleton)."""
    global _repository
    if _repository is None:
        _repository = InMemoryRepository(data_dir=data_dir or "./data")
    return _repository


def set_repository(repo: ConversationRepository) -> None:
    """Set a custom repository (useful for testing)."""
    global _repository
    _repository = repo
