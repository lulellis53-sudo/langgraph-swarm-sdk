# syntax=docker/dockerfile:1
# WebSearch CLI + HTTP API image. Build context is the repo root (the WebSearch package dir).
FROM python:3.14-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /uvx /usr/local/bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON=/usr/local/bin/python3.14 \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH=/opt/venv/bin:$PATH

WORKDIR /app/WebSearch

# Dependencies first so source edits do not invalidate the venv layer.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra websearch

# Optional headless Chromium for the browse agent (adds ~600 MB).
ARG INSTALL_BROWSER=0
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
RUN if [ "$INSTALL_BROWSER" = "1" ]; then playwright install --with-deps chromium; fi

COPY . .

RUN useradd --create-home --uid 10001 websearch \
    && mkdir -p /data && chown websearch /data
USER websearch

ENTRYPOINT ["python", "-m", "WebSearch"]
