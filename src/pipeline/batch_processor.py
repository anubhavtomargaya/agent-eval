from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
from typing import Any, Dict, List

from src.db.repository import ConversationRepository, get_repository
from src.evaluation.evaluators import get_global_registry, EvaluatorDiscovery
from src.evaluation.service import EvaluationService
from src.ingestion.service import IngestionService, ValidationError
from src.analysis.service import AnalysisService


class BatchPipelineProcessor:
    """Dedicated processor for batch analysis with staged evaluation.

    ARCHITECTURE:
    - self.evaluation_service: Full service (all evaluators) for regression testing
    - Stage evaluation services: Isolated services with only stage-specific evaluators

    WORKFLOW:
    1. Load conversations from files
    2. Ingest into database
    3. Run fast heuristic evaluators on all conversations
    4. Run LLM evaluator on conversations with issues (efficiency optimization)
    5. Analyze patterns and generate proposals

    Designed for efficiency and visibility in batch processing workflows.
    """

    def __init__(
        self,
        repository: ConversationRepository | None = None,
        source_dir: str | Path = "data/travel_agent",
    ):
        """Initialize the batch processor.

        Args:
            repository: Optional repository instance
            source_dir: Directory containing conversation files
        """
        self.repository = repository or get_repository(data_dir="./data")
        self.source_dir = Path(source_dir)

        # Initialize services
        registry = get_global_registry()
        EvaluatorDiscovery.discover_and_register(registry)

        self.ingestion_service = IngestionService(self.repository)

        # Full evaluation service for regression testing (used by AnalysisService)
        self.evaluation_service = EvaluationService(self.repository, registry)
        self.analysis_service = AnalysisService(self.repository, self.evaluation_service)

        # Default evaluation stages
        self.default_stages = [
            {
                "name": "heuristic_stage",
                "evaluators": ["heuristic", "tool_call", "tool_causality"],
                "description": "Fast rule-based evaluators on all conversations",
                "filter_criteria": None  # Process all
            },
            {
                "name": "llm_stage",
                "evaluators": ["llm_judge"],
                "description": "LLM evaluation on conversations with issues",
                "filter_criteria": "has_issues"  # Only process those with issues
            }
        ]

    def run_batch_analysis(
        self,
        source_pattern: str = "*.json",
        custom_stages: List[Dict[str, Any]] | None = None,
        max_conversations: int | None = None,
    ) -> Dict[str, Any]:
        """Run complete batch analysis with staged evaluation.

        Args:
            source_pattern: Glob pattern for conversation files
            custom_stages: Optional custom evaluation stages
            max_conversations: Optional limit on conversations to process

        Returns:
            Complete analysis results with all stages
        """
        print("🚀 Starting Batch Analysis Pipeline")
        print("=" * 50)

        # Stage 1: Load conversations
        conversations = self._load_conversations(source_pattern, max_conversations)
        if not conversations:
            return {"error": "No conversations loaded"}

        # Stage 2: Ingest conversations
        ingestion_result = self._ingest_conversations(conversations)

        # Stage 3: Staged evaluation
        stages = custom_stages or self.default_stages
        evaluation_results = self._run_staged_evaluation(conversations, stages)

        # Stage 4: Analysis
        analysis_results = self._run_analysis(len(conversations))

        # Stage 5: Summary
        summary = self._generate_summary(conversations, evaluation_results, analysis_results)

        # Use only final stage evaluations for summary (most comprehensive)
        final_stage_evaluations = []
        if evaluation_results:
            # Group evaluations by conversation_id and take the latest (highest stage)
            eval_by_conv = {}
            for eval_result in evaluation_results:
                conv_id = eval_result.conversation_id
                eval_by_conv[conv_id] = eval_result  # Later stages override earlier ones

            final_stage_evaluations = list(eval_by_conv.values())

        return {
            "conversations": conversations,
            "ingestion": ingestion_result,
            "evaluations": evaluation_results,  # All evaluations from all stages
            "final_evaluations": final_stage_evaluations,  # Deduplicated final evaluations
            "analysis": analysis_results,
            "summary": summary,
            "stages_completed": len(stages) + 2  # Load, ingest + evaluation stages + analysis
        }

    def _load_conversations(
        self,
        source_pattern: str,
        max_conversations: int | None = None
    ) -> List[Dict[str, Any]]:
        """Load conversations from files matching the pattern."""
        print("\n📁 Stage 1: Loading Conversations")

        source_path = Path(self.source_dir)
        print(f"   Looking in directory: {source_path.absolute()}")
        print(f"   Using pattern: {source_pattern}")
        source_files = list(source_path.glob(source_pattern))

        if not source_files:
            print(f"❌ No files found matching pattern: {source_pattern}")
            return []

        print(f"📖 Found {len(source_files)} files matching '{source_pattern}'")

        conversations = []
        for i, file_path in enumerate(source_files, 1):
            try:
                data = json.loads(file_path.read_text())

                if isinstance(data, list):
                    conversations.extend(data)
                    print(f"   {i:2d}/{len(source_files)} ✅ {file_path.name:<25} → {len(data)} conversations")
                else:
                    conversations.append(data)
                    print(f"   {i:2d}/{len(source_files)} ✅ {file_path.name:<25} → 1 conversation")

                # Check limit
                if max_conversations and len(conversations) >= max_conversations:
                    print(f"   ⚠️ Reached max_conversations limit ({max_conversations})")
                    break

            except Exception as e:
                print(f"   {i:2d}/{len(source_files)} ❌ {file_path.name:<25} → ERROR: {str(e)[:40]}")
                continue

        # Apply final limit if specified
        if max_conversations and len(conversations) > max_conversations:
            conversations = conversations[:max_conversations]

        print(f"📥 Loaded {len(conversations)} conversations total")
        return conversations

    def _ingest_conversations(self, conversations: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Ingest conversations into the database."""
        print("\n🔄 Stage 2: Ingesting Conversations")

        try:
            result = self.ingestion_service.ingest_batch(conversations)
            print(f"✅ Ingested: {result.get('total', 0)} total, {result.get('new', 0)} new")
            return result
        except Exception as e:
            print(f"❌ Ingestion failed: {e}")
            return {"error": str(e)}

    def _run_staged_evaluation(
        self,
        conversations: List[Dict[str, Any]],
        stages: List[Dict[str, Any]]
    ) -> List[Any]:
        """Run staged evaluation on conversations."""
        print("\n🔄 Stage 3: Staged Evaluation")

        conversation_ids = [c["conversation_id"] for c in conversations]
        all_evaluations = []

        for stage_idx, stage in enumerate(stages, 3):  # Start from stage 3
            stage_name = stage["name"]
            evaluators = stage["evaluators"]
            description = stage.get("description", "")
            filter_criteria = stage.get("filter_criteria")

            print(f"\n🔄 Stage {stage_idx}: {stage_name}")
            print(f"   {description}")
            print(f"   Evaluators: {', '.join(evaluators)}")

            # Determine which conversations to evaluate
            target_ids = self._filter_conversations_for_stage(
                conversation_ids, filter_criteria
            )

            if not target_ids:
                print("   ⚠️ No conversations to evaluate in this stage")
                continue

            # Create fresh evaluation service for this stage (isolated from other stages)
            registry = get_global_registry()
            stage_eval_service = EvaluationService(
                self.repository, registry, enabled_evaluators=evaluators
            )

            # Evaluate conversations with progress
            stage_evaluations = self._evaluate_conversations_with_progress(
                stage_eval_service, target_ids, stage_idx
            )

            all_evaluations.extend(stage_evaluations)

        return all_evaluations

    def _filter_conversations_for_stage(
        self,
        conversation_ids: List[str],
        filter_criteria: str | None
    ) -> List[str]:
        """Filter conversations based on stage criteria."""
        if not filter_criteria:
            return conversation_ids

        if filter_criteria == "has_issues":
            # Get conversations that have issues from previous evaluations
            prev_evaluations = self.repository.list_evaluations(limit=1000)

            # Build lookup of conversation_id -> has_issues
            issues_lookup = {}
            for eval_result in prev_evaluations:
                issues_lookup[eval_result.conversation_id] = len(eval_result.issues) > 0

            # Filter to conversations with issues
            filtered_ids = [
                cid for cid in conversation_ids
                if issues_lookup.get(cid, False)
            ]

            print(f"   🔍 Filtered to {len(filtered_ids)} conversations with issues")
            return filtered_ids

        return conversation_ids

    def _evaluate_conversations_with_progress(
        self,
        eval_service: EvaluationService,
        conversation_ids: List[str],
        stage_number: int
    ) -> List[Any]:
        """Evaluate conversations one by one with progress tracking."""
        evaluations = []

        print(f"   📊 Processing {len(conversation_ids)} conversations...")

        for i, conv_id in enumerate(conversation_ids, 1):
            try:
                # Evaluate single conversation
                eval_result = eval_service.evaluate(conv_id)
                evaluations.append(eval_result)

                # Progress indicator
                has_issues = len(eval_result.issues) > 0
                status = "❌" if has_issues else "✅"
                score = f"{eval_result.aggregate_score:.2f}"
                issues_count = len(eval_result.issues)

                print(f"      {i:2d}/{len(conversation_ids)} {status} {conv_id[:28]:<28} Score: {score} Issues: {issues_count}")

            except Exception as e:
                print(f"      {i:2d}/{len(conversation_ids)} ❌ {conv_id[:28]:<28} ERROR: {str(e)[:40]}")
                continue

        # Stage summary
        issues_found = sum(1 for e in evaluations if len(e.issues) > 0)
        print(f"   ✅ Stage {stage_number} complete: {len(evaluations)} evaluated, {issues_found} with issues")

        return evaluations

    def _run_analysis(self, conversation_count: int) -> List[Any]:
        """Run failure pattern analysis."""
        print("\n🔄 Final Stage: Analysis")

        try:
            print(f"   📈 Analyzing evaluations for patterns...")
            proposals = self.analysis_service.run_analysis_cycle(limit=conversation_count)
            print(f"   🎯 Generated {len(proposals)} improvement proposals")
            return proposals
        except Exception as e:
            print(f"   ❌ Analysis failed: {e}")
            return []

    def _generate_summary(
        self,
        conversations: List[Dict[str, Any]],
        evaluations: List[Any],
        proposals: List[Any]
    ) -> Dict[str, Any]:
        """Generate comprehensive summary of the batch analysis."""
        print("\n📊 Batch Analysis Complete")

        # Use deduplicated final evaluations for summary
        final_evaluations = []
        if evaluations:
            eval_by_conv = {}
            for eval_result in evaluations:
                conv_id = eval_result.conversation_id
                eval_by_conv[conv_id] = eval_result  # Later stages override
            final_evaluations = list(eval_by_conv.values())

        total_evaluations = len(final_evaluations)
        conversations_with_issues = sum(1 for e in final_evaluations if len(e.issues) > 0)
        total_issues = sum(len(e.issues) for e in final_evaluations)
        avg_score = sum(e.aggregate_score for e in final_evaluations) / total_evaluations if total_evaluations > 0 else 0

        summary = {
            "total_conversations": len(conversations),
            "total_evaluations": total_evaluations,
            "conversations_with_issues": conversations_with_issues,
            "total_issues": total_issues,
            "average_score": round(avg_score, 3),
            "proposals_count": len(proposals),
            "timestamp": datetime.utcnow().isoformat()
        }

        print(f"   Conversations: {summary['total_conversations']}")
        print(f"   With Issues: {summary['conversations_with_issues']}")
        print(f"   Total Issues: {summary['total_issues']}")
        print(f"   Average Score: {summary['average_score']:.2f}")
        print(f"   Proposals: {summary['proposals_count']}")

        return summary
