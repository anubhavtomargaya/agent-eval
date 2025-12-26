from __future__ import annotations

from collections import Counter
from typing import Any

from src.db.repository import ConversationRepository
from src.models import FeedbackSignal, Conversation
from src.feedback.metrics import (
    AnnotationRecord,
    build_annotation_matrix,
    average_pairwise_kappa,
    krippendorff_alpha_nominal,
)

class FeedbackService:
    """Service for managing feedback and resolving disagreements."""

    def __init__(self, repository: ConversationRepository):
        self.repository = repository

    def add_feedback(self, conversation_id: str, feedback: FeedbackSignal) -> FeedbackSignal:
        """Add feedback and trigger disagreement check."""
        self.repository.add_feedback(conversation_id, feedback)
        # In a real async system, we'd trigger a background check here.
        # For now, we compute status on-read.
        return feedback

    def get_disagreements(self, limit: int = 50) -> list[dict[str, Any]]:
        """Identify conversations with conflicting human feedback."""
        # This is a naive implementation scanning all conversations.
        # In prod, we'd query a "needs_resolution" index.
        conversations = self.repository.list_conversations(limit=1000) 
        disagreements = []

        for conv in conversations:
            if not conv.feedback:
                continue
            
            # Group by signal (e.g. 'user_rating', 'helpfulness')
            signals: dict[str, list[FeedbackSignal]] = {}
            for f in conv.feedback:
                if f.source in ("user", "ops", "annotator"): # Only human signals
                    key = f.signal
                    if key not in signals:
                        signals[key] = []
                    signals[key].append(f)
            
            # Check for variance in any signal
            for signal_name, items in signals.items():
                if len(items) < 2:
                    continue
                
                values = [str(i.value) for i in items]
                if len(set(values)) > 1:
                    disagreements.append({
                        "conversation_id": conv.conversation_id,
                        "signal": signal_name,
                        "values": values,
                        "conflict_count": len(items),
                        "created_at": conv.created_at
                    })
                    if len(disagreements) >= limit:
                        break
            
            if len(disagreements) >= limit:
                break
                
        return disagreements

    def get_agreement_metrics(self, signal: str) -> dict[str, Any]:
        """Compute agreement metrics for a given signal across conversations."""
        records: list[AnnotationRecord] = []
        conversations = self.repository.list_conversations(limit=1000)

        for conv in conversations:
            for feedback in conv.feedback:
                if feedback.signal != signal:
                    continue
                if feedback.feedback_type != "explicit":
                    continue
                if not feedback.annotator_id:
                    continue

                item_id = conv.conversation_id
                if feedback.turn_id is not None:
                    item_id = f"{conv.conversation_id}:{feedback.turn_id}"

                records.append(AnnotationRecord(
                    item_id=item_id,
                    annotator_id=feedback.annotator_id,
                    label=str(feedback.value),
                ))

        matrix, items, annotators = build_annotation_matrix(records)
        return {
            "signal": signal,
            "items": len(items),
            "annotators": len(annotators),
            "pairwise_kappa": average_pairwise_kappa(matrix),
            "krippendorff_alpha": krippendorff_alpha_nominal(matrix),
        }

    def resolve_disagreement(self, conversation_id: str, signal: str, resolution_value: Any, resolver_id: str) -> None:
        """Force a resolution for a disagreement."""
        # We model resolution as a new feedback entry with high authority
        resolution = FeedbackSignal(
            feedback_type="explicit",
            signal=signal,
            value=resolution_value,
            source="admin_resolution", # Special source
            annotator_id=resolver_id,
            notes="Manual resolution of disagreement",
            confidence=1.0
        )
        self.repository.add_feedback(conversation_id, resolution)

    def get_consensus_label(self, conversation: Conversation, signal_name: str) -> Any | None:
        """Get the consensus value for a signal (simple majority vote)."""
        relevant_feedback = [
            f for f in conversation.feedback 
            if f.signal == signal_name and f.feedback_type == "explicit"
        ]
        
        if not relevant_feedback:
            return None
            
        # 1. Check for admin resolution
        admin_res = next((f for f in relevant_feedback if f.source == "admin_resolution"), None)
        if admin_res:
            return admin_res.value
            
        # 2. Majority vote
        values = [str(f.value) for f in relevant_feedback]
        counts = Counter(values)
        most_common, count = counts.most_common(1)[0]
        
        # If tie or weak consensus, we could return None or a specific flag
        # For this prototype, we return the most common
        return most_common
