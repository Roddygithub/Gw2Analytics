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
COPY libs/gw2_skills /app/libs/gw2_skills
COPY apps/api /app/apps/api

# Install API + its workspace path deps (libs/) into .venv.
# The root pyproject.toml is a virtual project (package=false),
# so uv sync at the root needs --package to pick a member.
# --no-editable: install as regular packages (not editable .pth)
# so the runtime stage only needs the venv, not the source trees.
RUN uv sync --frozen --no-dev --no-editable --package gw2analytics_api

# --- runtime stage ---
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends libpq5 && rm -rf /var/lib/apt/lists/*

# Copy the entire venv from builder (has all packages installed non-editably)
COPY --from=builder /app/.venv /app/.venv
# Copy alembic config for runtime migrations (non-package files)
COPY --from=builder /app/apps/api/alembic /app/apps/api/alembic
COPY --from=builder /app/apps/api/alembic.ini /app/apps/api/alembic.ini

ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /app/apps/api

EXPOSE 8000

CMD ["uvicorn", "gw2analytics_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "120", "--workers", "2"]
