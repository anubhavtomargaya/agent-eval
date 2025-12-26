import json
from typing import List, Optional, Dict, Any
from src.analysis.models import (
    ImprovementProposal, 
    IssueCluster, 
    ImprovementType, 
    ProposalStatus
)
from src.utils.llm import LLMClientFactory

class SuggestionEngine:
    """Generates localized prompt PRs based on failure clusters."""
    
    def __init__(self):
        self.factory = LLMClientFactory()

    def generate_proposal(
        self, 
        cluster: IssueCluster, 
        current_prompt: str,
        tool_definitions: Optional[Dict[str, Any]] = None
    ) -> ImprovementProposal:
        """Create a suggestion to fix the pattern identified in the cluster.
        
        Automatically detects if the issue is with the system prompt or 
        a specific tool schema.
        """
        tool_definitions = tool_definitions or {}
        
        # 1. Determine if this cluster is tool-focused
        # Heuristic: Check issue types and cluster explanation for tool keywords
        is_tool_issue = any(
            t in cluster.explanation.lower() 
            for t in ["tool", "parameter", "argument", "schema", "invalid value"]
        ) or any(
            "tool" in it.lower() for it in cluster.metadata.get("issue_types", [])
        )

        client = self.factory.get_client()
        if not client.api_key:
            return self._mock_proposal(cluster, current_prompt, is_tool_issue)

        if is_tool_issue:
            return self._generate_tool_proposal(client, cluster, tool_definitions)
        else:
            return self._generate_prompt_proposal(client, cluster, current_prompt)

    def _generate_prompt_proposal(self, client, cluster, current_prompt) -> ImprovementProposal:
        """Handle standard prompt updates."""

        prompt = f"""You are an expert Prompt Engineer. 
        Your task is to fix a systemic AI agent failure through a localized prompt modification.

        Systemic Failure Pattern:
        {cluster.explanation}

        Current System Prompt (or relevant snippet):
        ---
        {current_prompt}
        ---

        Return a JSON response with:
        - "proposed_snippet": The new, improved version of the prompt snippet.
        - "rationale": Clear explanation of why this change fixes the pattern.
        - "confidence": Float between 0 and 1.
        
        Constraints:
        - Keep changes localized.
        - Do not break existing functionality.
        
        Response:"""

        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            data = json.loads(response.choices[0].message.content)
            
            return ImprovementProposal(
                type=ImprovementType.PROMPT,
                cluster_id=cluster.cluster_id,
                failure_pattern=cluster.explanation,
                rationale=data.get("rationale", ""),
                original_content=current_prompt,
                proposed_content=data.get("proposed_snippet", ""),
                evidence_ids=cluster.conversation_ids,
                status=ProposalStatus.DRAFT,
                metadata={"confidence": data.get("confidence", 0.0)}
            )
            
        except Exception as e:
            print(f"Error generating prompt proposal: {e}")
            return self._error_proposal(cluster, current_prompt, str(e))

    def _generate_tool_proposal(self, client, cluster, tool_definitions) -> ImprovementProposal:
        """Handle tool schema updates (descriptions, validation rules)."""
        
        tools_str = json.dumps(tool_definitions, indent=2)
        
        prompt = f"""You are an expert Tool & API Designer.
        Your task is to fix a systemic AI agent failure by improving a Tool's JSON Schema.
        
        Systemic Failure Pattern:
        {cluster.explanation}
        
        Current Tool Definitions:
        {tools_str}
        
        Provide a JSON response with:
        - "tool_name": Name of the tool to modify.
        - "proposed_schema": The updated JSON schema for that specific tool.
        - "rationale": Why this change (e.g., added validation, clearer description) fixes the pattern.
        - "improvement_type": One of ["description_improvement", "validation_rule", "schema_fix"]
        
        Response:"""

        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            data = json.loads(response.choices[0].message.content)
            
            tool_name = data.get("tool_name", "unknown_tool")
            original_schema = json.dumps(tool_definitions.get(tool_name, {}), indent=2)
            proposed_schema = json.dumps(data.get("proposed_schema", {}), indent=2)
            
            return ImprovementProposal(
                type=ImprovementType.TOOL,
                cluster_id=cluster.cluster_id,
                failure_pattern=cluster.explanation,
                rationale=data.get("rationale", ""),
                original_content=original_schema,
                proposed_content=proposed_schema,
                evidence_ids=cluster.conversation_ids,
                status=ProposalStatus.DRAFT,
                metadata={
                    "tool_name": tool_name,
                    "fix_category": data.get("improvement_type", "schema_fix")
                }
            )
        except Exception as e:
            print(f"Error generating tool proposal: {e}")
            return self._error_proposal(cluster, "Tool Schema Modification", str(e))

    def _mock_proposal(self, cluster: IssueCluster, current_prompt: str, is_tool: bool = False) -> ImprovementProposal:
        """Mock proposal for development without API keys."""
        if is_tool:
            return ImprovementProposal(
                type=ImprovementType.TOOL,
                cluster_id=cluster.cluster_id,
                failure_pattern=cluster.explanation,
                rationale="Mock rationale: Added enum validation to hotel_search location.",
                original_content='{"parameters": {"location": {"type": "string"}}}',
                proposed_content='{"parameters": {"location": {"type": "string", "description": "City name, must be capitalized"}}}',
                evidence_ids=cluster.conversation_ids,
                status=ProposalStatus.DRAFT,
                metadata={"tool_name": "hotel_search"}
            )
        return ImprovementProposal(
            type=ImprovementType.PROMPT,
            cluster_id=cluster.cluster_id,
            failure_pattern=cluster.explanation,
            rationale="Mock rationale: Added date format instructions.",
            original_content=current_prompt,
            proposed_content=current_prompt + "\n\nNote: Always use YYYY-MM-DD for dates.",
            evidence_ids=cluster.conversation_ids,
            status=ProposalStatus.DRAFT,
            metadata={"mock": True}
        )

    def _error_proposal(self, cluster: IssueCluster, current_prompt: str, error: str) -> ImprovementProposal:
        """Fallback proposal in case of API failure."""
        return ImprovementProposal(
            type=ImprovementType.PROMPT,
            cluster_id=cluster.cluster_id,
            failure_pattern=cluster.explanation,
            rationale=f"Failed to generate suggestion: {error}",
            original_content=current_prompt,
            status=ProposalStatus.REJECTED
        )
