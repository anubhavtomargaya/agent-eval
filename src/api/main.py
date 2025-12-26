from __future__ import annotations
"""FastAPI application for the AI Agent Evaluation Pipeline.

Endpoints:
- POST /ingest - Ingest conversations from JSON body
- POST /ingest/file - Ingest conversations from uploaded file
- POST /evaluate/{conversation_id} - Evaluate a single conversation
- POST /evaluate/batch - Evaluate multiple conversations
- POST /evaluate/pending - Evaluate all pending conversations
- GET /results/{conversation_id} - Get evaluation results
- GET /results - List all evaluations
- GET /conversations - List all conversations
- GET /stats - Get summary statistics
- GET /health - Health check
"""

from datetime import datetime
from typing import Any
from pathlib import Path
import json
import tempfile

from fastapi import FastAPI, HTTPException, UploadFile, File, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.config import get_settings
from src.db.repository import get_repository
from src.ingestion.service import IngestionService, ValidationError
from src.evaluation.service import EvaluationService, EvaluationError
from src.evaluation.evaluators import get_global_registry, EvaluatorDiscovery
from src.feedback.sampling import sample_conversations, list_strategies, ConversationSample
from src.agent.demo_agent import DemoAgent, build_conversation_payload, append_turns_payload
from src.models import FeedbackSignal


# =============================================================================
# Pydantic Models for API
# =============================================================================

class ToolCallInput(BaseModel):
    """Tool call input schema."""
    tool_name: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    result: Any | None = None
    execution_time_ms: float | None = None


class TurnInput(BaseModel):
    """Turn input schema."""
    turn_id: int | None = None
    role: str
    content: str
    timestamp: str | None = None
    latency_ms: float | None = None
    tool_calls: list[ToolCallInput] = Field(default_factory=list)


class ConversationInput(BaseModel):
    """Conversation input schema."""
    conversation_id: str | None = None
    turns: list[TurnInput]
    metadata: dict[str, Any] = Field(default_factory=dict)


class BatchIngestInput(BaseModel):
    """Batch ingestion input schema."""
    conversations: list[ConversationInput]


class BatchEvaluateInput(BaseModel):
    """Batch evaluation input schema."""
    conversation_ids: list[str]


class IngestionResponse(BaseModel):
    """Response for ingestion operations."""
    total: int
    success: int
    failed: int
    errors: list[str]
    conversation_ids: list[str]


class IssueResponse(BaseModel):
    """Issue in evaluation response."""
    issue_type: str
    severity: str
    description: str
    turn_id: int | None = None
    suggested_fix: str | None = None


class EvaluatorResultResponse(BaseModel):
    """Single evaluator result in response."""
    evaluator_name: str
    scores: dict[str, float]
    issues: list[IssueResponse]
    confidence: float
    latency_ms: float | None = None


class EvaluationResponse(BaseModel):
    """Response for evaluation operations."""
    conversation_id: str
    run_id: str
    timestamp: str
    aggregate_score: float
    status: str
    evaluations: dict[str, EvaluatorResultResponse]
    issues: list[IssueResponse]
    issues_count: int


class ConversationResponse(BaseModel):
    """Response for conversation queries."""
    conversation_id: str
    turn_count: int
    metadata: dict[str, Any]
    created_at: str
    has_evaluation: bool


class FeedbackInput(BaseModel):
    """Input schema for explicit feedback."""
    signal: str
    value: Any
    source: str
    timestamp: str | None = None
    turn_id: int | None = None
    annotator_id: str | None = None
    confidence: float | None = None
    notes: str | None = None


class FeedbackItemResponse(BaseModel):
    """Single feedback item response."""
    conversation_id: str
    feedback_type: str
    signal: str
    value: Any
    source: str
    timestamp: str
    turn_id: int | None = None
    annotator_id: str | None = None
    confidence: float | None = None
    notes: str | None = None


class FeedbackSampleResponse(BaseModel):
    """Response for feedback sampling."""
    conversation_id: str
    aggregate_score: float | None = None
    issues_count: int | None = None
    turn_count: int
    created_at: str
    metadata: dict[str, Any]
    has_evaluation: bool


class FeedbackAgreementResponse(BaseModel):
    """Response for feedback agreement metrics."""
    signal: str
    items: int
    annotators: int
    pairwise_kappa: float | None = None
    krippendorff_alpha: float | None = None


class DemoAskInput(BaseModel):
    """Input schema for demo agent requests."""
    message: str
    force_error: bool = False


class DemoAskResponse(BaseModel):
    """Response for demo agent requests."""
    conversation_id: str
    assistant_message: str
    tool_name: str | None = None
    tool_params: dict[str, Any] | None = None


class DemoTurnInput(BaseModel):
    """Input schema for adding a turn to an existing conversation."""
    conversation_id: str
    message: str
    force_error: bool = False


class DemoTurnResponse(BaseModel):
    """Response for demo turn requests."""
    conversation_id: str
    turn_count: int
    last_turn_id: int


class StatsResponse(BaseModel):
    """Response for statistics endpoint."""
    total_conversations: int
    total_evaluations: int
    pending_evaluations: int
    average_score: float
    total_issues: int
    issues_by_type: dict[str, int]
    scores_by_evaluator: dict[str, float]


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    timestamp: str
    version: str


class ScoreDeltaResponse(BaseModel):
    """Score change in regression testing."""
    metric_name: str
    old_val: float
    new_val: float
    is_improvement: bool


class RegressionReportResponse(BaseModel):
    """Regression test results."""
    run_id: str
    timestamp: str
    test_case_count: int
    overall_improvement: bool
    score_deltas: list[ScoreDeltaResponse]


class ImprovementProposalResponse(BaseModel):
    """Response for improvement proposals."""
    proposal_id: str
    type: str
    failure_pattern: str
    rationale: str
    original_content: str
    proposed_content: str
    status: str
    created_at: str
    regression_report: RegressionReportResponse | None = None
    evidence_count: int
    metadata: dict[str, Any] = {}


# =============================================================================
# Application Factory
# =============================================================================

def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    
    settings = get_settings()
    
    app = FastAPI(
        title="AI Agent Evaluation Pipeline",
        description="Modular evaluation framework for AI agent conversations",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )
    
    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Initialize Registry and Discovery (Composition Root)
    registry = get_global_registry()
    EvaluatorDiscovery.discover_and_register(registry)
    
    repository = get_repository(data_dir="./data")
    ingestion_service = IngestionService(repository)
    evaluation_service = EvaluationService(
        repository,
        registry,
        enabled_evaluators=settings.enabled_evaluators,
    )
    
    # Lazy import to avoid circular dependencies if any
    from src.analysis.service import AnalysisService
    analysis_service = AnalysisService(repository, evaluation_service)
    
    # =========================================================================
    # Health Check
    # =========================================================================
    
    @app.get("/health", response_model=HealthResponse, tags=["Health"])
    async def health_check():
        """Health check endpoint."""
        return HealthResponse(
            status="healthy",
            timestamp=datetime.utcnow().isoformat(),
            version="0.1.0",
        )
    
    # =========================================================================
    # Ingestion Endpoints
    # =========================================================================
    
    @app.post("/ingest", response_model=IngestionResponse, tags=["Ingestion"])
    async def ingest_conversations(input_data: BatchIngestInput):
        """Ingest conversations from JSON body.
        
        Accepts a list of conversations and validates/stores them.
        """
        conversations = [c.model_dump() for c in input_data.conversations]
        result = ingestion_service.ingest_batch(conversations)
        
        return IngestionResponse(
            total=result.total,
            success=result.success,
            failed=result.failed,
            errors=list(result.errors),
            conversation_ids=list(result.conversation_ids),
        )
    
    @app.post("/ingest/single", response_model=IngestionResponse, tags=["Ingestion"])
    async def ingest_single_conversation(conversation: ConversationInput):
        """Ingest a single conversation."""
        try:
            conv = ingestion_service.ingest_single(conversation.model_dump())
            return IngestionResponse(
                total=1,
                success=1,
                failed=0,
                errors=[],
                conversation_ids=[conv.conversation_id],
            )
        except ValidationError as e:
            return IngestionResponse(
                total=1,
                success=0,
                failed=1,
                errors=[str(e)],
                conversation_ids=[],
            )
    
    @app.post("/ingest/file", response_model=IngestionResponse, tags=["Ingestion"])
    async def ingest_from_file(file: UploadFile = File(...)):
        """Ingest conversations from an uploaded JSON file."""
        # Save uploaded file temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name
        
        try:
            result = ingestion_service.ingest_from_file(tmp_path)
            return IngestionResponse(
                total=result.total,
                success=result.success,
                failed=result.failed,
                errors=list(result.errors),
                conversation_ids=list(result.conversation_ids),
            )
        finally:
            # Clean up temp file
            Path(tmp_path).unlink(missing_ok=True)
    
    @app.post("/ingest/pending", tags=["Ingestion"])
    async def ingest_pending(pending_dir: str = Query(default="data/pending")):
        """Process all JSON files in the pending directory."""
        return ingestion_service.ingest_pending(pending_dir)
    
    # =========================================================================
    # Evaluation Endpoints
    # =========================================================================
    
    @app.post("/evaluate/batch", response_model=list[EvaluationResponse], tags=["Evaluation"])
    async def evaluate_batch(input_data: BatchEvaluateInput):
        """Evaluate multiple conversations by ID."""
        results = evaluation_service.evaluate_batch(input_data.conversation_ids)
        return [_evaluation_to_response(r) for r in results]
    
    @app.post("/evaluate/pending", response_model=list[EvaluationResponse], tags=["Evaluation"])
    async def evaluate_pending(force: bool = Query(default=False)):
        """Evaluate all conversations that haven't been evaluated yet."""
        results = evaluation_service.evaluate_pending(force=force)
        return [_evaluation_to_response(r) for r in results]

    @app.post("/evaluate/{conversation_id}", response_model=EvaluationResponse, tags=["Evaluation"])
    async def evaluate_conversation(conversation_id: str):
        """Evaluate a single conversation by ID."""
        try:
            result = evaluation_service.evaluate(conversation_id)
            return _evaluation_to_response(result)
        except EvaluationError as e:
            raise HTTPException(status_code=404, detail=str(e))
    
    # =========================================================================
    # Results Endpoints
    # =========================================================================
    
    @app.get("/results/{conversation_id}", response_model=EvaluationResponse, tags=["Results"])
    async def get_evaluation_result(conversation_id: str):
        """Get evaluation results for a conversation."""
        result = evaluation_service.get_evaluation(conversation_id)
        if result is None:
            raise HTTPException(status_code=404, detail=f"No evaluation found for conversation: {conversation_id}")
        return _evaluation_to_response(result)
    
    @app.get("/results", response_model=list[EvaluationResponse], tags=["Results"])
    async def list_evaluations(
        limit: int = Query(default=100, le=1000),
        offset: int = Query(default=0, ge=0),
    ):
        """List all evaluations with pagination."""
        results = evaluation_service.list_evaluations(limit=limit, offset=offset)
        return [_evaluation_to_response(r) for r in results]
    
    # =========================================================================
    # Conversation Endpoints
    # =========================================================================
    
    @app.get("/conversations", response_model=list[ConversationResponse], tags=["Conversations"])
    async def list_conversations(
        limit: int = Query(default=100, le=1000),
        offset: int = Query(default=0, ge=0),
    ):
        """List all conversations with pagination."""
        conversations = repository.list_conversations(limit=limit, offset=offset)
        responses = []
        for conv in conversations:
            eval_result = repository.get_evaluation(conv.conversation_id)
            responses.append(ConversationResponse(
                conversation_id=conv.conversation_id,
                turn_count=len(conv.turns),
                metadata=conv.metadata,
                created_at=conv.created_at.isoformat(),
                has_evaluation=eval_result is not None,
            ))
        return responses
    
    @app.get("/conversations/{conversation_id}", tags=["Conversations"])
    async def get_conversation(conversation_id: str):
        """Get a conversation by ID with full details."""
        conv = repository.get_conversation(conversation_id)
        if conv is None:
            raise HTTPException(status_code=404, detail=f"Conversation not found: {conversation_id}")
        
        return {
            "conversation_id": conv.conversation_id,
            "metadata": conv.metadata,
            "created_at": conv.created_at.isoformat(),
            "feedback": [
                {
                    "signal": f.signal,
                    "value": f.value,
                    "source": f.source,
                    "notes": f.notes,
                    "timestamp": f.timestamp.isoformat() if f.timestamp else None,
                    "annotator_id": f.annotator_id,
                }
                for f in conv.feedback
            ],
            "turns": [
                {
                    "turn_id": t.turn_id,
                    "role": t.role.value,
                    "content": t.content,
                    "timestamp": t.timestamp.isoformat() if t.timestamp else None,
                    "latency_ms": t.latency_ms,
                    "tool_calls": [
                        {
                            "tool_name": tc.tool_name,
                            "parameters": tc.parameters,
                            "result": tc.result,
                        }
                        for tc in t.tool_calls
                    ],
                }
                for t in conv.turns
            ],
        }

    # =========================================================================
    # Feedback Endpoints
    # =========================================================================

    @app.post("/conversations/{conversation_id}/feedback", response_model=FeedbackItemResponse, tags=["Feedback"])
    async def add_feedback(conversation_id: str, feedback: FeedbackInput):
        """Add explicit feedback for a conversation."""
        conv = repository.get_conversation(conversation_id)
        if conv is None:
            raise HTTPException(status_code=404, detail=f"Conversation not found: {conversation_id}")

        feedback_item = FeedbackSignal(
            feedback_type="explicit",
            signal=feedback.signal,
            value=feedback.value,
            source=feedback.source,
            timestamp=_parse_timestamp(feedback.timestamp),
            turn_id=feedback.turn_id,
            annotator_id=feedback.annotator_id,
            confidence=feedback.confidence,
            notes=feedback.notes,
        )
        repository.add_feedback(conversation_id, feedback_item)
        return _feedback_to_response(conversation_id, feedback_item)

    @app.get("/conversations/{conversation_id}/feedback", response_model=list[FeedbackItemResponse], tags=["Feedback"])
    async def list_feedback(conversation_id: str):
        """List all feedback items for a conversation."""
        conv = repository.get_conversation(conversation_id)
        if conv is None:
            raise HTTPException(status_code=404, detail=f"Conversation not found: {conversation_id}")
        items = repository.list_feedback(conversation_id)
        return [_feedback_to_response(conversation_id, item) for item in items]

    @app.get("/feedback/samples", response_model=list[FeedbackSampleResponse], tags=["Feedback"])
    async def sample_conversations_for_feedback(
        limit: int = Query(default=50, le=200),
        strategy: str = Query(default="confidence"),
        min_issues: int = Query(default=1, ge=0),
        max_score: float = Query(default=0.6, ge=0.0, le=1.0),
        threshold: float = Query(default=0.8, ge=0.0, le=1.0),
        metadata_key: str | None = Query(default=None),
        metadata_value: str | None = Query(default=None),
        seed: int | None = Query(default=None),
    ):
        """Sample conversations for human feedback review."""
        evaluations = evaluation_service.list_evaluations(limit=1000, offset=0)
        conversations = repository.list_conversations(limit=10000, offset=0)
        try:
            samples = sample_conversations(
                strategy=strategy,
                conversations=conversations,
                evaluations=evaluations,
                limit=limit,
                min_issues=min_issues,
                max_score=max_score,
                threshold=threshold,
                metadata_key=metadata_key,
                metadata_value=metadata_value,
                seed=seed,
            )
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"{str(e)}. Available strategies: {', '.join(list_strategies())}",
            )

        return [_sample_to_response(sample) for sample in samples]
    
    # =========================================================================
    # Statistics Endpoints
    # =========================================================================
    
    @app.get("/stats", response_model=StatsResponse, tags=["Statistics"])
    async def get_stats():
        """Get summary statistics for all evaluations."""
        stats = evaluation_service.get_summary_stats()
        conversations = repository.list_conversations(limit=10000)
        pending = repository.get_pending_conversations()
        
        return StatsResponse(
            total_conversations=len(conversations),
            total_evaluations=stats["total_evaluations"],
            pending_evaluations=len(pending),
            average_score=stats["average_score"],
            total_issues=stats["total_issues"],
            issues_by_type=stats["issues_by_type"],
            scores_by_evaluator=stats["scores_by_evaluator"],
        )
    
    # =========================================================================
    # Analysis Endpoints
    # =========================================================================
    
    @app.post("/analysis/run", response_model=list[ImprovementProposalResponse], tags=["Analysis"])
    async def run_analysis(limit: int = Query(default=100, le=500)):
        """Trigger a full analysis cycle (Cluster failures -> Generate Suggestions)."""
        proposals = analysis_service.run_analysis_cycle(limit=limit)
        return [_proposal_to_response(p) for p in proposals]
    
    @app.get("/analysis/proposals", response_model=list[ImprovementProposalResponse], tags=["Analysis"])
    async def list_proposals(
        limit: int = Query(default=50, le=100),
        offset: int = Query(default=0, ge=0)
    ):
        """List all generated improvement proposals."""
        proposals = repository.list_proposals(limit=limit, offset=offset)
        return [_proposal_to_response(p) for p in proposals]
    
    @app.get("/analysis/proposals/{proposal_id}", response_model=ImprovementProposalResponse, tags=["Analysis"])
    async def get_proposal(proposal_id: str):
        """Get details of a specific proposal."""
        proposal = repository.get_proposal(proposal_id)
        if not proposal:
            raise HTTPException(status_code=404, detail="Proposal not found")
        return _proposal_to_response(proposal)
    
    @app.post("/analysis/proposals/{proposal_id}/verify", response_model=RegressionReportResponse, tags=["Analysis"])
    async def verify_proposal(proposal_id: str):
        """Run regression testing for a proposal."""
        try:
            report = analysis_service.verify_proposal(proposal_id)
            return _report_to_response(report)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/analysis/proposals/{proposal_id}/apply", tags=["Analysis"])
    async def apply_proposal(proposal_id: str):
        """Apply a proposal by writing it to the active artifact files."""
        try:
            artifacts = analysis_service.apply_proposal(proposal_id)
            return {"status": "applied", "artifacts": artifacts}
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/analysis/proposals/{proposal_id}/verify-real", response_model=RegressionReportResponse, tags=["Analysis"])
    async def verify_proposal_real(proposal_id: str):
        """Run a real regression using the demo agent and fixed prompt set."""
        try:
            prompts_path = Path("data/regression_prompts.json")
            if not prompts_path.exists():
                raise HTTPException(status_code=404, detail="regression_prompts.json not found")
            prompts = json.loads(prompts_path.read_text())
            report = analysis_service.run_real_regression(proposal_id, prompts)
            return _report_to_response(report)
        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # =========================================================================
    # Demo Agent Endpoints
    # =========================================================================

    @app.post("/demo/ask", response_model=DemoAskResponse, tags=["Demo"])
    async def demo_ask(input_data: DemoAskInput):
        """Generate and ingest a demo conversation using the current prompt."""
        agent = DemoAgent()
        response = agent.generate(
            input_data.message,
            force_error=input_data.force_error,
        )
        payload = build_conversation_payload(response, agent.prompt_path)
        conversation = ingestion_service.ingest_single(payload)

        return DemoAskResponse(
            conversation_id=conversation.conversation_id,
            assistant_message=response.assistant_message,
            tool_name=response.tool_call["tool_name"] if response.tool_call else None,
            tool_params=response.tool_call["parameters"] if response.tool_call else None,
        )

    @app.post("/demo/turn", response_model=DemoTurnResponse, tags=["Demo"])
    async def demo_turn(input_data: DemoTurnInput):
        """Append a user/assistant turn pair to an existing conversation."""
        conv = repository.get_conversation(input_data.conversation_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

        agent = DemoAgent()
        assistant_message, tool_call = agent.generate_turn(
            input_data.message,
            force_error=input_data.force_error,
        )

        existing_payload = {
            "conversation_id": conv.conversation_id,
            "turns": [
                {
                    "turn_id": t.turn_id,
                    "role": t.role.value,
                    "content": t.content,
                    "timestamp": t.timestamp.isoformat() if t.timestamp else None,
                    "latency_ms": t.latency_ms,
                    "tool_calls": [
                        {
                            "tool_name": tc.tool_name,
                            "parameters": tc.parameters,
                            "result": tc.result,
                            "execution_time_ms": tc.execution_time_ms,
                        }
                        for tc in t.tool_calls
                    ],
                }
                for t in conv.turns
            ],
            "metadata": conv.metadata,
        }

        payload = append_turns_payload(
            existing_payload,
            user_message=input_data.message,
            assistant_message=assistant_message,
            tool_call=tool_call,
            prompt_path=agent.prompt_path,
        )
        updated = ingestion_service.ingest_single(payload)

        return DemoTurnResponse(
            conversation_id=updated.conversation_id,
            turn_count=len(updated.turns),
            last_turn_id=updated.turns[-1].turn_id if updated.turns else 0,
        )

    # =========================================================================
    # Feedback & Meta-Evaluation Endpoints (NEW)
    # =========================================================================

    from src.feedback.service import FeedbackService

    feedback_service = FeedbackService(repository)

    @app.get("/feedback/disagreements", tags=["Feedback"])
    async def get_feedback_disagreements(limit: int = 50):
        """List conversations where human annotators disagree."""
        return feedback_service.get_disagreements(limit=limit)

    @app.get("/feedback/metrics", response_model=FeedbackAgreementResponse, tags=["Feedback"])
    async def get_feedback_metrics(signal: str = Query(...)):
        """Compute agreement metrics for a feedback signal."""
        return feedback_service.get_agreement_metrics(signal)

    @app.post("/feedback/resolve", tags=["Feedback"])
    async def resolve_disagreement(
        conversation_id: str, 
        signal: str, 
        value: Any, 
        resolver_id: str = "admin"
    ):
        """Manually resolve a disagreement."""
        feedback_service.resolve_disagreement(conversation_id, signal, value, resolver_id)
        return {"status": "resolved"}

    # =========================================================================
    # Static Files (Frontend)
    # =========================================================================
    
    from fastapi.staticfiles import StaticFiles
    import os
    
    # Ensure static directory exists
    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app


def _evaluation_to_response(result) -> EvaluationResponse:
    """Convert EvaluationResult to API response model."""
    evaluations = {}
    for name, eval_result in result.evaluations.items():
        evaluations[name] = EvaluatorResultResponse(
            evaluator_name=eval_result.evaluator_name,
            scores=eval_result.scores,
            issues=[
                IssueResponse(
                    issue_type=i.issue_type.value,
                    severity=i.severity.value,
                    description=i.description,
                    turn_id=i.turn_id,
                    suggested_fix=i.suggested_fix,
                )
                for i in eval_result.issues
            ],
            confidence=eval_result.confidence,
            latency_ms=eval_result.latency_ms,
        )
    
    return EvaluationResponse(
        conversation_id=result.conversation_id,
        run_id=result.run_id,
        timestamp=result.timestamp.isoformat(),
        aggregate_score=result.aggregate_score,
        status=result.status,
        evaluations=evaluations,
        issues=[
            IssueResponse(
                issue_type=i.issue_type.value,
                severity=i.severity.value,
                description=i.description,
                turn_id=i.turn_id,
                suggested_fix=i.suggested_fix,
            )
            for i in result.issues
        ],
        issues_count=len(result.issues),
    )


def _parse_timestamp(value: str | None) -> datetime:
    """Parse an ISO timestamp, defaulting to now."""
    if not value:
        return datetime.utcnow()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.utcnow()


def _feedback_to_response(conversation_id: str, feedback: FeedbackSignal) -> FeedbackItemResponse:
    """Convert FeedbackSignal to API response model."""
    return FeedbackItemResponse(
        conversation_id=conversation_id,
        feedback_type=feedback.feedback_type,
        signal=feedback.signal,
        value=feedback.value,
        source=feedback.source,
        timestamp=feedback.timestamp.isoformat() if feedback.timestamp else "",
        turn_id=feedback.turn_id,
        annotator_id=feedback.annotator_id,
        confidence=feedback.confidence,
        notes=feedback.notes,
    )


def _sample_to_response(sample: ConversationSample) -> FeedbackSampleResponse:
    """Convert ConversationSample to API response model."""
    return FeedbackSampleResponse(
        conversation_id=sample.conversation_id,
        aggregate_score=sample.aggregate_score,
        issues_count=sample.issues_count,
        turn_count=sample.turn_count,
        created_at=sample.created_at.isoformat(),
        metadata=sample.metadata,
        has_evaluation=sample.aggregate_score is not None,
    )


def _proposal_to_response(proposal: Any) -> ImprovementProposalResponse:
    """Convert ImprovementProposal to API response."""
    return ImprovementProposalResponse(
        proposal_id=proposal.proposal_id,
        type=proposal.type.value,
        failure_pattern=proposal.failure_pattern,
        rationale=proposal.rationale,
        original_content=proposal.original_content,
        proposed_content=proposal.proposed_content,
        status=proposal.status.value,
        created_at=proposal.created_at.isoformat(),
        regression_report=_report_to_response(proposal.regression_report) if proposal.regression_report else None,
        evidence_count=len(proposal.evidence_ids),
        metadata=proposal.metadata
    )


def _report_to_response(report: Any) -> RegressionReportResponse:
    """Convert RegressionReport to API response."""
    return RegressionReportResponse(
        run_id=report.run_id,
        timestamp=report.timestamp.isoformat(),
        test_case_count=report.test_case_count,
        overall_improvement=report.overall_improvement,
        score_deltas=[
            ScoreDeltaResponse(
                metric_name=d.metric_name,
                old_val=d.old_val,
                new_val=d.new_val,
                is_improvement=d.is_improvement
            )
            for d in report.score_deltas
        ]
    )


# Create default app instance
app = create_app()


if __name__ == "__main__":
    import uvicorn
    settings = get_settings()
    uvicorn.run(app, host=settings.api_host, port=settings.api_port)
