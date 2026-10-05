# Multi-stage production build for LangGraph Swarm SDK API Service
# Stage 1: Build virtual environment with uv
FROM python:3.14-slim AS builder

WORKDIR /app

# Install uv for fast dependency resolution and virtualenv creation
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uv/bin/uv

# Copy dependency definitions and lockfile
COPY pyproject.toml uv.lock README.md ./

# Create virtual environment and install frozen non-dev dependencies
RUN /uv/bin/uv sync --frozen --no-dev --no-editable

# Stage 2: Runtime image
FROM python:3.14-slim AS runtime

# Security: Create non-root system group and user
RUN groupadd -r appgroup && useradd -r -g appgroup -u 10001 appuser

WORKDIR /app

# Copy virtual environment from builder stage
COPY --from=builder /app/.venv /app/.venv
# Copy application source code and agent manifests
COPY src/ /app/src/
COPY Agents/ /app/Agents/
COPY Main/ /app/Main/
COPY pyproject.toml /app/

# Set environment variables for non-buffered output and venv PATH
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH="/app/src:/app"

# Set ownership to non-root appuser
RUN chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')" || exit 1

ENTRYPOINT ["swarm-api"]
