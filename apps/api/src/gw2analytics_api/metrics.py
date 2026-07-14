"""Prometheus metrics for Arq workers (plan 017).

Exposes counters, gauges, and histograms for worker observability.
Metrics are registered at module import time and updated by the
worker middleware/hooks.

Metric inventory (plan 017 spec):
- arq_jobs_completed_total: Counter — jobs completed (labels: queue)
- arq_jobs_failed_total: Counter — jobs failed (labels: queue, error_type)
- arq_jobs_retried_total: Counter — jobs retried (labels: queue, attempt)
- arq_workers_active: Gauge — currently active workers (labels: queue)
- arq_jobs_queue_depth: Gauge — jobs waiting in queue (labels: queue)
- arq_job_duration_seconds: Histogram — job execution time (labels: queue, status)
- arq_job_queue_wait_seconds: Histogram — time waiting in queue (labels: queue)
- arq_job_retry_delay_seconds: Histogram — delay before retry (labels: queue, attempt)

Plan 017 close-out (addition):
- health_drift_count: Gauge — `OrmFightPlayerSummary` drift
  (set by /api/v1/health/summary)
- uploads_pending_count: Gauge — uploads currently in `pending` status
  (set by stuck_upload_sweeper)
- stuck_sweeper_iteration_duration_seconds: Histogram — sweep-iteration wallclock
  (set by lifespan_stuck_upload_sweeper)
- stuck_sweeper_marked_failed_total: Counter — uploads promoted `pending` → `failed`
  by the sweeper (set by _sweep_once)
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# ---------------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------------

ARQ_JOBS_COMPLETED = Counter(
    "arq_jobs_completed_total",
    "Total number of Arq jobs completed successfully",
    ["queue"],
)

ARQ_JOBS_FAILED = Counter(
    "arq_jobs_failed_total",
    "Total number of Arq jobs that failed",
    ["queue", "error_type"],
)

ARQ_JOBS_RETRIED = Counter(
    "arq_jobs_retried_total",
    "Total number of Arq jobs retried",
    ["queue", "attempt"],
)

# ---------------------------------------------------------------------------
# Gauges
# ---------------------------------------------------------------------------

ARQ_WORKERS_ACTIVE = Gauge(
    "arq_workers_active",
    "Number of currently active Arq workers",
    ["queue"],
)

ARQ_QUEUE_DEPTH = Gauge(
    "arq_jobs_queue_depth",
    "Number of jobs waiting in the Arq queue",
    ["queue"],
)

# ---------------------------------------------------------------------------
# Histograms
# ---------------------------------------------------------------------------

ARQ_JOB_DURATION = Histogram(
    "arq_job_duration_seconds",
    "Arq job execution time in seconds",
    ["queue", "status"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
)

ARQ_JOB_QUEUE_WAIT = Histogram(
    "arq_job_queue_wait_seconds",
    "Time a job waited in the queue before execution",
    ["queue"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

ARQ_JOB_RETRY_DELAY = Histogram(
    "arq_job_retry_delay_seconds",
    "Delay before job retry execution",
    ["queue", "attempt"],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0),
)

# ---------------------------------------------------------------------------
# Plan 017 close-out — health + sweeper observability
# ---------------------------------------------------------------------------

#: Plan 017 close-out: tracks the `OrmFightPlayerSummary` drift count
#: surfaced by ``GET /api/v1/health/summary``. Updated on every probe
#: call (in :mod:`gw2analytics_api.routes.health`). Labels intentionally
#: empty: a single production table drives the value.
HEALTH_DRIFT_COUNT = Gauge(
    "health_drift_count",
    "Current fight-summary drift count (fights with no player-summary rows)",
)

#: Plan 017 close-out: tracks the current number of uploads in
#: ``pending`` status. Updated by the stuck-upload sweeper
#: (``lifespan_stuck_upload_sweeper``) AFTER each sweep iteration
#: so the gauge reflects the post-sweep state. The gauge exists
#: for operator alerting (anyone whose sweeper is silently broken
#: will see the gauge stuck >0).
UPLOADS_PENDING_COUNT = Gauge(
    "uploads_pending_count",
    "Current uploads in 'pending' status (post-sweep)",
)

#: Plan 017 close-out: tracks wallclock time of each sweeper
#: iteration. Buckets sized for the default 300s interval + small
#: bursts (5s, 30s, 60s) and large parses (>5min). Use the
#: ``.observe(elapsed_seconds)`` contract.
STUCK_SWEEPER_ITERATION_DURATION = Histogram(
    "stuck_sweeper_iteration_duration_seconds",
    "Wallclock time of one stuck-upload sweeper iteration",
    buckets=(0.05, 0.25, 1.0, 5.0, 30.0, 60.0, 300.0),
)

#: Plan 017 close-out: cumulative count of uploads promoted from
#: ``pending`` to ``failed`` by the stuck-upload sweeper. Diff
#: before/after a sweeper run to confirm the sweeper picked up
#: stale rows (a non-delta means the sweeper is broken OR there
#: were no stale rows to pick up — log correlation needed).
_STUCK_SWEEPER_MARKED_FAILED_HELP = (
    "Total uploads promoted pending to failed by the stuck-upload sweeper"
)
STUCK_SWEEPER_MARKED_FAILED = Counter(
    "stuck_sweeper_marked_failed_total",
    _STUCK_SWEEPER_MARKED_FAILED_HELP,
)

__all__ = [
    "ARQ_JOBS_COMPLETED",
    "ARQ_JOBS_FAILED",
    "ARQ_JOBS_RETRIED",
    "ARQ_JOB_DURATION",
    "ARQ_JOB_QUEUE_WAIT",
    "ARQ_JOB_RETRY_DELAY",
    "ARQ_QUEUE_DEPTH",
    "ARQ_WORKERS_ACTIVE",
    "HEALTH_DRIFT_COUNT",
    "STUCK_SWEEPER_ITERATION_DURATION",
    "STUCK_SWEEPER_MARKED_FAILED",
    "UPLOADS_PENDING_COUNT",
]
