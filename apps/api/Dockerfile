# --- builder stage ---
FROM astral/uv:python3.12-bookworm AS builder

WORKDIR /app

# Install prod deps only (lockfile-resolved exact versions)
COPY pyproject.toml uv.lock /app/
RUN uv sync --frozen --no-dev

# Copy application code
COPY apps/api/src /app/apps/api/src
COPY apps/api/alembic /app/apps/api/alembic
COPY apps/api/alembic.ini /app/apps/api/alembic.ini

# --- runtime stage ---
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends libpq5 && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/apps/api /app/apps/api

ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /app/apps/api

EXPOSE 8000

CMD ["uvicorn", "gw2analytics_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "120", "--workers", "2"]
