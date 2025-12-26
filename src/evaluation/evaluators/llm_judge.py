from __future__ import annotations
import json
import os
from typing import Any, List, Optional

from .base import Evaluator
from .registry import register_evaluator
from src.models import (
    Conversation,
    EvaluatorResult,
    Issue,
    IssueType,
    IssueSeverity,
)
from src.utils.llm import LLMClientFactory, LLMModel
from src.config import get_settings
from pydantic import BaseModel, Field


# =============================================================================
# Structured Output Models
# =============================================================================

class LLMIssue(BaseModel):
    """Model for a single issue detected by the LLM."""
    type: str = Field(description="Type of issue: low_helpfulness, low_factuality, low_quality")
    severity: str = Field(description="Severity: low, medium, high")
    description: str = Field(description="Brief explanation of the issue")
    turn_id: Optional[int] = Field(None, description="The turn ID where the issue occurred")
    suggested_fix: Optional[str] = Field(None, description="Actionable suggestion to fix this issue")


class LLMEvaluationResponse(BaseModel):
    """Model for the full LLM evaluation results."""
    scores: dict[str, float] = Field(description="Scores between 0 and 1 for: helpfulness, factuality, quality")
    reasoning: str = Field(description="Human-readable explanation of the evaluation")
    issues: List[LLMIssue] = Field(default_factory=list, description="List of specific issues found")


# =============================================================================
# Evaluation Prompt
# =============================================================================

EVALUATION_PROMPT = """Evaluate the following conversation between a user and an AI assistant.

Your task is to assess the quality of the assistant's responses and identify any issues.

Return your evaluation as a JSON object with the following structure:
{{
    "scores": {{
        "helpfulness": float, // 0 to 1
        "factuality": float,  // 0 to 1
        "quality": float      // 0 to 1
    }},
    "reasoning": "...", // A concise explanation for your scores
    "issues": [
        {{
            "type": "low_helpfulness" | "low_factuality" | "low_quality",
            "severity": "low" | "medium" | "high",
            "description": "...",
            "turn_id": int, // Optional
            "suggested_fix": "..." // How to improve the response or tool call
        }}
    ]
}}

Conversation to evaluate:
{conversation_text}

JSON Object:"""


def _format_conversation(conversation: Conversation) -> str:
    """Format conversation for LLM evaluation."""
    lines = []
    
    if conversation.metadata:
        lines.append(f"Metadata: {json.dumps(conversation.metadata)}")
        lines.append("")
    
    for turn in conversation.turns:
        role = turn.role.value.upper()
        lines.append(f"[{role}] (Turn {turn.turn_id}):")
        lines.append(turn.content)
        
        if turn.tool_calls:
            lines.append("  Tool calls:")
            for tc in turn.tool_calls:
                lines.append(f"    - {tc.tool_name}({json.dumps(tc.parameters)})")
                if tc.result:
                    lines.append(f"    - Result: {str(tc.result)[:200]}...")
        lines.append("")
        
    return "\n".join(lines)


@register_evaluator
class LLMJudgeEvaluator(Evaluator):
    """LLM-based evaluator using direct OpenAI calls and manual JSON parsing.
    
    This implementation avoids the complexity of the instructor library while
    still enforcing structured output through Pydantic parsing.
    """
    
    def __init__(
        self,
        factory: Optional[LLMClientFactory] = None,
        model: Optional[LLMModel] = None,
    ):
        settings = get_settings()
        self.factory = factory or LLMClientFactory()
        self.model = model or LLMModel.OPENAI_GPT_4_O
        self.is_mock = not (settings.openai_key or os.getenv("OPENAI_KEY"))
    
    @property
    def evaluator_name(self) -> str:
        return "llm_judge"
    
    def _evaluate(self, conversation: Conversation) -> EvaluatorResult:
        """Evaluate conversation using LLM-as-Judge."""
        if self.is_mock:
            return self._mock_result(conversation.conversation_id)

        try:
            client = self.factory.get_client()
            conversation_text = _format_conversation(conversation)
            
            # Call LLM with direct OpenAI client using JSON mode
            response = client.chat.completions.create(
                model=self.model.value,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": "You are an expert conversation evaluator. Always respond in valid JSON."},
                    {"role": "user", "content": EVALUATION_PROMPT.format(conversation_text=conversation_text)},
                ],
                temperature=0.0,
            )
            
            content = response.choices[0].message.content
            if not content:
                raise ValueError("Empty response from LLM")
                
            parsed_response = LLMEvaluationResponse.model_validate_json(content)
            
            return self._process_response(parsed_response)
            
        except Exception as e:
            print(f"ERROR: LLMJudgeEvaluator failed: {str(e)}")
            return self._error_result(conversation.conversation_id, str(e))

    def _process_response(self, response: LLMEvaluationResponse) -> EvaluatorResult:
        """Convert LLM response to internal EvaluatorResult."""
        type_mapping = {
            "low_helpfulness": IssueType.LOW_HELPFULNESS,
            "low_factuality": IssueType.LOW_FACTUALITY,
            "low_quality": IssueType.LOW_QUALITY,
        }
        
        severity_mapping = {
            "low": IssueSeverity.LOW,
            "medium": IssueSeverity.MEDIUM,
            "high": IssueSeverity.HIGH,
        }
        
        issues = []
        for raw in response.issues:
            issues.append(Issue(
                issue_type=type_mapping.get(raw.type, IssueType.LOW_QUALITY),
                severity=severity_mapping.get(raw.severity, IssueSeverity.MEDIUM),
                description=raw.description,
                turn_id=raw.turn_id,
                suggested_fix=raw.suggested_fix,
                details={"llm_detected": True},
            ))
            
        return EvaluatorResult(
            evaluator_name=self.evaluator_name,
            scores=response.scores,
            issues=tuple(issues),
            confidence=0.85,
            metadata={
                "reasoning": response.reasoning,
                "model": self.model.value,
                "mock": False,
            }
        )

    def _mock_result(self, conversation_id: str) -> EvaluatorResult:
        """Generic mock results for LLM when no keys present."""
        return EvaluatorResult(
            evaluator_name=self.evaluator_name,
            scores={
                "helpfulness": 0.8,
                "factuality": 0.85,
                "quality": 0.75,
            },
            issues=(),
            confidence=0.0,
            metadata={
                "reasoning": "Mock reasoning because no API keys were provided.",
                "mock": True,
            }
        )

    def _error_result(self, conversation_id: str, error: str) -> EvaluatorResult:
        """Error result when evaluation fails."""
        return EvaluatorResult(
            evaluator_name=self.evaluator_name,
            scores={},
            issues=(),
            confidence=0.0,
            metadata={"error": error},
        )
