import json
from typing import List, Optional
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
        current_prompt: str
    ) -> ImprovementProposal:
        """Create a suggestion to fix the pattern identified in the cluster."""
        
        client = self.factory.get_client()
        if not client.api_key:
            return self._mock_proposal(cluster, current_prompt)

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
            print(f"Error generating proposal: {e}")
            return self._error_proposal(cluster, current_prompt, str(e))

    def _mock_proposal(self, cluster: IssueCluster, current_prompt: str) -> ImprovementProposal:
        """Mock proposal for development without API keys."""
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
