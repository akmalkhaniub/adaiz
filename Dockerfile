# Multi-Stage Production Dockerfile for AdAiz (uv + Python 3.13)
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --no-install-project

COPY src ./src
COPY evals ./evals
COPY README.md ./
RUN uv sync --no-dev

FROM python:3.13-slim-bookworm AS runtime
WORKDIR /app

RUN groupadd -r adaiz && useradd -r -g adaiz adaiz
COPY --from=builder --chown=adaiz:adaiz /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PORT=8000

USER adaiz
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health')" || exit 1

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
