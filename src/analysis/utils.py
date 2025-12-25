from typing import List, Optional
from src.utils.llm import LLMClientFactory

def get_token_count(text: str) -> int:
    """Approximate token count (4 chars per token).
    
    Using a simple heuristic for the demo/assignment.
    In production, use tiktoken.
    """
    return len(text) // 4

def generate_embedding(text: str, model: str = "text-embedding-3-small") -> List[float]:
    """Generate vector embedding for the given text."""
    factory = LLMClientFactory()
    client = factory.get_client()
    
    # Check if we have a key, otherwise return mock
    # (Checking the client directly since factory doesn't expose it easily)
    if not client.api_key:
        # Return a zero vector for mocks
        return [0.0] * 1536
        
    response = client.embeddings.create(
        input=[text],
        model=model
    )
    return response.data[0].embedding

def construct_embedding_string(issue_type: str, description: str, turn_content: str) -> str:
    """Build a contextual string for embedding.
    
    We keep it high-level to ensure similar patterns group together even if 
    specific user variables (dates, names) vary.
    """
    return f"Type: {issue_type} | Issue: {description}"
