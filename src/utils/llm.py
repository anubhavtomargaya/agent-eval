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
        # Use effective_openai_key which checks both openai_key and openai_api_key
        api_key = settings.effective_openai_key or os.getenv("OPENAI_KEY") or os.getenv("OPENAI_API_KEY")
        
        if api_key:
            # Fix for 'proxies' argument mismatch in some environment versions
            # We manually instantiate the http client to avoid the library's default behavior that might be passing unsupported args
            import httpx
            http_client = httpx.Client()
            self.client = OpenAI(api_key=api_key, http_client=http_client)
        else:
            # Start: Critical Error as requested by user
            # We should fail if no key is provided in a production-like/assignment environment
            raise ValueError("CRITICAL: OPENAI_API_KEY not found. Operations requiring LLM will fail.")

    def get_client(self):
        """Return the standard OpenAI client (or None if in mock mode)."""
        return self.client
