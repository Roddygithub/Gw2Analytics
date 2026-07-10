# advisor-plan 017 — arq observability metrics (structured counters + gauges + histograms)

## Problem

The arq worker (parser_worker.py) + webhook scheduler (webhook_scheduler.py) + (post-plan-014) stuck-upload sweeper have NO structured metrics surface. The only observability is `logger.info/warning` calls (stdlib `logging`). An operator cannot answer: how many parse jobs/hour, what's the queue depth, what's the failure rate, what's the p95 latency per kind. Worker deadlock is silent until the queue is 1000 deep 2 hours later.

## Context

- `apps/api/src/gw2analytics_api/workers/parser_worker.py:79-114` — `parse_job(ctx)` is the main job handler.
- `apps/api/src/gw2analytics_api/workers/webhook_scheduler.py:303-329` — `lifespan_scheduler` polls every 5s.
- `apps/api/src/gw2analytics_api/workers/stuck_upload_sweeper.py` (built in plan 014) — sweep loop.
- No `opentelemetry`, `prometheus_client`, or `statsd` imports anywhere in `apps/api/src/`.

## Approach

Adopt `prometheus_client` (lightweight, ubiquitous) with a `/metrics` endpoint on the FastAPI app. Emit 3 counters + 2 gauges + 3 histograms:
- Counter: `gw2a_arq_jobs_total{kind, status}` — incremented at end of each arq job.
- Counter: `gw2a_webhook_deliveries_total{status}` — incremented per delivery attempt.
- Counter: `gw2a_health_probe_drift` — current health drift value (already in `health_gate`).
- Gauge: `gw2a_arq_pool_active` — current connections in the arq pool.
- Gauge: `gw2a_uploads_pending_count` — current pending uploads (label: data age bucket).
- Histogram: `gw2a_parse_duration_seconds` — wall-clock per parse (buckets: 1s, 5s, 30s, 60s, 300s).
- Histogram: `gw2a_webhook_latency_seconds` — webhook POST duration.
- Histogram: `gw2a_sweeper_iteration_seconds` — stuck-sweeper pass time.

Add a `services/scripts/metrics_smoke.py` that asserts after N parses the counters + histogram populate correctly.

## Files

**In scope**:
- MODIFIED `apps/api/pyproject.toml` (add `prometheus_client>=0.20` to dependencies)
- MODIFIED `apps/api/src/gw2analytics_api/main.py` (mount `/metrics`)
- MODIFIED `apps/api/src/gw2analytics_api/workers/parser_worker.py` (emit metrics)
- MODIFIED `apps/api/src/gw2analytics_api/workers/webhook_scheduler.py` (emit metrics)
- MODIFIED `apps/api/src/gw2analytics_api/workers/stuck_upload_sweeper.py` (emit metrics)
- MODIFIED `apps/api/src/gw2analytics_api/routes/health.py` (expose `gw2a_health_probe_drift` gauge)
- NEW `apps/api/src/gw2analytics_api/metrics.py` (centralized definitions)
- NEW `apps/api/tests/test_metrics.py`
- NEW `apps/api/src/gw2analytics_api/scripts/metrics_smoke.py`

**Out of scope**:
- Grafana / Prometheus operator infrastructure (operator-side choice).
- A high-cardinality per-fight label (would explode counter).

## Steps

1. Create `apps/api/src/gw2analytics_api/metrics.py` (~120 lines) with the canonical Counter / Gauge / Histogram definitions — DO NOT use `prometheus_client.REGISTRY` defaults; explicitly declare in our own `CollectorRegistry` to avoid side-effects on imports.
2. Modify `apps/api/src/gw2analytics_api/main.py`:
   ```python
   from prometheus_client import make_asgi_app
   _app.mount("/metrics", make_asgi_app())
   ```
3. Modify `parser_worker.py:parse_job`:
   - At start: `start = time.monotonic()`.
   - At end (success OR failure): increment `gw2a_arq_jobs_total{kind="parse", status="completed"|"failed"}` AND observe `gw2a_parse_duration_seconds.observe(elapsed)`.
4. Modify `webhook_scheduler.py:dispatch_one`:
   - Same pattern: increment `gw2a_webhook_deliveries_total{status}` AND observe `gw2a_webhook_latency_seconds`.
5. Modify `stuck_upload_sweeper.py:lifespan_stuck_upload_sweeper` (from plan 014):
   - Set `gw2a_uploads_pending_count` to the rowcount after each iteration; observe `gw2a_sweeper_iteration_seconds`.
6. Modify `routes/health.py`:
   - On each probe: `gw2a_health_probe_drift.set(drift_count)`.
7. Add `apps/api/tests/test_metrics.py`:
   - Respx-mocked arq + webhook mocks; run 2 parse jobs (1 success, 1 failure); assert counters + histogram observations.
8. Add `apps/api/src/gw2analytics_api/scripts/metrics_smoke.py`:
   - Start FastAPI app + run 10 parses via arq; curl `/metrics`; grep for the new metric names; assert presence + non-zero values.

## Verification

- `find apps/api/src -name 'metrics.py'` → 1 file.
- `uv run pytest apps/api/tests/test_metrics.py -v` → all green.
- `uv run pytest` (full suite) → all green.
- Manual smoke (operator): start the stack with `arq` worker running; `curl http://localhost:8000/metrics | grep gw2a_` → matches all 8 metric names.

## Test plan

- 1 new pytest with respx-mocked arq + webhook mocks.
- 1 manual CLI smoke test (`metrics_smoke.py`).
- The default `prometheus_client` REGISTRY should be AVOIDED in test scoping — use a fresh registry per test to avoid cross-test contamination.

## Done criteria

- `metrics.py` defines the 8 metrics.
- `/metrics` endpoint mounted.
- 4 worker modules emit metrics at the right points.
- 1 new pytest + 1 manual smoke test pass.
- Lint + mypy + ruff all green.

## Maintenance note

- High-cardinality labels (per-fight_id, per-account) are forbidden — pick `data age bucket` (e.g. `<1h`, `1h-1d`, `1d+`) which is bounded. Keep cardinality in mind for Prometheus scrape cost.
- `prometheus_client` is process-local; multiple FastAPI or arq workers each emit their own metrics. A real Prometheus deployment needs sidecar aggregation — operator's job, document in `docs/prod-hardening.md`.
- DO NOT put credentials in metric labels — Prometheus labels are visible to anyone with `curl /metrics` access.

## Escape hatch

- If the operator prefers OpenTelemetry, swap `prometheus_client` for `opentelemetry-exporter-prometheus` or `otel-stdout-exporter`. Same counter/gauge semantics.
- If a future arq version adds native instrumentation, prefer that over hand-rolled emission in `parser_worker.py`.
- If metric cardinality becomes a real ops issue (>50 series per scrape), drop the histograms for the cheap success path; keep only failure latency.
