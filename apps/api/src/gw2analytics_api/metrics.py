"""Prometheus metrics for Arq workers (plan 017).

Exposes counters, gauges, and histograms for worker observability.
Metrics are registered at module import time and updated by the
worker middleware/hooks.

Metric inventory (plan 017 spec):
- arq_jobs_completed_total: Counter — jobs completed (labels: queue, status)
- arq_jobs_failed_total: Counter — jobs failed (labels: queue, error_type)
- arq_jobs_retried_total: Counter — jobs retried (labels: queue, attempt)
- arq_workers_active: Gauge — currently active workers (labels: queue)
- arq_jobs_queue_depth: Gauge — jobs waiting in queue (labels: queue)
- arq_job_duration_seconds: Histogram — job execution time (labels: queue, status)
- arq_job_queue_wait_seconds: Histogram — time waiting in queue (labels: queue)
- arq_job_retry_delay_seconds: Histogram — delay before retry (labels: queue, attempt)
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

__all__ = [
    "ARQ_JOBS_COMPLETED",
    "ARQ_JOBS_FAILED",
    "ARQ_JOBS_RETRIED",
    "ARQ_JOB_DURATION",
    "ARQ_JOB_QUEUE_WAIT",
    "ARQ_JOB_RETRY_DELAY",
    "ARQ_QUEUE_DEPTH",
    "ARQ_WORKERS_ACTIVE",
]
