from __future__ import annotations
import os
from enum import Enum
from openai import OpenAI
from src.config import get_settings

class LLMModel(Enum):
    """Supported LLM models."""
    OPENAI_GPT_4_O = "gpt-4o"

class LLMClientFactory:
    """Simplified LLM client factory focusing on standard OpenAI."""
    
    def __init__(self):
        settings = get_settings()
        # Use OPENAI_KEY from env as requested
        api_key = settings.openai_key or os.getenv("OPENAI_KEY")
        print(f"DEBUG: Initializing simple OpenAI client (Key present: {bool(api_key)})")
        self.client = OpenAI(api_key=api_key)

    def get_client(self):
        """Return the standard OpenAI client."""
        return self.client
