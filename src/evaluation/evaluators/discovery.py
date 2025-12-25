from __future__ import annotations
import importlib
import pkgutil
from typing import List
from .registry import EvaluatorRegistry
import src.evaluation.evaluators as evaluators_pkg

class EvaluatorDiscovery:
    """Discovery Service for finding and loading evaluation strategies.
    
    This encapsulates the filesystem logic, keeping it out of the Registry and Service.
    """
    
    @staticmethod
    def discover_and_register(registry: EvaluatorRegistry) -> List[str]:
        """Scans the evaluators package and registers all found strategies."""
        loaded_modules = []
        
        # Iterates over all modules in the src.evaluation.evaluators package
        for _, name, is_pkg in pkgutil.iter_modules(evaluators_pkg.__path__):
            if is_pkg or name in ['base', 'registry', 'discovery']:
                continue
                
            module_path = f"src.evaluation.evaluators.{name}"
            try:
                # Importing the module triggers the @register_evaluator decorator
                importlib.import_module(module_path)
                loaded_modules.append(module_path)
            except Exception as e:
                print(f"Warning: Discovery failed for {module_path}: {e}")
                
        return loaded_modules
