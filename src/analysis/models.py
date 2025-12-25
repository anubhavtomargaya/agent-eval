from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Dict, Any, Optional
import uuid

from src.models import Issue, EvaluationResult, Conversation

class ProposalStatus(str, Enum):
    DRAFT = "draft"
    TESTING = "testing"
    APPROVED = "approved"
    REJECTED = "rejected"
    DEPLOYED = "deployed"

class ImprovementType(str, Enum):
    PROMPT = "prompt"
    TOOL = "tool"

@dataclass
class IssueCluster:
    """Internal representation of grouped issues."""
    cluster_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    label: str = ""
    issues: List[Issue] = field(default_factory=list)
    conversation_ids: List[str] = field(default_factory=list)
    explanation: str = ""
    severity: float = 0.0  # 1-10
    significance_score: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ScoreDelta:
    """Metric comparison between base and shadow runs."""
    metric_name: str
    old_val: float
    new_val: float
    is_improvement: bool
    confidence_interval: Optional[float] = None

@dataclass
class RegressionReport:
    """Complete regression test results."""
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.utcnow)
    test_case_count: int = 0
    score_deltas: List[ScoreDelta] = field(default_factory=list)
    overall_improvement: bool = False
    details: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ImprovementProposal:
    """A 'Prompt PR' suggested by the analysis layer."""
    proposal_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: ImprovementType = ImprovementType.PROMPT
    cluster_id: Optional[str] = None
    failure_pattern: str = ""
    rationale: str = ""
    original_content: str = ""  # The original prompt or tool schema
    proposed_content: str = ""  # The fixed version
    evidence_ids: List[str] = field(default_factory=list)  # Linked conversation IDs
    status: ProposalStatus = ProposalStatus.DRAFT
    regression_report: Optional[RegressionReport] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)
