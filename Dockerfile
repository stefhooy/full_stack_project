# Backend image for a normal long-running Python host (Render/Fly.io free
# tier) — NOT for Vercel Python functions. See DOCEXP.md's Slice 6 entry
# for why: this stack's dependency footprint (fastembed's ONNX model,
# scipy, DuckDB, multi-step LLM calls with retries) doesn't comfortably
# fit serverless payload-size and execution-time limits.
#
# Ingestion runs at BUILD time (see below), baking a snapshot of the
# SteamSpy catalog into the image. That's a deliberate, documented
# trade-off for a mostly-static demo dataset, not an oversight — see
# DOCEXP.md. Re-deploy (rebuild the image) to refresh the data.

FROM python:3.12-slim

WORKDIR /app

# libgomp1: onnxruntime (fastembed's backend) links against it on some
# base images. Kept minimal deliberately — add more here only if a real
# build failure asks for it, not speculatively.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# uv, copied as a static binary from its official distroless image --
# faster and more reproducible (installs pinned versions from uv.lock)
# than pip + requirements.txt. UV_LINK_MODE=copy avoids a hardlink
# warning uv prints when the cache and target dirs are on different
# Docker layers/filesystems.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/
ENV UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
RUN uv sync --extra agent --frozen
ENV PATH="/app/.venv/bin:${PATH}"

COPY src/ ./src/

# Ingestion needs a real .env (for STEAMSPY_USER_AGENT etc.) and network
# access to steamspy.com — both available at build time on Render/Fly.
# INGEST_GAME_COUNT can be overridden via --build-arg if you want fewer
# games for a faster build while testing the Dockerfile itself.
ARG INGEST_GAME_COUNT=200
ENV INGEST_GAME_COUNT=${INGEST_GAME_COUNT}
RUN python -m src.ingestion.ingest --count ${INGEST_GAME_COUNT}

# player_counts (Slice 7): materialize the table from every snapshot the
# poll_player_counts.yml GitHub Action has committed so far. Safe even
# before that workflow has ever run — build_player_counts_table.py no-ops
# cleanly if data/player_counts_raw/ doesn't exist yet.
COPY data/player_counts_raw/ ./data/player_counts_raw/
RUN python -m src.ingestion.build_player_counts_table

# fastembed's ONNX model also downloads at build time here, via the first
# import that constructs a SchemaIndex — done as a separate layer so a
# requirements-only change doesn't force re-downloading it.
RUN python -c "from src.agent.rag.schema_index import get_schema_index; get_schema_index()"

EXPOSE 8000
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
