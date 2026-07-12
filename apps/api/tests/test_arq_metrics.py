"""Tests for Arq observability metrics (plan 017)."""

from __future__ import annotations

from prometheus_client import generate_latest

from gw2analytics_api.metrics import (
    ARQ_JOB_DURATION,
    ARQ_JOB_QUEUE_WAIT,
    ARQ_JOB_RETRY_DELAY,
    ARQ_JOBS_COMPLETED,
    ARQ_JOBS_FAILED,
    ARQ_JOBS_RETRIED,
    ARQ_QUEUE_DEPTH,
    ARQ_WORKERS_ACTIVE,
)


def test_metrics_module_imports() -> None:
    """All metric objects are importable and have correct types."""
    assert ARQ_JOBS_COMPLETED._documentation == "Total number of Arq jobs completed successfully"
    assert ARQ_JOBS_FAILED._documentation == "Total number of Arq jobs that failed"
    assert ARQ_JOBS_RETRIED._documentation == "Total number of Arq jobs retried"
    assert ARQ_WORKERS_ACTIVE._documentation == "Number of currently active Arq workers"
    assert ARQ_QUEUE_DEPTH._documentation == "Number of jobs waiting in the Arq queue"
    assert ARQ_JOB_DURATION._documentation == "Arq job execution time in seconds"
    assert ARQ_JOB_QUEUE_WAIT._documentation == "Time a job waited in the queue before execution"
    assert ARQ_JOB_RETRY_DELAY._documentation == "Delay before job retry execution"


def test_metrics_counter_increment() -> None:
    """Counter metrics can be incremented."""
    ARQ_JOBS_COMPLETED.labels(queue="test").inc()
    ARQ_JOBS_FAILED.labels(queue="test", error_type="timeout").inc()
    ARQ_JOBS_RETRIED.labels(queue="test", attempt="1").inc()


def test_metrics_gauge_set() -> None:
    """Gauge metrics can be set."""
    ARQ_WORKERS_ACTIVE.labels(queue="test").set(5)
    ARQ_QUEUE_DEPTH.labels(queue="test").set(10)


def test_metrics_histogram_observe() -> None:
    """Histogram metrics can observe values."""
    ARQ_JOB_DURATION.labels(queue="test", status="success").observe(1.5)
    ARQ_JOB_QUEUE_WAIT.labels(queue="test").observe(0.5)
    ARQ_JOB_RETRY_DELAY.labels(queue="test", attempt="1").observe(2.0)


def test_generate_latest_returns_bytes() -> None:
    """generate_latest() returns Prometheus exposition format."""
    output = generate_latest()
    assert isinstance(output, bytes)
    assert b"arq_jobs_completed_total" in output
    assert b"arq_jobs_failed_total" in output
    assert b"arq_job_duration_seconds" in output
