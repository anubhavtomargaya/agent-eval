"""Coherence Evaluator - Checks context maintenance across conversation turns.

This evaluator assesses:
- Context retention: Does the assistant remember earlier information?
- Consistency: Are responses consistent with previous statements?
- Reference handling: Does the assistant correctly resolve references (pronouns, "that", etc.)?

Scores (0-1):
- context_retention: How well context is maintained across turns
- consistency: How consistent responses are with each other
- reference_accuracy: How well references are resolved
"""

from typing import Any
import re

from .base import Evaluator
from .registry import register_evaluator
from src.models import (
    Conversation,
    Turn,
    Role,
    EvaluatorResult,
    Issue,
    IssueType,
    IssueSeverity,
)


# Keywords that often indicate references to earlier context
REFERENCE_PATTERNS = [
    r"\bthat\b",
    r"\bthose\b", 
    r"\bthis\b",
    r"\bthese\b",
    r"\bit\b",
    r"\bthem\b",
    r"\bthe same\b",
    r"\bearlier\b",
    r"\bpreviously\b",
    r"\bbefore\b",
    r"\bmentioned\b",
    r"\bas I said\b",
    r"\bmy preference\b",
    r"\bwhat I asked\b",
]

# Contradiction indicators
CONTRADICTION_PATTERNS = [
    (r"\byes\b", r"\bno\b"),
    (r"\bcan\b", r"\bcannot\b"),
    (r"\bwill\b", r"\bwon't\b"),
    (r"\bis\b", r"\bisn't\b"),
    (r"\bare\b", r"\baren't\b"),
]


@register_evaluator
class CoherenceEvaluator(Evaluator):
    """Evaluator for multi-turn coherence and context handling.
    
    Configuration:
        min_turns_for_eval: Minimum turns needed for coherence evaluation
        context_window: Number of previous turns to consider for context
    """
    
    def __init__(
        self,
        min_turns_for_eval: int = 3,
        context_window: int = 5,
    ):
        self.min_turns_for_eval = min_turns_for_eval
        self.context_window = context_window
    
    @property
    def evaluator_name(self) -> str:
        return "coherence"
    
    def _extract_key_entities(self, text: str) -> set[str]:
        """Extract potential key entities from text (simplified)."""
        # Extract capitalized words (likely proper nouns/entities)
        entities = set(re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', text))
        
        # Extract quoted strings
        quotes = set(re.findall(r'"([^"]+)"', text))
        entities.update(quotes)
        
        # Extract numbers and dates
        numbers = set(re.findall(r'\b\d+(?:\.\d+)?\b', text))
        dates = set(re.findall(r'\b\d{4}-\d{2}-\d{2}\b', text))
        entities.update(numbers)
        entities.update(dates)
        
        return entities
    
    def _check_context_retention(
        self, 
        conversation: Conversation
    ) -> tuple[float, list[Issue]]:
        """Check if important context is retained across turns."""
        issues = []
        
        # Build context from user turns
        user_entities_by_turn: dict[int, set[str]] = {}
        for turn in conversation.turns:
            if turn.role == Role.USER:
                entities = self._extract_key_entities(turn.content)
                if entities:
                    user_entities_by_turn[turn.turn_id] = entities
        
        # Check if assistant turns reference earlier entities
        context_hits = 0
        context_checks = 0
        
        assistant_turns = [t for t in conversation.turns if t.role == Role.ASSISTANT]
        
        for i, turn in enumerate(assistant_turns):
            if i == 0:
                continue  # Skip first assistant turn
            
            turn_entities = self._extract_key_entities(turn.content)
            
            # Check for references to earlier context
            for ref_turn_id, ref_entities in user_entities_by_turn.items():
                if ref_turn_id < turn.turn_id:
                    # Check if any earlier entity appears in current turn
                    overlap = turn_entities & ref_entities
                    if overlap:
                        context_hits += 1
                    context_checks += 1
        
        # Check for context loss patterns
        for i, turn in enumerate(assistant_turns):
            content_lower = turn.content.lower()
            
            # Phrases indicating context loss
            context_loss_phrases = [
                "i don't have access to",
                "i cannot see",
                "you haven't told me",
                "could you remind me",
                "what was your",
                "i'm not sure what you",
            ]
            
            for phrase in context_loss_phrases:
                if phrase in content_lower and i > 0:
                    # Check if context was actually provided earlier
                    issues.append(Issue(
                        issue_type=IssueType.CONTEXT_LOSS,
                        severity=IssueSeverity.MEDIUM,
                        description=f"Possible context loss at turn {turn.turn_id}: '{phrase}'",
                        turn_id=turn.turn_id,
                        details={"phrase": phrase},
                    ))
        
        # Compute score
        if context_checks == 0:
            score = 1.0  # No context to check
        else:
            score = context_hits / context_checks
        
        return score, issues
    
    def _check_consistency(
        self, 
        conversation: Conversation
    ) -> tuple[float, list[Issue]]:
        """Check for contradictory statements across turns."""
        issues = []
        inconsistencies = 0
        
        assistant_turns = [t for t in conversation.turns if t.role == Role.ASSISTANT]
        
        if len(assistant_turns) < 2:
            return 1.0, []
        
        # Simple contradiction detection
        for i in range(len(assistant_turns)):
            for j in range(i + 1, len(assistant_turns)):
                turn_i = assistant_turns[i]
                turn_j = assistant_turns[j]
                
                content_i = turn_i.content.lower()
                content_j = turn_j.content.lower()
                
                # Check for potential contradictions
                for pos_pattern, neg_pattern in CONTRADICTION_PATTERNS:
                    has_pos_i = bool(re.search(pos_pattern, content_i))
                    has_neg_j = bool(re.search(neg_pattern, content_j))
                    has_neg_i = bool(re.search(neg_pattern, content_i))
                    has_pos_j = bool(re.search(pos_pattern, content_j))
                    
                    # Very simplified - in production would use semantic similarity
                    if (has_pos_i and has_neg_j) or (has_neg_i and has_pos_j):
                        # Only flag if similar topics (share some words)
                        words_i = set(content_i.split())
                        words_j = set(content_j.split())
                        if len(words_i & words_j) > 5:  # Arbitrary threshold
                            issues.append(Issue(
                                issue_type=IssueType.INCONSISTENT_RESPONSE,
                                severity=IssueSeverity.LOW,
                                description=f"Potential inconsistency between turns {turn_i.turn_id} and {turn_j.turn_id}",
                                turn_id=turn_j.turn_id,
                                details={
                                    "turn_a": turn_i.turn_id,
                                    "turn_b": turn_j.turn_id,
                                },
                            ))
                            inconsistencies += 1
                            break
        
        # Compute score
        total_pairs = len(assistant_turns) * (len(assistant_turns) - 1) / 2
        if total_pairs == 0:
            score = 1.0
        else:
            score = 1.0 - (inconsistencies / total_pairs)
        
        return max(0.0, score), issues
    
    def _check_reference_handling(
        self, 
        conversation: Conversation
    ) -> tuple[float, list[Issue]]:
        """Check if references (pronouns, 'that', etc.) are handled correctly."""
        issues = []
        reference_count = 0
        unresolved_count = 0
        
        assistant_turns = [t for t in conversation.turns if t.role == Role.ASSISTANT]
        
        for turn in assistant_turns:
            content = turn.content.lower()
            
            for pattern in REFERENCE_PATTERNS:
                matches = re.findall(pattern, content, re.IGNORECASE)
                reference_count += len(matches)
            
            # Check for phrases indicating failed reference resolution
            failed_resolution_phrases = [
                "not sure what you mean by",
                "unclear what",
                "which one do you mean",
                "can you clarify",
                "what do you mean by",
            ]
            
            for phrase in failed_resolution_phrases:
                if phrase in content:
                    unresolved_count += 1
                    issues.append(Issue(
                        issue_type=IssueType.REFERENCE_ERROR,
                        severity=IssueSeverity.LOW,
                        description=f"Reference resolution issue at turn {turn.turn_id}",
                        turn_id=turn.turn_id,
                        details={"phrase": phrase},
                    ))
        
        # Compute score (penalize unresolved references)
        if reference_count == 0:
            score = 1.0
        else:
            score = 1.0 - (unresolved_count / reference_count)
        
        return max(0.0, min(1.0, score)), issues
    
    def _evaluate(self, conversation: Conversation) -> EvaluatorResult:
        """Evaluate coherence of the conversation."""
        # Check if conversation is long enough for coherence evaluation
        if len(conversation.turns) < self.min_turns_for_eval:
            return EvaluatorResult(
                evaluator_name=self.evaluator_name,
                scores={
                    "context_retention": 1.0,
                    "consistency": 1.0,
                    "reference_accuracy": 1.0,
                },
                issues=(),
                confidence=0.5,  # Lower confidence for short conversations
                metadata={
                    "note": f"Conversation too short for full coherence evaluation ({len(conversation.turns)} < {self.min_turns_for_eval} turns)",
                },
            )
        
        # Run coherence checks
        context_score, context_issues = self._check_context_retention(conversation)
        consistency_score, consistency_issues = self._check_consistency(conversation)
        reference_score, reference_issues = self._check_reference_handling(conversation)
        
        # Aggregate issues
        all_issues = context_issues + consistency_issues + reference_issues
        
        return EvaluatorResult(
            evaluator_name=self.evaluator_name,
            scores={
                "context_retention": context_score,
                "consistency": consistency_score,
                "reference_accuracy": reference_score,
            },
            issues=tuple(all_issues),
            confidence=0.75,  # Moderate confidence for heuristic coherence checks
            metadata={
                "total_turns": len(conversation.turns),
                "context_issues": len(context_issues),
                "consistency_issues": len(consistency_issues),
                "reference_issues": len(reference_issues),
            },
        )

