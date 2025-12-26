from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import shutil
from typing import Any

from src.db.repository import ConversationRepository, get_repository
from src.evaluation.evaluators import get_global_registry, EvaluatorDiscovery
from src.evaluation.service import EvaluationService
from src.ingestion.service import IngestionService, ValidationError
from src.analysis.service import AnalysisService
from src.feedback.service import FeedbackService
from src.models import FeedbackSignal


class PipelineProcessor:
    """End-to-end pipeline runner for ingestion, evaluation, and analysis."""

    def __init__(
        self,
        repository: ConversationRepository | None = None,
        source_dir: str | Path = "data/unprocessed",
        processed_dir: str | Path = "data/processed",
    ):
        self.repository = repository or get_repository(data_dir="./data")
        self.source_dir = Path(source_dir)
        self.processed_dir = Path(processed_dir)

        registry = get_global_registry()
        EvaluatorDiscovery.discover_and_register(registry)

        self.ingestion_service = IngestionService(self.repository)
        self.evaluation_service = EvaluationService(self.repository, registry)
        self.analysis_service = AnalysisService(self.repository, self.evaluation_service)
        self.feedback_service = FeedbackService(self.repository)

    def run(
        self,
        conversations: list[dict[str, Any]] | None = None,
        feedback: dict[str, list[dict[str, Any]]] | None = None,
        evaluate_pending: bool = True,
    ) -> dict[str, Any]:
        """Ingest conversations (or load from source_dir), attach feedback, then evaluate."""
        file_paths: list[Path] = []
        if conversations is None:
            conversations, file_paths = self._load_conversations_from_dir()

        result = self.ingestion_service.ingest_batch(conversations)

        if file_paths:
            self._move_processed_files(file_paths)

        if feedback:
            for conversation_id, items in feedback.items():
                for item in items:
                    self.feedback_service.add_feedback(
                        conversation_id,
                        self._parse_feedback(item),
                    )

        evaluations = []
        if evaluate_pending:
            evaluations = self.evaluation_service.evaluate_pending(force=True)

        return {
            "ingestion": result,
            "evaluations": evaluations,
        }

    def run_analysis(self, limit: int = 100):
        """Run failure pattern detection and proposal generation."""
        return self.analysis_service.run_analysis_cycle(limit=limit)

    def flag_for_review(
        self,
        strategy: str = "confidence",
        limit: int = 50,
        **kwargs: Any,
    ) -> list[str]:
        """Flag conversations for human review using a sampling strategy."""
        from src.feedback.sampling import sample_conversations

        conversations = self.repository.list_conversations(limit=10000, offset=0)
        evaluations = self.repository.list_evaluations(limit=10000, offset=0)

        samples = sample_conversations(
            strategy=strategy,
            conversations=conversations,
            evaluations=evaluations,
            limit=limit,
            **kwargs,
        )

        flagged_ids = []
        for sample in samples:
            self.repository.flag_for_review(
                sample.conversation_id,
                reason=f"sampled:{strategy}",
            )
            flagged_ids.append(sample.conversation_id)

        return flagged_ids

    def process_feedback(
        self,
        signals: list[str] | None = None,
        flag_disagreements: bool = True,
    ) -> dict[str, Any]:
        """Process feedback to surface disagreements and agreement metrics."""
        disagreements = self.feedback_service.get_disagreements(limit=200)

        if flag_disagreements:
            for item in disagreements:
                self.repository.flag_for_review(
                    item["conversation_id"],
                    reason="disagreement",
                )

        metrics = {}
        if signals:
            for signal in signals:
                metrics[signal] = self.feedback_service.get_agreement_metrics(signal)

        return {
            "disagreements": disagreements,
            "metrics": metrics,
        }

    def apply_and_verify(
        self,
        proposal_id: str,
        prompts_path: str | Path = "data/regression_prompts.json",
    ):
        """Apply a proposal and run the real regression gate."""
        self.analysis_service.apply_proposal(proposal_id)
        prompts = json.loads(Path(prompts_path).read_text())
        return self.analysis_service.run_real_regression(proposal_id, prompts)

    def _parse_feedback(self, item: dict[str, Any]) -> FeedbackSignal:
        """Normalize feedback payloads into FeedbackSignal objects."""
        timestamp = item.get("timestamp")
        parsed = None
        if isinstance(timestamp, str):
            try:
                parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError:
                parsed = None

        return FeedbackSignal(
            feedback_type=item.get("feedback_type", "explicit"),
            signal=item.get("signal", ""),
            value=item.get("value"),
            source=item.get("source", ""),
            timestamp=parsed or datetime.utcnow(),
            turn_id=item.get("turn_id"),
            annotator_id=item.get("annotator_id"),
            confidence=item.get("confidence"),
            notes=item.get("notes"),
        )

    def _load_conversations_from_dir(self) -> tuple[list[dict[str, Any]], list[Path]]:
        """Load JSON conversations from the source_dir."""
        conversations: list[dict[str, Any]] = []
        files: list[Path] = []

        self.source_dir.mkdir(parents=True, exist_ok=True)
        for path in self.source_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text())
            except json.JSONDecodeError:
                continue

            if isinstance(data, dict):
                if "conversations" in data:
                    conversations.extend(data["conversations"])
                else:
                    conversations.append(data)
            elif isinstance(data, list):
                conversations.extend(data)

            files.append(path)

        return conversations, files

    def _move_processed_files(self, files: list[Path]) -> None:
        """Move ingested files to processed_dir."""
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        for path in files:
            target = self.processed_dir / path.name
            shutil.move(str(path), str(target))
