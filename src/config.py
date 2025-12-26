from __future__ import annotations
"""Configuration settings for the AI Agent Evaluation Pipeline."""

from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Model configuration for Pydantic v2
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False
    )
    
    # Database
    database_url: str = "sqlite:///./ai_agent_eval.db"
    
    # OpenAI
    openai_api_key: str = ""
    openai_key: str = ""
    openai_model: str = "gpt-4o"
    

    # API settings
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    
    @property
    def effective_openai_key(self) -> str:
        """Get the effective OpenAI API key (checking both names)."""
        return self.openai_key or self.openai_api_key

    @property
    def enabled_evaluators(self) -> list[str]:
        """List of all enabled evaluators for full production-grade analysis."""
        return [
            "llm_judge", 
            "tool_causality", 
            "heuristic", 
            "tool_call", 
            "coherence"
        ]


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
