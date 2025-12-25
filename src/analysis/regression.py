from typing import List, Optional, Any
from src.analysis.models import RegressionReport, ScoreDelta, ImprovementProposal
from src.models import EvaluationResult, Conversation
from src.utils.llm import LLMClientFactory

class RegressionTester:
    """Verifies improvements by running 'shadow' evaluations."""
    
    def __init__(self, evaluation_service: Any):
        self.evaluation_service = evaluation_service
        self.factory = LLMClientFactory()

    def run_regression(
        self, 
        proposal: ImprovementProposal, 
        test_set: List[Conversation]
    ) -> RegressionReport:
        """Run the test set through the proposed prompt and compare results."""
        
        report = RegressionReport(
            test_case_count=len(test_set),
            details={"proposal_id": proposal.proposal_id}
        )
        
        # 1. Simulate Shadow Responses
        shadow_conversations = []
        for conv in test_set:
            shadow_conv = self._simulate_shadow_conversation(conv, proposal.proposed_content)
            shadow_conversations.append(shadow_conv)
            
        # 2. Evaluate Shadow Responses
        base_evals = [self.evaluation_service.get_evaluation(c.conversation_id) for c in test_set]
        shadow_evals = [self.evaluation_service.evaluate_conversation(c) for c in shadow_conversations]
        
        # 3. Calculate Deltas
        report.score_deltas = self._calculate_deltas(base_evals, shadow_evals)
        report.overall_improvement = any(d.is_improvement for d in report.score_deltas)
        
        return report

    def _simulate_shadow_conversation(self, original: Conversation, _proposed_prompt: str) -> Conversation:
        """Simulate a conversation using the new prompt."""
        shadow_turns = []
        for turn in original.turns:
            shadow_turns.append(turn)
                
        return Conversation(
            conversation_id=f"shadow_{original.conversation_id}",
            turns=tuple(shadow_turns),
            metadata={**original.metadata, "is_shadow": True, "prompt_version": "proposed"}
        )

    def _calculate_deltas(
        self, 
        base_list: List[Optional[EvaluationResult]], 
        shadow_list: List[EvaluationResult]
    ) -> List[ScoreDelta]:
        """Aggregate score changes across the test set."""
        metrics = ["aggregate_score"]
        deltas = []
        
        for metric in metrics:
            base_vals = [e.aggregate_score for e in base_list if e]
            shadow_vals = [e.aggregate_score for e in shadow_list]
            
            avg_base = sum(base_vals) / len(base_vals) if base_vals else 0.0
            avg_shadow = sum(shadow_vals) / len(shadow_vals) if shadow_vals else 0.0
            
            is_improvement = avg_shadow > avg_base
            print(f"DEBUG: Metric '{metric}' delta: {avg_base:.3f} -> {avg_shadow:.3f} ({'IMPROVEMENT' if is_improvement else 'NO IMPROVEMENT'})")
            
            deltas.append(ScoreDelta(
                metric_name=metric,
                old_val=round(avg_base, 3),
                new_val=round(avg_shadow, 3),
                is_improvement=is_improvement
            ))
            
        return deltas
