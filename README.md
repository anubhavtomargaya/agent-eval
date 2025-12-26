# AI Agent Evaluation Pipeline - Architecture Notes

## 1. Core Philosophy

### Why This Architecture?

**Problem**: Evaluating AI agent conversations at scale requires multiple evaluation strategies (rule-based, LLM-based, semantic), each with different latency profiles and failure modes. We need a system that:
- Handles diverse evaluator types uniformly
- Allows independent development and testing of evaluators
- Scales from demo (single process) to production (distributed workers) without code changes
- Provides clear contracts between components

**Solution**: Service-oriented design with Strategy pattern for evaluators and Repository pattern for storage abstraction.

---

## 2. Design Decisions

### 2.1 Strategy Pattern for Evaluators

```
┌─────────────────────────────────────────────────────────────────┐
│                    EvaluationService                            │
│                         │                                       │
│    ┌────────────────────┼────────────────────┐                 │
│    │                    │                    │                 │
│    ▼                    ▼                    ▼                 │
│ ┌──────────┐      ┌──────────┐        ┌──────────┐            │
│ │Evaluator │      │Evaluator │        │Evaluator │            │
│ │Interface │      │Interface │        │Interface │            │
│ └────┬─────┘      └────┬─────┘        └────┬─────┘            │
│      │                 │                   │                   │
│      ▼                 ▼                   ▼                   │
│ ┌──────────┐      ┌──────────┐        ┌──────────┐            │
│ │Heuristic │      │Tool Call │        │LLM Judge │            │
│ │   ~1ms   │      │  ~5ms    │        │ ~500ms   │            │
│ └──────────┘      └──────────┘        └──────────┘            │
└─────────────────────────────────────────────────────────────────┘
```


### 2.2 Repository Pattern for Storage

```python
# Abstract interface
class ConversationRepository(ABC):
    def save_conversation(self, conv) -> str: ...
    def get_conversation(self, id) -> Conversation: ...

# Demo implementation
class InMemoryRepository(ConversationRepository):
    # Dict + JSON files

# Production implementation (future)
class PostgresRepository(ConversationRepository):
    # SQLAlchemy + connection pooling
```

**Why?**
- **Easier testing**: In-memory implementations are used for unit tests; the actual database is used for integration.
- **Simple to switch storage**: You can change storage backends without touching other parts of the code.
- **Flexibility**: Services are built to work with a storage interface, so details of where data lives can change as needed.


### 2.3 Stateless Services

Both `IngestionService` and `EvaluationService` are stateless:
- All state lives in the repository
- Services can be instantiated per-request or as singletons
- Horizontal scaling is trivial (run N instances)

```python
# Services don't hold state - they coordinate
class EvaluationService:
    def __init__(self, repository, evaluators):
        self.repository = repository  # State lives here
        self.evaluators = evaluators  # Strategies are stateless
```

### 2.4 Ingestion Responsibilities (Current Code)

`IngestionService` is the boundary between raw JSON and internal models:
- **Validate + normalize**: roles, turn IDs, timestamps, tool calls
- **ID hygiene**: generate `conversation_id` when missing
- **Batch + file ingestion**: accepts lists or JSON files with a `conversations` wrapper
- **Pending directory workflow**: processes `data/pending/*.json`, moves to `processed/` or `error/`
- **Persistence**: stores the normalized `Conversation` via the repository

Feedback ingestion is intentionally separate from ingestion (see below) to keep ingestion fast and idempotent.

### 2.5 Explicit Feedback 

Explicit feedback is a **post-ingest** step:
- **Separate API path**: `/conversations/{id}/feedback` for adding and listing feedback
- **Append-only**: feedback items are attached to existing conversations
- **Storage**: persisted alongside conversations in the repository
- **Sampling**: `/feedback/samples` surfaces low-score or high-issue conversations for review

Implicit feedback is planned as an offline enrichment job, not part of ingestion.

### 2.6 Self-Updating

The demo uses versioned artifacts and a lightweight agent:
- **Active prompt**: `artifacts/prompts/active_prompt.txt`
- **Active tool schema**: `artifacts/tools/active_tool_schema.json`
- **Demo agent**: `/demo/ask` generates real LLM conversations and ingests them
- **Apply proposal**: `/analysis/proposals/{id}/apply` writes active artifacts
- **Real regression**: `/analysis/proposals/{id}/verify-real` runs a fixed prompt set

---

## 3. Data Flow

### Current (Demo Mode)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Single Process                                 │
│                                                                          │
│   ┌──────────┐     ┌───────────────┐     ┌──────────────────────┐       │
│   │  FastAPI │────▶│  Ingestion    │────▶│     Repository       │       │
│   │ Endpoint │     │   Service     │     │  (In-Memory + JSON)  │       │
│   └──────────┘     └───────────────┘     └──────────────────────┘       │
│        │                                           │                     │
│        │           ┌───────────────┐               │                     │
│        └──────────▶│  Evaluation   │◀──────────────┘                     │
│                    │   Service     │                                     │
│                    └───────┬───────┘                                     │
│                            │                                             │
│              ┌─────────────┼─────────────┼─────────────┼─────────────┐   │
│              ▼             ▼             ▼             ▼             ▼   │
│         Heuristic     Tool Call   Tool Causality   Coherence    LLM Judge│
│           ~1ms          ~5ms         ~5-15ms         ~10ms      ~500ms   │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

**Execution Model**:
1. API receives request
2. Ingestion validates and stores
3. Evaluation loads conversation, runs evaluators **sequentially**
4. Results stored and returned

**Evaluation Routing (Production Intent)**:
- Run cheap evaluators on all conversations (heuristic, tool_call, coherence).
- Route LLM-as-judge to a subset based on confidence, sampling, or metadata.
- This keeps cost/latency manageable while preserving quality signals.

**Feedback Flow (Explicit)**:
1. API receives feedback for an existing conversation
2. Repository appends the feedback item to the conversation record
3. Feedback can be sampled later for review or calibration

**Self-Updating Flow (Demo)**:
1. `/demo/ask` creates a conversation using the active prompt artifact
2. Evaluators detect failures and analysis generates proposals
3. `/analysis/proposals/{id}/apply` updates active artifacts
4. `/analysis/proposals/{id}/verify-real` re-runs a fixed prompt set (`data/regression_prompts.json`)

### Production Ingestion (Nuances & Options)

The prototype runs ingestion inline inside the API process for simplicity. In production, the **ingestion core stays the same**, but the *transport + scaling* change. We intentionally keep ingestion logic stateless and behind a clean interface so different sources can feed it.

**Possible ingestion sources**:
- **Queue-first**: API enqueues ingestion jobs; worker fleet pulls and calls `IngestionService`
- **Object storage**: S3 (or GCS) drops trigger a worker to download JSON and ingest
- **Filesystem drops**: Batch files appear in a watched directory; a worker ingests and archives

**Why this works without rewriting ingestion**:
- `IngestionService` only cares about **validated conversation payloads**, not transport
- Repository abstraction cleanly absorbs different persistence backends
- Stateless services allow horizontal scaling (more workers = more throughput)

### Production (Future)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                                                                          │
│   ┌──────────┐     ┌─────────┐     ┌───────────────────────────────┐    │
│   │  FastAPI │────▶│  Queue  │────▶│     Ingestion Workers (N)     │    │
│   │   (API)  │     │ (Redis) │     └───────────────────────────────┘    │
│   └──────────┘     └─────────┘                    │                      │
│                         ▲                         ▼                      │
│                         │                  ┌─────────────┐               │
│                         │                  │  PostgreSQL │               │
│                         │                  └─────────────┘               │
│                         │                         │                      │
│                    ┌─────────┐                    ▼                      │
│                    │  Queue  │◀────────────────────                      │
│                    │ (Redis) │                                           │
│                    └─────────┘                                           │
│                         │                                                │
│                         ▼                                                │
│              ┌───────────────────────────────────┐                      │
│              │    Evaluation Workers (M)         │                      │
│              │    - Run evaluators in parallel   │                      │
│              │    - M > N (slower work)          │                      │
│              └───────────────────────────────────┘                      │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

**Key Insight**: The **service interfaces don't change**. We only:
1. Swap `InMemoryRepository` → `PostgresRepository`
2. Add queue consumption in workers
3. Run evaluators with `ThreadPoolExecutor`

---

## 4. Evaluators

### Latency Profiles

| Evaluator | Latency | Dependencies | Failure Mode |
|-----------|---------|--------------|--------------|
| Heuristic | ~1ms | None | Never fails (deterministic) |
| Tool Call | ~5ms | Schema registry | Graceful degradation |
| Tool Causality | ~5-15ms | None | Heuristic-based, can be noisy |
| Coherence | ~10ms | None | Heuristic-based, may miss edge cases |
| LLM Judge | ~500ms-2s | OpenAI API | Rate limits, timeouts |

### Why This Mix?

1. **Heuristic**: Fast, cheap, catches obvious issues (empty responses, format errors)
2. **Tool Call**: Validates tool choice and parameter schemas
3. **Tool Causality**: Flags non-grounded parameter values (hallucination provenance)
4. **Coherence**: Catches context loss - key for multi-turn quality
5. **LLM Judge**: Semantic quality that rules can't capture

### Extending Evaluators

```python
from src.evaluation.evaluators import Evaluator, register_evaluator

@register_evaluator
class MyCustomEvaluator(Evaluator):
    @property
    def evaluator_name(self) -> str:
        return "my_custom"
    
    def _evaluate(self, conversation: Conversation) -> EvaluatorResult:
        # Your logic here
        return EvaluatorResult(
            evaluator_name=self.evaluator_name,
            scores={"my_metric": 0.95},
            issues=(),
            confidence=0.9,
        )
```

The `@register_evaluator` decorator automatically adds it to the registry.

---

## 6. Testing Philosophy

### Unit Tests
- Test evaluators in isolation with mock conversations
- Test repository with in-memory implementation
- No external dependencies

### Integration Tests
- Test full flow: ingest → evaluate → results
- Use real repository (SQLite for CI)
- Mock only OpenAI calls

### Contract Tests
- Evaluator interface compliance
- API schema validation
- Repository interface compliance

---

## 7. Configuration & Operations

### Environment Variables
```bash

OPENAI_API_KEY=...           
# Enabled evaluators are currently set in src/config.py (override in code)
DATABASE_URL=sqlite:///...   # Reserved for future SQL repository
```

### Observability (Future)
- Prometheus metrics per evaluator (latency, success rate)
- Structured logging with correlation IDs
- Distributed tracing for production

