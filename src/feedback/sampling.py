from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import random
from typing import Any

from src.models import Conversation, EvaluationResult


@dataclass
class ConversationSample:
    """Lightweight sample metadata for review workflows."""
    conversation_id: str
    created_at: datetime
    turn_count: int
    metadata: dict[str, Any]
    aggregate_score: float | None = None
    issues_count: int | None = None


class SamplingStrategy:
    """Base class for sampling strategies."""
    name: str = "base"

    def sample(
        self,
        conversations: list[Conversation],
        evaluations: list[EvaluationResult],
        limit: int,
        **kwargs: Any,
    ) -> list[ConversationSample]:
        raise NotImplementedError


class EvaluationSampler(SamplingStrategy):
    """Sample conversations based on evaluation scores and issue counts."""
    name = "evaluation"

    def sample(
        self,
        conversations: list[Conversation],
        evaluations: list[EvaluationResult],
        limit: int,
        **kwargs: Any,
    ) -> list[ConversationSample]:
        max_score = float(kwargs.get("max_score", 0.6))
        min_issues = int(kwargs.get("min_issues", 1))

        conv_map = {c.conversation_id: c for c in conversations}
        samples: list[ConversationSample] = []

        for evaluation in evaluations:
            if evaluation.aggregate_score > max_score:
                continue
            if len(evaluation.issues) < min_issues:
                continue
            conv = conv_map.get(evaluation.conversation_id)
            if conv is None:
                continue
            samples.append(_sample_from_conversation(conv, evaluation))
            if len(samples) >= limit:
                break

        return samples


class RandomSampler(SamplingStrategy):
    """Sample conversations uniformly at random."""
    name = "random"

    def sample(
        self,
        conversations: list[Conversation],
        evaluations: list[EvaluationResult],
        limit: int,
        **kwargs: Any,
    ) -> list[ConversationSample]:
        seed = kwargs.get("seed")
        rng = random.Random(seed)
        candidates = list(conversations)
        rng.shuffle(candidates)

        eval_map = {e.conversation_id: e for e in evaluations}
        return [
            _sample_from_conversation(conv, eval_map.get(conv.conversation_id))
            for conv in candidates[:limit]
        ]


class RecentSampler(SamplingStrategy):
    """Sample most recent conversations."""
    name = "recent"

    def sample(
        self,
        conversations: list[Conversation],
        evaluations: list[EvaluationResult],
        limit: int,
        **kwargs: Any,
    ) -> list[ConversationSample]:
        eval_map = {e.conversation_id: e for e in evaluations}
        candidates = sorted(conversations, key=lambda c: c.created_at, reverse=True)
        return [
            _sample_from_conversation(conv, eval_map.get(conv.conversation_id))
            for conv in candidates[:limit]
        ]


class ConfidenceSampler(SamplingStrategy):
    """Sample conversations with low evaluation confidence."""
    name = "confidence"

    def sample(
        self,
        conversations: list[Conversation],
        evaluations: list[EvaluationResult],
        limit: int,
        **kwargs: Any,
    ) -> list[ConversationSample]:
        threshold = float(kwargs.get("threshold", 0.8)) # Default high threshold to catch anything below it
        
        # 1. Filter evaluations with low confidence
        low_conf_evals = []
        for e in evaluations:
            # Check aggregate confidence if available, or calculate average of sub-evaluators
            # Currently EvaluationResult doesn't store aggregate confidence, so we compute it
            confs = [res.confidence for res in e.evaluations.values()]
            if not confs:
                continue
            
            avg_conf = sum(confs) / len(confs)
            if avg_conf < threshold:
                low_conf_evals.append(e)

        # 2. Map back to conversations
        conv_map = {c.conversation_id: c for c in conversations}
        samples = []
        
        for e in low_conf_evals:
            conv = conv_map.get(e.conversation_id)
            if conv:
                samples.append(_sample_from_conversation(conv, e))
                if len(samples) >= limit:
                    break
                    
        return samples


class MetadataSampler(SamplingStrategy):
    """Sample conversations matching metadata filters."""
    name = "metadata"

    def sample(
        self,
        conversations: list[Conversation],
        evaluations: list[EvaluationResult],
        limit: int,
        **kwargs: Any,
    ) -> list[ConversationSample]:
        key = kwargs.get("metadata_key")
        value = kwargs.get("metadata_value")

        if not key:
            raise ValueError("metadata_key is required for metadata sampling.")

        eval_map = {e.conversation_id: e for e in evaluations}
        samples: list[ConversationSample] = []

        for conv in conversations:
            if key not in conv.metadata:
                continue
            if value is not None and str(conv.metadata.get(key)) != str(value):
                continue
            samples.append(_sample_from_conversation(conv, eval_map.get(conv.conversation_id)))
            if len(samples) >= limit:
                break

        return samples


_STRATEGIES: dict[str, SamplingStrategy] = {
    "evaluation": EvaluationSampler(),
    "random": RandomSampler(),
    "recent": RecentSampler(),
    "metadata": MetadataSampler(),
    "confidence": ConfidenceSampler(),
}


def list_strategies() -> list[str]:
    """List supported sampling strategy names."""
    return list(_STRATEGIES.keys())


def sample_conversations(
    strategy: str,
    conversations: list[Conversation],
    evaluations: list[EvaluationResult],
    limit: int,
    **kwargs: Any,
) -> list[ConversationSample]:
    """Dispatch to the selected sampling strategy."""
    if strategy == "evaluation" and not evaluations:
        strategy = "random"
    
    sampler = _STRATEGIES.get(strategy)
    if not sampler:
        raise ValueError(f"Unknown sampling strategy: {strategy}")
    return sampler.sample(conversations, evaluations, limit, **kwargs)


def _sample_from_conversation(
    conversation: Conversation,
    evaluation: EvaluationResult | None,
) -> ConversationSample:
    """Create a sample from a conversation and optional evaluation."""
    return ConversationSample(
        conversation_id=conversation.conversation_id,
        created_at=conversation.created_at,
        turn_count=len(conversation.turns),
        metadata=conversation.metadata,
        aggregate_score=evaluation.aggregate_score if evaluation else None,
        issues_count=len(evaluation.issues) if evaluation else None,
    )
