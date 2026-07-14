"""v0.10.12 plan 017 close-out: metrics surface smoke test.

Manual observation: run against a live stack
(``uv run fastapi dev apps/api/src/gw2analytics_api/main.py`` +
``docker compose up -d redis postgres minio`` + Arq worker) to
confirm the observability surface is alive end-to-end.

Usage::

    # From repo root (start the stack first; default port 8000):
    uv run python apps/api/src/gw2analytics_api/scripts/metrics_smoke.py

    # Or point at a non-default base URL:
    METRICS_BASE_URL=http://localhost:9000 uv run python \\
        apps/api/src/gw2analytics_api/scripts/metrics_smoke.py

The script:
1. Hit ``GET <base>/api/v1/health/summary`` (updates HEALTH_DRIFT_COUNT).
2. Hit ``GET <base>/api/v1/metrics`` (Prometheus exposition).
3. Spot-check that 7 expected metric names are present.

Exit code 0 on success; non-zero on any unexpected condition.
"""

from __future__ import annotations

import os
import sys

import httpx

DEFAULT_BASE_URL = "http://localhost:8000"

_EXPECTED_METRICS: tuple[str, ...] = (
    # Arq worker observability (plan 017 core).
    "arq_jobs_completed_total",
    "arq_jobs_failed_total",
    "arq_job_duration_seconds",
    # Health + sweeper close-out (plan 017 delta).
    "health_drift_count",
    "uploads_pending_count",
    "stuck_sweeper_iteration_duration_seconds",
    "stuck_sweeper_marked_failed_total",
)


def main() -> int:
    """Hit ``/api/v1/health/summary`` + ``/api/v1/metrics`` and assert presence."""
    base_url = os.environ.get("METRICS_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    print(f"=== metrics_smoke (base={base_url}) ===", flush=True)

    try:
        with httpx.Client(timeout=5.0) as client:
            # Probe 1: health/summary. Updates the HEALTH_DRIFT_COUNT gauge.
            r1 = client.get(f"{base_url}/api/v1/health/summary")
            r1.raise_for_status()
            status = r1.json().get("status", "?")
            print(f"  health/summary -> {r1.status_code} status={status}", flush=True)
            # Probe 2: scrape /metrics. Returns text/plain Prometheus exposition.
            r2 = client.get(f"{base_url}/api/v1/metrics")
            r2.raise_for_status()
            print(
                f"  metrics        -> {r2.status_code} "
                f"content-type={r2.headers.get('content-type', '?')} "
                f"bytes={len(r2.text)}",
                flush=True,
            )
            # Spot-check the expected metric names.
            missing: list[str] = []
            for req in _EXPECTED_METRICS:
                if req not in r2.text:
                    missing.append(req)
                    print(f"  MISSING: {req}", flush=True)
                else:
                    print(f"  present: {req}", flush=True)
            if missing:
                print(
                    f"ERROR: {len(missing)} expected metric(s) missing: {missing}",
                    file=sys.stderr,
                    flush=True,
                )
                return 1
    except httpx.HTTPError as exc:
        print(f"ERROR: HTTP request failed: {exc}", file=sys.stderr, flush=True)
        return 2

    print("OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
