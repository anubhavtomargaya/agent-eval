# Failure Pattern Strategy

Failure pattern detection is the core of this project. Instead of treating each
evaluation issue as an isolated bug, we aggregate recurring issues into patterns
that explain *what* is failing, *where* it shows up, and *why* it matters. That
single idea connects ingestion, evaluation, feedback, analysis, and regression.

## What We Mean by “Pattern”

A pattern is a cluster of similar failures that repeat across conversations.
Examples include “date format mismatch,” “context loss after five turns,” or
“tool parameters not grounded in user input.” Patterns are more actionable than
raw issues because they can be prioritized, fixed, and verified.

## How the Current Implementation Works

The implemented flow is straightforward and intentionally modular:

1. Evaluators emit granular issues (tool errors, coherence gaps, hallucinations).
2. Analysis flattens issues with surrounding conversation context.
3. Clustering groups similar issues into a small set of patterns.
4. LLM enrichment produces a readable summary and a suggested fix per pattern.
5. Proposals are stored and can be applied and verified via regression.

The logic is orchestrated by `src/analysis/service.py`, with clustering in
`src/analysis/clustering.py`, embeddings in `src/analysis/utils.py`, and proposal
generation in `src/analysis/suggestions.py`.

## Why This Scales

The pipeline scales by changing *transport*, not *logic*. In production, the same
stages run as separate workers and batch jobs, but the interfaces stay the same.
Ingestion can be queue-driven, evaluation can be parallelized, and clustering can
run offline on large datasets. Because the services are stateless, scaling does
not require a redesign.

## Using Patterns to Improve Evaluators

Patterns are not only for prompt or tool updates. They also reveal evaluator
blind spots. When a pattern appears in human feedback but is not detected by
current evaluators, it becomes a candidate for a new rule, a new evaluator, or a
threshold update. This keeps evaluator evolution grounded in real failure data,
not ad hoc intuition.

## Metadata-Driven Analysis

Metadata gives us the ability to slice and diagnose behavior by context: agent
version, tool version, scenario tags, user segments, or latency markers. We use
these tags to run focused analyses (e.g., “only v1.3 failures”) and to route
conversations to human review when risk is higher.

## Sampling Strategy

Sampling is how we choose which conversations get deeper evaluation or human
review. Today we use evaluation-based sampling (low scores, high issues),
confidence-based sampling (low evaluator confidence), random sampling, recency
sampling, and metadata filters. Planned extensions include risk-weighted sampling,
active-learning sampling (maximize disagreement), and drift-based sampling.

## Demo Loop

The demo executes the full loop: ingest → evaluate → cluster → propose → apply →
verify. This is the same logic that production would run, just without distributed
infrastructure.
