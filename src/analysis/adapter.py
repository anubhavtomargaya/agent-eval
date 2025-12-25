from typing import List, Dict, Any
from src.models import EvaluationResult, Conversation, Turn
from src.analysis.utils import construct_embedding_string

def flatten_issue(evaluation: EvaluationResult, conversation: Conversation) -> List[Dict[str, Any]]:
    """Flatten all issues in an evaluation into a canonical list for clustering.
    
    Each item in the list represents a single issue with its specific context.
    """
    flattened = []
    
    # Map turn IDs to content for quick lookup
    turn_map = {t.turn_id: t for t in conversation.turns}
    
    for issue in evaluation.issues:
        # Get context turn
        context_content = ""
        if issue.turn_id is not None and issue.turn_id in turn_map:
            turn = turn_map[issue.turn_id]
            context_content = turn.content
            # Add tool call info if present
            if turn.tool_calls:
                tool_names = [tc.tool_name for tc in turn.tool_calls]
                context_content += f" | Tools used: {', '.join(tool_names)}"
        
        # Build flattened dictionary
        item = {
            "issue_type": issue.issue_type.value,
            "severity": issue.severity.value,
            "description": issue.description,
            "turn_id": issue.turn_id,
            "conversation_id": evaluation.conversation_id,
            "context_content": context_content,
            "suggested_fix": issue.suggested_fix,
            "embedding_string": construct_embedding_string(
                issue.issue_type.value, 
                issue.description, 
                context_content
            )
        }
        flattened.append(item)
        
    return flattened

def prepare_batch_data(evaluations: List[EvaluationResult], conversations: List[Conversation]) -> List[Dict[str, Any]]:
    """Ochestrate flattening for a batch of evaluations."""
    all_flattened = []
    conv_map = {c.conversation_id: c for c in conversations}
    
    for eval_res in evaluations:
        conv = conv_map.get(eval_res.conversation_id)
        if conv:
            all_flattened.extend(flatten_issue(eval_res, conv))
            
    return all_flattened
