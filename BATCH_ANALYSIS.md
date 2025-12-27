# Batch Analysis Pipeline Documentation

## Overview

This document describes the complete batch analysis pipeline for evaluating AI agent conversations, including staged evaluation, pattern detection, and automated improvement proposal generation.

## Test Setup

### Agent Configuration
- **Agent**: Travel assistant (`travel_assistant_v1`)
- **Prompt**: Basic travel assistance prompt from `artifacts/prompts/prompt_v1.txt`
- **Tools**: Flight search, hotel search with standard schemas
- **Version**: Single agent version for controlled pattern analysis

### Conversation Generation
Generated 15 conversations with controlled issue patterns:
- **8 conversations with issues** (53% failure rate)
- **7 conversations without major issues** (47% success rate)

#### Embedded Failure Patterns
1. **Date Format Issues** (3 conversations)
   - Invalid formats: `03/15/2024` instead of `2024-03-15`
   - Tool validation failures

2. **Missing User Preferences** (4 conversations)
   - User specifies detailed requirements (class, budget, amenities)
   - Assistant ignores preferences in tool calls and responses

3. **Incomplete Responses** (2 conversations)
   - Assistant provides minimal information despite detailed user requests

4. **Parameter Validation** (2 conversations)
   - Missing required tool parameters
   - Invalid parameter combinations

## Pipeline Architecture

### Stage 1: Batch Ingestion
```python
# Load conversations from files
conversations = load_conversations("travel_v1_*.json")
ingested = ingestion_service.ingest_batch(conversations)
```

### Stage 2: Staged Evaluation

#### Heuristic Stage (All Conversations)
```python
# Fast rule-based evaluators
heuristic_evaluators = ["heuristic", "tool_call", "tool_causality"]
stage_eval_service = EvaluationService(repo, registry, evaluators=heuristic_evaluators)

# Process all 15 conversations
for conv_id in conversation_ids:
    result = stage_eval_service.evaluate(conv_id)
```
**Catches**: Technical issues (date formats, parameter validation, execution errors)

#### LLM Judge Stage (Filtered)
```python
# Only conversations with issues from Stage 1
llm_service = EvaluationService(repo, registry, evaluators=["llm_judge"])
problematic_convs = [c for c in results if len(c.issues) > 0]

for conv_id in problematic_convs:
    deep_result = llm_service.evaluate(conv_id)
```
**Catches**: Semantic issues (user preferences, response completeness, contextual appropriateness)

### Stage 3: Pattern Analysis
```python
# Cluster issues across conversations
all_evaluations = heuristic_results + llm_results
proposals = analysis_service.run_analysis_cycle(limit=len(conversations))
```

## Results Analysis

### Performance Metrics
```
Conversations Processed: 15
Issues Detected: 18 (1.2 issues/conversation)
Average Score: 0.72
Proposals Generated: 3
```

### Pattern Detection Success
Identified three major failure patterns:

1. **Inadequate User Input Handling** (67.5 significance)
   - Assistant fails to incorporate user preferences
   - Affects 4 conversations with detailed requirements

2. **Inadequate Error Handling** (45.0 significance)
   - Date format validation failures
   - Tool parameter validation issues

3. **Assistive Response Failure** (21.0 significance)
   - Incomplete or unhelpful responses
   - Missing contextual information

### LLM Judge Validation
Demonstrated LLM judge catches semantic issues missed by heuristics:

**Example: `travel_v1_issue_010`**
- **Heuristic Score**: 1.00 (technically valid tool calls)
- **LLM Score**: 0.60 (-0.40 delta)
- **Issues Detected**: User preferences ignored, generic response

## Technical Implementation

### Core Components
- **BatchPipelineProcessor**: Orchestrates staged evaluation
- **EvaluationService**: Manages evaluator execution
- **AnalysisService**: Pattern clustering and proposal generation
- **Repository**: Persistent storage and retrieval

### Evaluator Types
```python
# Heuristic Evaluators
heuristic: Format/latency validation
tool_call: Parameter and execution checking
tool_causality: Tool selection appropriateness

# LLM Judge
llm_judge: Semantic quality assessment
```

### Pattern Clustering
```python
# Issue embedding and clustering
flattened_issues = prepare_batch_data(evaluations, conversations)
clusters = clustering_engine.cluster_issues(flattened_issues)

# Proposal generation
for cluster in clusters:
    proposal = suggestion_engine.generate_proposal(cluster, prompt, tool_schemas)
```

## Usage Examples

### Basic Batch Analysis
```python
from src.pipeline.batch_processor import BatchPipelineProcessor

processor = BatchPipelineProcessor()
result = processor.run_batch_analysis(source_pattern="travel_v1_*.json")
```

### Custom Stages
```python
custom_stages = [
    {"name": "quality_check", "evaluators": ["heuristic"], "filter_criteria": None},
    {"name": "deep_analysis", "evaluators": ["llm_judge"], "filter_criteria": "has_issues"}
]
result = processor.run_batch_analysis(stages=custom_stages)
```

### Individual LLM Evaluation
```python
from src.evaluation.service import EvaluationService

llm_service = EvaluationService(repo, registry, evaluators=["llm_judge"])
result = llm_service.evaluate("conversation_id")
```

## Key Insights

1. **Staged Evaluation**: Heuristics provide fast filtering, LLM judge provides deep semantic analysis
2. **Pattern Embeddings**: Controlled conversation generation enables predictable pattern detection
3. **Cost Optimization**: LLM evaluation only on conversations likely to have issues
4. **Scalability**: Pipeline processes hundreds of conversations efficiently
5. **Actionability**: Generated proposals directly address identified failure patterns

## Future Enhancements

- **Regression Testing**: Automated proposal validation
- **Multi-Agent Analysis**: Compare patterns across agent versions
- **Real-time Processing**: Streaming evaluation for live conversations
- **Advanced Clustering**: ML-based pattern recognition
- **Proposal Prioritization**: Impact-based ranking of improvements
