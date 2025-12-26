from __future__ import annotations
from typing import Any, Set
import re

from .base import Evaluator
from .registry import register_evaluator
from src.models import (
    Conversation,
    Role,
    EvaluatorResult,
    Issue,
    IssueType,
    IssueSeverity,
)

@register_evaluator
class ToolCausalityEvaluator(Evaluator):
    """Evaluator that verifies the provenance of tool parameters.
    
    A tool parameter is considered 'causal' if its value appeared in:
    1. Previous user messages (direct instruction)
    2. Previous tool results (chained execution)
    3. Previous system or assistant messages (contextual continuity)
    
    If a value appears in a tool call but never appeared in the history, 
    it is flagged as a likely hallucination.
    """
    
    @property
    def evaluator_name(self) -> str:
        return "tool_causality"
    
    def _extract_values(self, obj: Any) -> Set[str]:
        """Recursively extract all string/number values from a dictionary or list."""
        values = set()
        if isinstance(obj, (str, int, float)):
            values.add(str(obj).lower())
        elif isinstance(obj, dict):
            for v in obj.values():
                values.update(self._extract_values(v))
        elif isinstance(obj, (list, tuple)):
            for item in obj:
                values.update(self._extract_values(item))
        return values

    def _evaluate(self, conversation: Conversation) -> EvaluatorResult:
        """Verify data provenance for all tool calls."""
        issues: list[Issue] = []
        
        # This set will store all strings/data seen so far in the conversation
        seen_data: Set[str] = set()
        
        total_checks = 0
        hallucinated_params = 0
        
        for turn in conversation.turns:
            # 1. Before checking the assistant's tool call, we update our 'seen_data'
            # with the user's current input and any previous turn content.
            # We also tokenize slightly to handle values inside sentences.
            content_tokens = set(re.findall(r'\w+', turn.content.lower()))
            seen_data.update(content_tokens)
            
            # Special case: values like "XY123" might be specific, let's also add the whole content
            seen_data.add(turn.content.lower())

            if turn.role == Role.ASSISTANT:
                for tool_call in turn.tool_calls:
                    param_values = self._extract_values(tool_call.parameters)
                    non_grounded_params = []
                    
                    for val in param_values:
                        if not val or len(val) < 2: # Skip empty or trivial single-chars
                            continue
                            
                        total_checks += 1
                        
                        # Check if this specific value (or a substring of it) has been seen
                        is_grounded = False
                        if val in seen_data:
                            is_grounded = True
                        else:
                            # Direct substring search in previous content
                            for prev_data in seen_data:
                                if val in prev_data:
                                    is_grounded = True
                                    break
                        
                        # Fuzzy date fallback: If it's a date like YYYY-MM-DD, check if parts are seen
                        if not is_grounded and re.match(r'^\d{4}-\d{2}-\d{2}$', val):
                            year, month, day = val.split('-')
                            # If year and day are mentioned, we consider the ISO format grounded (best effort)
                            if (year in seen_data or year[2:] in seen_data) and (day in seen_data or str(int(day)) in seen_data):
                                is_grounded = True

                        if not is_grounded:
                            hallucinated_params += 1
                            non_grounded_params.append(val)

                    # Group issues by tool call to avoid individual spam
                    if non_grounded_params:
                        issues.append(Issue(
                            issue_type=IssueType.TOOL_HALLUCINATION,
                            severity=IssueSeverity.HIGH,
                            description=(
                                f"Tool '{tool_call.tool_name}' used non-grounded parameter values: {', '.join(non_grounded_params)}. "
                                "These values were never clearly mentioned in the conversation history."
                            ),
                            turn_id=turn.turn_id,
                            details={
                                "tool": tool_call.tool_name,
                                "hallucinated_params": non_grounded_params,
                                "context_snippet": turn.content[:100]
                            },
                            suggested_fix=(
                                f"Ensure that these specific values ({', '.join(non_grounded_params)}) are either "
                                "provided by the user or fetched from a previous tool before using them."
                            )
                        ))

                    # 2. After checking, add the tool results to 'seen_data' for subsequent turns
                    if tool_call.result:
                        result_values = self._extract_values(tool_call.result)
                        seen_data.update(result_values)
            
        # Compute score
        provenance_score = 1.0
        if total_checks > 0:
            provenance_score = 1.0 - (hallucinated_params / total_checks)
            
        return EvaluatorResult(
            evaluator_name=self.evaluator_name,
            scores={
                "data_provenance": max(0.0, provenance_score),
            },
            issues=tuple(issues),
            confidence=0.9,
            metadata={
                "total_params_checked": total_checks,
                "hallucinations_detected": hallucinated_params
            }
        )
