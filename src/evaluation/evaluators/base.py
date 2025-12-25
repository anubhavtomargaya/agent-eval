from __future__ import annotations
from abc import ABC, abstractmethod
import time
from typing import ClassVar, Any
from src.models import Conversation, EvaluatorResult

class Evaluator(ABC):
    """Abstract base class for all evaluation strategies.
    
    This defines the formal interface that all evaluators must follow.
    """
    
    @property
    @abstractmethod
    def evaluator_name(self) -> str:
        """Return the unique name of this evaluator."""
        pass
    
    @abstractmethod
    def _evaluate(self, conversation: Conversation) -> EvaluatorResult:
        """Internal evaluation logic to be implemented by strategies."""
        pass
    
    def evaluate(self, conversation: Conversation) -> EvaluatorResult:
        """Template method to handle orchestration, timing, and error safety."""
        start_time = time.perf_counter()
        try:
            result = self._evaluate(conversation)
            latency_ms = (time.perf_counter() - start_time) * 1000
            
            # Enrich result with metadata
            result.latency_ms = latency_ms
            result.metadata = {**(result.metadata or {}), "latency_ms": latency_ms}
            return result
        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            return EvaluatorResult(
                evaluator_name=self.evaluator_name,
                scores={},
                issues=(),
                confidence=0.0,
                metadata={"error": str(e), "latency_ms": latency_ms},
                latency_ms=latency_ms,
            )
