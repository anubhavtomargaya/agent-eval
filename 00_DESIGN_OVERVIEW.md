# Design Overview

This project is a prototype pipeline for evaluating and improving an AI concierge agent.
The design favors clarity and traceability over production-grade scale so the demo is
self-contained and easy to reason about.

What the system does
- Ingests conversations (batch or file-based) into a simple repository.
- Runs evaluators (rules + LLM judge) and aggregates scores/issues.
- Applies feedback signals (explicit/implicit) and surfaces disagreements.
- Detects failure patterns and proposes updates to prompts/tools.
- Verifies updates via a regression gate and stores versioned artifacts.

Primary interfaces
- Main API (`src/api/main.py`) exposes ingestion, feedback, evaluation, and demo endpoints.
- The pipeline notebook/one-liner demonstrates the end-to-end flow without UI dependencies.

Where to look
- Pipeline runner: `src/pipeline/processor.py`
- Ingestion: `src/ingestion/service.py`
- Evaluation: `src/evaluation/service.py`, `src/evaluation/evaluators/*`
- Feedback + agreement: `src/feedback/service.py`, `src/feedback/metrics.py`
- Analysis + proposals: `src/analysis/service.py`, `src/analysis/suggestions.py`

# Architecture Choices

This document captures the main design decisions and why they were made for the
prototype/demo scope.

1) Service + repository pattern
- Services encapsulate logic (ingestion, evaluation, feedback, analysis).
- The repository isolates persistence so we can swap JSON storage with a DB later.
- It keeps the API + pipeline runner thin and easy to test.

2) Strategy pattern for evaluators
- Evaluators are registered dynamically via the registry.
- Each evaluator is independent and can be added/removed without touching core logic.
- This mirrors how production evaluation stacks evolve over time.

3) Explicit feedback as a separate step
- Conversations are ingested first; feedback is applied later.
- This matches real workflows where human feedback arrives asynchronously.
- It also enables multiple annotators, disagreement tracking, and re-labeling.

4) Versioned artifacts for self-updating
- Prompt/tool updates are treated as versioned artifacts.
- Applying a proposal writes an active artifact for the agent/evaluators to use.
- Regression gates compare the active prompt against a fixed baseline prompt set.

5) Simple storage and file-based inputs
- JSON storage makes the demo runnable without external services.
- The unprocessed/processed folders act as stand-ins for queues or object storage.

Design goal
- Keep the pipeline understandable end-to-end so the demo can show data flowing
  through ingestion, evaluation, feedback, analysis, and verification.

# Future Enhancements

This section lists realistic extensions beyond the prototype.

Pipeline and infra
- Replace JSON repository with a database and append-only event log.
- Run ingestion/evaluation/analysis as independent queue workers.
- Add monitoring dashboards for eval metrics and regression alerts.

Evaluation
- Add more evaluators (context retention, refusal policy, safety).
- Track evaluator drift across prompt/model versions.

Self-updating
- Add proposal approval workflow and automatic rollback.
- Add automatic regression suites per tool or intent.

Product demo
- Extend the UI to show the pipeline stages and approvals.