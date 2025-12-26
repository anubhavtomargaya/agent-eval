# Running the AI Agent Evaluation Pipeline

## Quick Start

### 1. Install Dependencies

```bash
poetry install
```

### 2. Start the Server

```bash
poetry run uvicorn src.api.main:app --reload --port 8000
```

### 3. Open API Docs

```
http://localhost:8000/docs
```
