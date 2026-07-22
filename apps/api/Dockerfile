# --- builder stage ---
FROM astral/uv:python3.12-bookworm AS builder

WORKDIR /app

# Copy workspace root config + lockfile
COPY pyproject.toml uv.lock /app/

# Copy all workspace members so uv can resolve path dependencies
COPY libs/gw2_core /app/libs/gw2_core
COPY libs/gw2_evtc_parser /app/libs/gw2_evtc_parser
COPY libs/gw2_analytics /app/libs/gw2_analytics
COPY libs/gw2_api_client /app/libs/gw2_api_client
COPY apps/api /app/apps/api

# Install API + its workspace path deps (libs/) into .venv.
# The root pyproject.toml is a virtual project (package=false),
# so uv sync at the root needs --package to pick a member.
# Editable install (default) so __file__-based path resolution
# in schema_guard.py finds alembic.ini relative to the source tree.
# --mount=type=cache caches uv's downloaded wheels across rebuilds.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package gw2analytics_api

# --- runtime stage ---
FROM python:3.12-slim

# --mount=type=cache caches apt packages across rebuilds to avoid
# re-downloading on every image build.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Create the non-root user FIRST so we can use --chown on COPY
# (avoids a 119 MB redundant chown layer on the venv).
RUN useradd -r appuser

# Copy the entire venv from builder with --chown (editable .pth files point to source).
# This collapses the previous "COPY + chown -R" into a single layer.
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
# Copy workspace source trees (needed by editable .pth files + alembic)
COPY --from=builder --chown=appuser:appuser /app/libs/gw2_core /app/libs/gw2_core
COPY --from=builder --chown=appuser:appuser /app/libs/gw2_evtc_parser /app/libs/gw2_evtc_parser
COPY --from=builder --chown=appuser:appuser /app/libs/gw2_analytics /app/libs/gw2_analytics
COPY --from=builder --chown=appuser:appuser /app/libs/gw2_api_client /app/libs/gw2_api_client
COPY --from=builder --chown=appuser:appuser /app/apps/api/src /app/apps/api/src
COPY --from=builder --chown=appuser:appuser /app/apps/api/alembic /app/apps/api/alembic
COPY --from=builder --chown=appuser:appuser /app/apps/api/alembic.ini /app/apps/api/alembic.ini

ENV PATH="/app/.venv/bin:$PATH"

USER appuser

WORKDIR /app/apps/api

EXPOSE 8000

CMD ["uvicorn", "gw2analytics_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "120", "--workers", "2"]
