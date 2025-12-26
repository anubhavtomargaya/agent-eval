from __future__ import annotations
import uuid
from typing import List, Optional

from src.models import Conversation, EvaluationResult, EvaluatorResult
from src.db.repository import ConversationRepository
from src.config import get_settings
from src.evaluation.evaluators import EvaluatorRegistry, Evaluator

class EvaluationError(Exception):
    """Custom exception for evaluation-related errors."""
    pass

class EvaluationService:
    """The Context in the Strategy Pattern.
    
    Orchestrates the evaluation process by applying selected strategies 
    from a registry to conversations.
    """
    
    def __init__(
        self, 
        repository: ConversationRepository,
        registry: EvaluatorRegistry,
        enabled_evaluators: Optional[List[str]] = None
    ):
        """Initialize with dependency injection."""
        self.repository = repository
        self.registry = registry
        
        # Determine which evaluators to use
        if enabled_evaluators is None:
            settings = get_settings()
            enabled_evaluators = settings.enabled_evaluators
        
        self.enabled_evaluators = enabled_evaluators

    def _get_active_strategies(self) -> List[Evaluator]:
        """Fetch instantiated strategy objects from the registry."""
        strategies = []
        for name in self.enabled_evaluators:
            strategy = self.registry.get(name)
            if strategy:
                strategies.append(strategy)
            else:
                print(f"Warning: Configured evaluator '{name}' not found in registry.")
        return strategies

    def evaluate(self, conversation_id: str) -> EvaluationResult:
        """Evaluate a single conversation by ID."""
        conversation = self.repository.get_conversation(conversation_id)
        if conversation is None:
            raise EvaluationError(f"Conversation not found: {conversation_id}")
        
        return self.evaluate_conversation(conversation)

    def evaluate_conversation(self, conversation: Conversation) -> EvaluationResult:
        """Evaluate a conversation object using the injected strategies."""
        result = EvaluationResult(
            conversation_id=conversation.conversation_id,
            run_id=str(uuid.uuid4()),
            evaluations={},
            status="pending",
        )
        
        strategies = self._get_active_strategies()
        if not strategies:
            result.status = "completed"
            result.aggregate_score = 0.0
            return result
        
        # Apply each strategy
        for strategy in strategies:
            try:
                eval_result = strategy.evaluate(conversation)
                result.evaluations[strategy.evaluator_name] = eval_result
            except Exception as e:
                print(f"ERROR: Strategy '{strategy.evaluator_name}' failed: {e}")
                result.evaluations[strategy.evaluator_name] = EvaluatorResult(
                    evaluator_name=strategy.evaluator_name,
                    scores={},
                    issues=(),
                    confidence=0.0,
                    metadata={"error": str(e)},
                )
        
        # Post-processing
        result.compute_aggregate_score()
        result.aggregate_issues()
        result.status = "completed"
        
        # Persist
        self.repository.save_evaluation(result)
        
        return result

    def evaluate_batch(self, conversation_ids: List[str]) -> List[EvaluationResult]:
        """Evaluate multiple conversations in sequence."""
        return [self.evaluate(cid) for cid in conversation_ids]

    def evaluate_pending(self, force: bool = False) -> List[EvaluationResult]:
        """Evaluate all conversations that require processing."""
        if force:
            pending_ids = [c.conversation_id for c in self.repository.list_conversations(limit=100)]
        else:
            pending_ids = self.repository.get_pending_conversations()
            
        return self.evaluate_batch(pending_ids)

    # =========================================================================
    # Repository Proxy Methods (For API Compatibility)
    # =========================================================================

    def get_evaluation(self, conversation_id: str) -> Optional[EvaluationResult]:
        """Proxy to repository."""
        return self.repository.get_evaluation(conversation_id)

    def list_evaluations(self, limit: int = 100, offset: int = 0) -> List[EvaluationResult]:
        """Proxy to repository."""
        return self.repository.list_evaluations(limit=limit, offset=offset)

    def get_summary_stats(self) -> dict:
        """Compute basic summary statistics across all evaluations."""
        evals = self.repository.list_evaluations(limit=1000)
        if not evals:
            return {
                "total_evaluations": 0,
                "average_score": 0.0,
                "issue_counts": {}
            }
            
        total_score = sum(e.aggregate_score for e in evals)
        issue_counts = {}
        for e in evals:
            for issue in e.issues:
                issue_counts[issue.issue_type.value] = issue_counts.get(issue.issue_type.value, 0) + 1
                
        return {
            "total_evaluations": len(evals),
            "average_score": total_score / len(evals),
            "issue_counts": issue_counts
        }
