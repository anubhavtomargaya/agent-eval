from typing import List
from pathlib import Path
import json
from src.analysis.models import ImprovementProposal, RegressionReport
from src.analysis.clustering import ClusteringEngine
from src.analysis.suggestions import SuggestionEngine
from src.analysis.regression import RegressionTester
from src.analysis.adapter import prepare_batch_data
from src.db.repository import ConversationRepository
from src.evaluation.service import EvaluationService
from src.analysis.models import ProposalStatus

class AnalysisService:
    """The orchestrator for the Analysis Module."""
    
    def __init__(
        self, 
        repository: ConversationRepository,
        evaluation_service: EvaluationService
    ):
        self.repository = repository
        self.evaluation_service = evaluation_service
        self.clustering_engine = ClusteringEngine()
        self.suggestion_engine = SuggestionEngine()
        self.regression_tester = RegressionTester(evaluation_service)

    def run_analysis_cycle(self, limit: int = 100) -> List[ImprovementProposal]:
        """Run a full cycle of discovery: Cluster -> Suggest."""
        
        # 1. Fetch recent evaluations and conversations
        evals = self.repository.list_evaluations(limit=limit)
        # Filter for only those with issues
        evals_with_issues = [e for e in evals if e.issues]
        
        print(f"DEBUG: Analysis discovery found {len(evals_with_issues)} evaluations with issues out of {len(evals)} reviewed.")
        
        if not evals_with_issues:
            return []
            
        conv_ids = [e.conversation_id for e in evals_with_issues]
        # In a real system, we'd batch fetch. Here we loop for simplicity.
        convs = [self.repository.get_conversation(cid) for cid in conv_ids]
        convs = [c for c in convs if c] # Filter None
        
        # 2. Transform into flattened items
        flattened_items = prepare_batch_data(evals_with_issues, convs)
        
        # 3. Cluster
        print(f"DEBUG: Clustering {len(flattened_items)} granular issues...")
        clusters = self.clustering_engine.cluster_issues(flattened_items)
        print(f"DEBUG: Discovery phase identified {len(clusters)} distinct failure patterns.")
        
        # 4. Generate Suggestions for each cluster using versioned artifacts
        # These artifacts are demo-friendly stand-ins for a real prompt/tool registry.
        current_prompt, prompt_path = self._load_prompt()
        tool_definitions, tool_schema_path = self._load_tool_definitions()
        
        proposals = []
        for cluster in clusters:
            print(f"DEBUG: Generating improvement proposal for pattern: '{cluster.label}' (Significance: {cluster.significance_score:.1f})")
            proposal = self.suggestion_engine.generate_proposal(cluster, current_prompt, tool_definitions)
            proposal.metadata.update({
                "prompt_path": str(prompt_path),
                "tool_schema_path": str(tool_schema_path),
                "artifact_version_hint": "v1",
            })
            # Persist the proposal
            self.repository.save_proposal(proposal)
            proposals.append(proposal)
            
        print(f"DEBUG: Analysis cycle complete. Generated {len(proposals)} proposals.")
        return proposals

    def verify_proposal(self, proposal_id: str) -> RegressionReport:
        """Run regression tests for a specific proposal."""
        proposal = self.repository.get_proposal(proposal_id)
        if not proposal:
            raise ValueError(f"Proposal not found: {proposal_id}")
            
        # 1. Fetch 'Golden Dataset' (for demo: sample 20 random conversations)
        test_set = self.repository.list_conversations(limit=20)
        
        # 2. Run regression
        print(f"DEBUG: Starting regression verification for proposal {proposal_id} on {len(test_set)} test cases...")
        report = self.regression_tester.run_regression(proposal, test_set)
        
        # 3. Update proposal with report
        improvement_count = sum(1 for d in report.score_deltas if d.is_improvement)
        print(f"DEBUG: Regression complete for {proposal_id}. Improvement detected in {improvement_count} metrics.")
        
        proposal.regression_report = report
        from src.analysis.models import ProposalStatus
        proposal.status = ProposalStatus.TESTING
        self.repository.save_proposal(proposal)
        
        return report

    def apply_proposal(self, proposal_id: str) -> dict[str, str]:
        """Apply a proposal by writing it to the active artifact files."""
        proposal = self.repository.get_proposal(proposal_id)
        if not proposal:
            raise ValueError(f"Proposal not found: {proposal_id}")

        artifacts = {}
        if proposal.type.value == "prompt":
            path = Path("artifacts/prompts/active_prompt.txt")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(proposal.proposed_content)
            artifacts["prompt_path"] = str(path)
        elif proposal.type.value == "tool":
            path = Path("artifacts/tools/active_tool_schema.json")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(proposal.proposed_content)
            artifacts["tool_schema_path"] = str(path)

        proposal.status = ProposalStatus.APPROVED
        proposal.metadata.update(artifacts)
        self.repository.save_proposal(proposal)
        return artifacts

    def run_real_regression(self, proposal_id: str, prompts: list[str]) -> RegressionReport:
        """Run a real regression using the demo agent and active artifacts."""
        proposal = self.repository.get_proposal(proposal_id)
        if not proposal:
            raise ValueError(f"Proposal not found: {proposal_id}")

        report = self.regression_tester.run_real_regression(proposal, prompts)
        proposal.regression_report = report
        self.repository.save_proposal(proposal)
        return report

    def _load_prompt(self) -> tuple[str, Path]:
        """Load the current prompt artifact for demo purposes."""
        prompt_path = Path("artifacts/prompts/prompt_v1.txt")
        if not prompt_path.exists():
            return "You are a helpful travel assistant.", prompt_path
        return prompt_path.read_text(), prompt_path

    def _load_tool_definitions(self) -> tuple[dict, Path]:
        """Load the current tool schema artifact for demo purposes."""
        schema_path = Path("artifacts/tools/tool_schema_v1.json")
        if not schema_path.exists():
            return {}, schema_path
        try:
            return json.loads(schema_path.read_text()), schema_path
        except json.JSONDecodeError:
            return {}, schema_path
