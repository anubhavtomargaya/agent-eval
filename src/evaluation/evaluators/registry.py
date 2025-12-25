from __future__ import annotations
from typing import Dict, Type, List, Optional
from .base import Evaluator

class EvaluatorRegistry:
    """A pure registry for managing evaluation strategies.
    
    This class is agnostic of how strategies are discovered or used.
    It simply provides a lookup and storage mechanism.
    """
    
    def __init__(self):
        self._strategies: Dict[str, Type[Evaluator]] = {}
    
    def register(self, strategy_cls: Type[Evaluator]) -> None:
        """Register a strategy class by its name."""
        # Instantiate once to get name if not static
        temp_instance = strategy_cls()
        self._strategies[temp_instance.evaluator_name] = strategy_cls
    
    def get(self, name: str) -> Optional[Evaluator]:
        """Get a fresh instance of a strategy by name."""
        strategy_cls = self._strategies.get(name)
        return strategy_cls() if strategy_cls else None
    
    def list_strategies(self) -> List[str]:
        """List all registered strategy names."""
        return list(self._strategies.keys())

# Global singleton for decorator-based registration if needed
_global_registry = EvaluatorRegistry()

def register_evaluator(cls: Type[Evaluator]) -> Type[Evaluator]:
    """Decorator for easy strategy registration."""
    _global_registry.register(cls)
    return cls

def get_global_registry() -> EvaluatorRegistry:
    """Access the global decorator-populated registry."""
    return _global_registry
