"""Tool Call Evaluator - Validates tool selection, parameters, and execution.

This evaluator checks:
- Tool selection accuracy: Was the right tool chosen for the task?
- Parameter accuracy: Are parameters correctly formatted and valid?
- Hallucination detection: Did the assistant make up tools/parameters?
- Execution success: Did tool calls execute successfully?

Scores (0-1):
- tool_selection: Whether correct tools were selected
- param_accuracy: Whether parameters were accurate
- no_hallucination: Whether there were no hallucinated tools/params
- execution_success: Whether tool calls executed successfully
"""

from typing import Any
import re

from .base import Evaluator
from .registry import register_evaluator
from src.models import (
    Conversation,
    Turn,
    ToolCall,
    Role,
    EvaluatorResult,
    Issue,
    IssueType,
    IssueSeverity,
)


# Known tool schemas for validation
# In production, this would come from a tool registry
DEFAULT_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "flight_search": {
        "required_params": ["destination"],
        "optional_params": ["date", "origin", "passengers", "class"],
        "param_patterns": {
            "date": r"^\d{4}-\d{2}-\d{2}$",  # YYYY-MM-DD
        },
    },
    "hotel_search": {
        "required_params": ["location", "check_in"],
        "optional_params": ["check_out", "guests", "rooms"],
        "param_patterns": {
            "check_in": r"^\d{4}-\d{2}-\d{2}$",
            "check_out": r"^\d{4}-\d{2}-\d{2}$",
        },
    },
    "calendar_create": {
        "required_params": ["title", "start_time"],
        "optional_params": ["end_time", "location", "attendees"],
        "param_patterns": {},
    },
    "web_search": {
        "required_params": ["query"],
        "optional_params": ["num_results", "date_range"],
        "param_patterns": {},
    },
    "send_email": {
        "required_params": ["to", "subject", "body"],
        "optional_params": ["cc", "bcc", "attachments"],
        "param_patterns": {
            "to": r"^[^@]+@[^@]+\.[^@]+$",  # Basic email pattern
        },
    },
}


@register_evaluator
class ToolCallEvaluator(Evaluator):
    """Evaluator for tool call accuracy and correctness.
    
    Configuration:
        tool_schemas: Dictionary of known tools and their schemas
        strict_mode: If True, unknown tools are flagged as hallucinations
    """
    
    def __init__(
        self,
        tool_schemas: dict[str, dict[str, Any]] | None = None,
        strict_mode: bool = False,
    ):
        # Allow a demo "active" schema override to showcase self-updating.
        self.tool_schemas = tool_schemas or self._load_active_schema() or DEFAULT_TOOL_SCHEMAS
        self.strict_mode = strict_mode

    def _load_active_schema(self) -> dict[str, dict[str, Any]] | None:
        """Load the active tool schema artifact if present."""
        from pathlib import Path
        import json

        schema_path = Path("artifacts/tools/active_tool_schema.json")
        if not schema_path.exists():
            return None
        try:
            data = json.loads(schema_path.read_text())
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        return data
    
    @property
    def evaluator_name(self) -> str:
        return "tool_call"
    
    def _validate_tool_call(self, tool_call: ToolCall, turn_id: int) -> list[Issue]:
        """Validate a single tool call against schema."""
        issues: list[Issue] = []
        tool_name = tool_call.tool_name
        params = tool_call.parameters
        
        # Check if tool exists in schema
        if tool_name not in self.tool_schemas:
            if self.strict_mode:
                issues.append(Issue(
                    issue_type=IssueType.TOOL_HALLUCINATION,
                    severity=IssueSeverity.HIGH,
                    description=f"Unknown tool '{tool_name}' - possible hallucination",
                    turn_id=turn_id,
                    details={"tool": tool_name, "known_tools": list(self.tool_schemas.keys())},
                ))
            return issues
        
        schema = self.tool_schemas[tool_name]
        required_params = schema.get("required_params", [])
        optional_params = schema.get("optional_params", [])
        param_patterns = schema.get("param_patterns", {})
        all_known_params = set(required_params + optional_params)
        
        # Check for missing required params
        for param in required_params:
            if param not in params:
                issues.append(Issue(
                    issue_type=IssueType.MISSING_PARAM,
                    severity=IssueSeverity.HIGH,
                    description=f"Tool '{tool_name}' missing required parameter: {param}",
                    turn_id=turn_id,
                    details={"tool": tool_name, "param": param},
                    suggested_fix=f"Add the '{param}' parameter to the {tool_name} call",
                ))
        
        # Check for unknown params (possible hallucination)
        for param in params.keys():
            if param not in all_known_params and self.strict_mode:
                issues.append(Issue(
                    issue_type=IssueType.INVALID_PARAM,
                    severity=IssueSeverity.MEDIUM,
                    description=f"Tool '{tool_name}' has unknown parameter: {param}",
                    turn_id=turn_id,
                    details={"tool": tool_name, "param": param, "known_params": list(all_known_params)},
                ))
        
        # Validate param patterns
        for param, pattern in param_patterns.items():
            if param in params:
                value = str(params[param])
                if not re.match(pattern, value):
                    issues.append(Issue(
                        issue_type=IssueType.INVALID_PARAM,
                        severity=IssueSeverity.HIGH,
                        description=f"Tool '{tool_name}' parameter '{param}' has invalid format: '{value}'",
                        turn_id=turn_id,
                        details={
                            "tool": tool_name,
                            "param": param,
                            "value": value,
                            "expected_pattern": pattern,
                        },
                        suggested_fix=f"Parameter '{param}' should match pattern: {pattern}",
                    ))
        
        return issues
    
    def _evaluate(self, conversation: Conversation) -> EvaluatorResult:
        """Evaluate all tool calls in the conversation."""
        issues: list[Issue] = []
        
        total_tool_calls = 0
        selection_issues = 0
        param_issues = 0
        hallucination_issues = 0
        execution_failures = 0
        
        for turn in conversation.turns:
            if turn.role != Role.ASSISTANT:
                continue
            
            for tool_call in turn.tool_calls:
                total_tool_calls += 1
                
                # Validate tool call
                call_issues = self._validate_tool_call(tool_call, turn.turn_id)
                issues.extend(call_issues)
                
                # Categorize issues
                for issue in call_issues:
                    if issue.issue_type == IssueType.TOOL_HALLUCINATION:
                        hallucination_issues += 1
                    elif issue.issue_type == IssueType.INVALID_TOOL:
                        selection_issues += 1
                    elif issue.issue_type in (IssueType.INVALID_PARAM, IssueType.MISSING_PARAM):
                        param_issues += 1
                
                # Check execution result
                if tool_call.result is None:
                    # No result could mean execution failed or wasn't executed
                    pass
                elif isinstance(tool_call.result, dict) and tool_call.result.get("error"):
                    issues.append(Issue(
                        issue_type=IssueType.EXECUTION_FAILED,
                        severity=IssueSeverity.HIGH,
                        description=f"Tool '{tool_call.tool_name}' execution failed",
                        turn_id=turn.turn_id,
                        details={
                            "tool": tool_call.tool_name,
                            "error": tool_call.result.get("error"),
                        },
                    ))
                    execution_failures += 1
        
        # If no tool calls, return perfect scores
        if total_tool_calls == 0:
            return EvaluatorResult(
                evaluator_name=self.evaluator_name,
                scores={
                    "tool_selection": 1.0,
                    "param_accuracy": 1.0,
                    "no_hallucination": 1.0,
                    "execution_success": 1.0,
                },
                issues=(),
                confidence=1.0,
                metadata={"total_tool_calls": 0, "note": "No tool calls in conversation"},
            )
        
        # Compute scores
        selection_score = 1.0 - (selection_issues / total_tool_calls)
        param_score = 1.0 - (param_issues / total_tool_calls)
        hallucination_score = 1.0 - (hallucination_issues / total_tool_calls)
        execution_score = 1.0 - (execution_failures / total_tool_calls)
        
        return EvaluatorResult(
            evaluator_name=self.evaluator_name,
            scores={
                "tool_selection": max(0.0, selection_score),
                "param_accuracy": max(0.0, param_score),
                "no_hallucination": max(0.0, hallucination_score),
                "execution_success": max(0.0, execution_score),
            },
            issues=tuple(issues),
            confidence=0.95,  # High confidence for rule-based checks
            metadata={
                "total_tool_calls": total_tool_calls,
                "selection_issues": selection_issues,
                "param_issues": param_issues,
                "hallucination_issues": hallucination_issues,
                "execution_failures": execution_failures,
            },
        )
