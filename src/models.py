"""Core data models for the AI Agent Evaluation Pipeline.

This module defines all dataclasses used throughout the pipeline:
- Conversation, Turn, ToolCall: Input data structures
- EvaluatorResult, Issue, EvaluationResult: Output data structures
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from enum import Enum
import uuid


# =============================================================================
# Enums
# =============================================================================

class Role(str, Enum):
    """Role in a conversation turn."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class IssueSeverity(str, Enum):
    """Severity level for detected issues."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IssueType(str, Enum):
    """Types of issues that can be detected."""
    # Heuristic issues
    MISSING_FIELD = "missing_field"
    FORMAT_ERROR = "format_error"
    LATENCY_EXCEEDED = "latency_exceeded"
    
    # Tool call issues
    INVALID_TOOL = "invalid_tool"
    INVALID_PARAM = "invalid_param"
    MISSING_PARAM = "missing_param"
    TOOL_HALLUCINATION = "tool_hallucination"
    EXECUTION_FAILED = "execution_failed"
    
    # Coherence issues
    CONTEXT_LOSS = "context_loss"
    INCONSISTENT_RESPONSE = "inconsistent_response"
    REFERENCE_ERROR = "reference_error"
    
    # LLM Judge issues
    LOW_HELPFULNESS = "low_helpfulness"
    LOW_FACTUALITY = "low_factuality"
    LOW_QUALITY = "low_quality"


# =============================================================================
# Input Data Structures
# =============================================================================

@dataclass
class ToolCall:
    """Represents a tool/function call made by the assistant.
    
    Attributes:
        tool_name: Name of the tool being called
        parameters: Parameters passed to the tool
        result: Result returned by the tool (if executed)
        execution_time_ms: Time taken to execute the tool in milliseconds
    """
    tool_name: str
    parameters: dict[str, Any] = field(default_factory=dict)
    result: Any | None = None
    execution_time_ms: float | None = None


@dataclass
class Turn:
    """Represents a single turn in a conversation.
    
    Attributes:
        turn_id: Unique identifier for this turn within the conversation
        role: Who sent this message (user/assistant/system)
        content: The text content of the message
        timestamp: When this turn occurred
        tool_calls: List of tool calls made in this turn (assistant only)
        latency_ms: Response latency in milliseconds (assistant only)
    """
    turn_id: int
    role: Role
    content: str
    timestamp: datetime | None = None
    tool_calls: tuple[ToolCall, ...] | list[ToolCall] = field(default_factory=tuple)
    latency_ms: float | None = None
    
    def __post_init__(self):
        # Normalize tool_calls to tuple
        if isinstance(self.tool_calls, list):
            self.tool_calls = tuple(self.tool_calls)


@dataclass
class Conversation:
    """Represents a complete multi-turn conversation.
    
    Attributes:
        conversation_id: Unique identifier for this conversation
        turns: Ordered sequence of turns in the conversation
        metadata: Additional metadata (user_id, session_start, agent_version, etc.)
        created_at: When this conversation was created/ingested
    """
    conversation_id: str
    turns: tuple[Turn, ...] | list[Turn]
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self):
        # Generate ID if not provided
        if not self.conversation_id:
            self.conversation_id = str(uuid.uuid4())
        # Normalize turns to tuple
        if isinstance(self.turns, list):
            self.turns = tuple(self.turns)


# =============================================================================
# Output Data Structures
# =============================================================================

@dataclass
class Issue:
    """Represents a detected issue in a conversation.
    
    Attributes:
        issue_type: Type of issue detected
        severity: How severe this issue is
        description: Human-readable description
        turn_id: Which turn this issue was found in (if applicable)
        details: Additional details about the issue
        suggested_fix: Suggested remediation (if applicable)
    """
    issue_type: IssueType
    severity: IssueSeverity
    description: str
    turn_id: int | None = None
    details: dict[str, Any] = field(default_factory=dict)
    suggested_fix: str | None = None


@dataclass
class EvaluatorResult:
    """Result from a single evaluator.
    
    Attributes:
        evaluator_name: Name of the evaluator that produced this result
        scores: Dictionary of score dimensions and their values (0-1 scale)
        issues: List of issues detected by this evaluator
        confidence: Confidence in this evaluation (0-1)
        metadata: Additional evaluator-specific metadata
        latency_ms: Time taken to run this evaluation
    """
    evaluator_name: str
    scores: dict[str, float] = field(default_factory=dict)
    issues: tuple[Issue, ...] | list[Issue] = field(default_factory=tuple)
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)
    latency_ms: float | None = None


@dataclass
class EvaluationResult:
    """Complete evaluation result for a conversation.
    
    Attributes:
        conversation_id: ID of the evaluated conversation
        run_id: Unique ID for this evaluation run
        evaluations: Results from each evaluator
        aggregate_score: Overall score computed from individual evaluations
        issues: All issues aggregated from all evaluators
        status: Status of this evaluation
        timestamp: When this evaluation was performed
    """
    conversation_id: str
    evaluations: dict[str, EvaluatorResult] = field(default_factory=dict)
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    aggregate_score: float = 0.0
    issues: list[Issue] = field(default_factory=list)
    status: Literal["pending", "completed", "failed"] = "pending"
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    def compute_aggregate_score(self) -> float:
        """Compute aggregate score from individual evaluator scores."""
        if not self.evaluations:
            return 0.0
        
        all_scores = []
        for eval_result in self.evaluations.values():
            all_scores.extend(eval_result.scores.values())
        
        if not all_scores:
            return 0.0
        
        self.aggregate_score = sum(all_scores) / len(all_scores)
        return self.aggregate_score
    
    def aggregate_issues(self) -> list[Issue]:
        """Aggregate issues from all evaluators."""
        self.issues = []
        for eval_result in self.evaluations.values():
            if isinstance(eval_result.issues, (list, tuple)):
                self.issues.extend(eval_result.issues)
        return self.issues


# =============================================================================
# Ingestion Result
# =============================================================================

@dataclass
class IngestionResult:
    """Result from ingesting conversations.
    
    Attributes:
        total: Total number of conversations processed
        success: Number successfully ingested
        failed: Number that failed
        errors: List of error messages
        conversation_ids: IDs of successfully ingested conversations
    """
    total: int
    success: int
    failed: int = 0
    errors: tuple[str, ...] | list[str] = field(default_factory=tuple)
    conversation_ids: tuple[str, ...] | list[str] = field(default_factory=tuple)
