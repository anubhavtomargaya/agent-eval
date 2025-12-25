"""Heuristic Evaluator - Rule-based checks for format, required fields, and latency.

This evaluator performs fast, deterministic checks that don't require external API calls:
- Format compliance: Response structure, JSON validity, etc.
- Required fields: Ensures all necessary data is present
- Latency thresholds: Checks if response times are acceptable

Scores (0-1):
- format_compliance: Whether responses are properly formatted
- required_fields: Whether all required fields are present  
- latency_ok: Whether response latencies are within threshold
"""

from .base import Evaluator
from .registry import register_evaluator
from src.models import (
    Conversation,
    Turn,
    Role,
    EvaluatorResult,
    Issue,
    IssueType,
    IssueSeverity,
)


# Default thresholds
DEFAULT_MAX_LATENCY_MS = 5000  # 5 seconds
DEFAULT_MAX_TURN_LENGTH = 10000  # 10k characters


@register_evaluator
class HeuristicEvaluator(Evaluator):
    """Rule-based evaluator for format, fields, and latency checks.
    
    Configuration:
        max_latency_ms: Maximum acceptable response latency
        max_turn_length: Maximum acceptable turn content length
        required_metadata_fields: List of required metadata fields
    """
    
    def __init__(
        self,
        max_latency_ms: float = DEFAULT_MAX_LATENCY_MS,
        max_turn_length: int = DEFAULT_MAX_TURN_LENGTH,
        required_metadata_fields: list[str] | None = None,
    ):
        self.max_latency_ms = max_latency_ms
        self.max_turn_length = max_turn_length
        self.required_metadata_fields = required_metadata_fields or []
    
    @property
    def evaluator_name(self) -> str:
        return "heuristic"
    
    def _evaluate(self, conversation: Conversation) -> EvaluatorResult:
        """Perform heuristic checks on the conversation."""
        issues: list[Issue] = []
        
        # Track scores
        format_issues = 0
        field_issues = 0
        latency_issues = 0
        total_assistant_turns = 0
        
        # Check required metadata fields
        for field in self.required_metadata_fields:
            if field not in conversation.metadata:
                issues.append(Issue(
                    issue_type=IssueType.MISSING_FIELD,
                    severity=IssueSeverity.MEDIUM,
                    description=f"Missing required metadata field: {field}",
                    details={"field": field, "location": "metadata"},
                ))
                field_issues += 1
        
        # Check each turn
        for turn in conversation.turns:
            # Format checks
            if not turn.content or not turn.content.strip():
                issues.append(Issue(
                    issue_type=IssueType.FORMAT_ERROR,
                    severity=IssueSeverity.HIGH,
                    description=f"Turn {turn.turn_id} has empty content",
                    turn_id=turn.turn_id,
                    details={"role": turn.role.value},
                ))
                format_issues += 1
            
            # Length check
            if len(turn.content) > self.max_turn_length:
                issues.append(Issue(
                    issue_type=IssueType.FORMAT_ERROR,
                    severity=IssueSeverity.LOW,
                    description=f"Turn {turn.turn_id} exceeds maximum length ({len(turn.content)} > {self.max_turn_length})",
                    turn_id=turn.turn_id,
                    details={"length": len(turn.content), "max": self.max_turn_length},
                ))
                format_issues += 1
            
            # Latency check (assistant turns only)
            if turn.role == Role.ASSISTANT:
                total_assistant_turns += 1
                
                if turn.latency_ms is not None and turn.latency_ms > self.max_latency_ms:
                    issues.append(Issue(
                        issue_type=IssueType.LATENCY_EXCEEDED,
                        severity=IssueSeverity.MEDIUM,
                        description=f"Turn {turn.turn_id} latency exceeded threshold ({turn.latency_ms:.0f}ms > {self.max_latency_ms}ms)",
                        turn_id=turn.turn_id,
                        details={
                            "latency_ms": turn.latency_ms,
                            "threshold_ms": self.max_latency_ms,
                        },
                    ))
                    latency_issues += 1
        
        # Compute scores (1.0 = perfect, 0.0 = all failed)
        total_turns = len(conversation.turns)
        
        format_score = 1.0 - (format_issues / max(total_turns, 1))
        field_score = 1.0 - (field_issues / max(len(self.required_metadata_fields), 1)) if self.required_metadata_fields else 1.0
        latency_score = 1.0 - (latency_issues / max(total_assistant_turns, 1)) if total_assistant_turns > 0 else 1.0
        
        return EvaluatorResult(
            evaluator_name=self.evaluator_name,
            scores={
                "format_compliance": max(0.0, format_score),
                "required_fields": max(0.0, field_score),
                "latency_ok": max(0.0, latency_score),
            },
            issues=tuple(issues),
            confidence=1.0,  # Heuristic checks are deterministic
            metadata={
                "total_turns": total_turns,
                "assistant_turns": total_assistant_turns,
                "format_issues": format_issues,
                "field_issues": field_issues,
                "latency_issues": latency_issues,
            },
        )

