FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1

WORKDIR /app

# Install system deps needed for building wheels
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

# Install poetry and dependencies
RUN pip install --no-cache-dir poetry

COPY pyproject.toml poetry.lock README.md /app/
RUN poetry install --only main --no-root

# Copy application code
COPY src /app/src
COPY artifacts /app/artifacts

EXPOSE 8000

CMD ["poetry", "run", "uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
