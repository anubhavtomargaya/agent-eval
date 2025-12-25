import os
import sys
# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.db.repository import get_repository
from src.evaluation.service import EvaluationService
from src.evaluation.evaluators import EvaluatorRegistry
from src.analysis.service import AnalysisService

def main():
    print("🚀 Starting Analysis Pipeline Demo...")
    
    # 1. Initialize dependencies
    repository = get_repository(data_dir="./data")
    registry = EvaluatorRegistry()
    eval_service = EvaluationService(repository, registry)
    analysis_service = AnalysisService(repository, eval_service)
    
    # 2. Ensure we have evaluations to analyze
    print("📊 Evaluating pending conversations...")
    eval_service.evaluate_pending(force=True)
    
    # 3. Run Analysis Cycle (Cluster -> Suggest)
    print("🔍 Running Failure Pattern Analysis...")
    proposals = analysis_service.run_analysis_cycle(limit=10)
    
    if not proposals:
        print("✅ No systemic failure patterns detected.")
        return

    print(f"✨ Detected {len(proposals)} Improvement Proposals!")
    
    for i, p in enumerate(proposals):
        print(f"\n--- Proposal {i+1}: {p.proposal_id} ---")
        print(f"Pattern  : {p.failure_pattern}")
        print(f"Rationale: {p.rationale}")
        print(f"Evidence : {len(p.evidence_ids)} conversations linked")
        print(f"Action   : Proposed new prompt snippet generated.")

        # 4. Run Regression for the first proposal
        if i == 0:
            print("\n🧪 Running Regression Test Harness...")
            report = analysis_service.verify_proposal(p.proposal_id)
            print(f"Status   : {p.status}")
            for delta in report.score_deltas:
                arrow = "📈" if delta.is_improvement else "📉"
                print(f"Metric   : {delta.metric_name} | {delta.old_val} -> {delta.new_val} {arrow}")

if __name__ == "__main__":
    main()
