"""v0.10.1 plan 010: Arq worker that runs the EVTC parser + webhook dispatch.

Phase 6.2: calls ``setup_logging()`` at module level so the Arq
worker process (separate from the API process) uses the same
structured JSON logging format as the API.

Why this exists
===============

Real-payload testing on 2026-07-09 surfaced bug #2: 8 parallel
``.zevtc`` uploads all stuck on ``pending`` after 20s while a
single sequential upload completed fine. Root cause: FastAPI's
``BackgroundTasks`` runs in a thread pool that shares the
Python GIL. 8 CPU-bound :func:`gw2analytics_api.services.process_parse`
calls serialise on the GIL and none finish quickly.

This module moves ``process_parse`` to a dedicated Arq worker
process (separate GIL, separate core pool, ``max_jobs=2``) and
chained ``dispatch_for_upload`` immediately after so the
upload->webhook handoff is no longer racy.

The race that this also closes
==============================

The pre-v0.10.1 ``routes/uploads.py`` scheduled
``process_parse`` and ``dispatch_for_upload`` as TWO
independent ``BackgroundTasks`` on the same response.
``dispatch_for_upload`` short-circuits if
``upload.status != UPLOAD_STATUS_COMPLETED``; the parser had
not yet committed the status flip when the dispatch ran, so
zero deliveries fired on every successful upload. Chaining
inside a single Arq job (``parse_job`` awaits ``process_parse``
before invoking ``dispatch_for_upload``) closes this gap with
no code change to the dispatch function itself.

Sync-in-asyncio
===============

``process_parse`` and ``dispatch_for_upload`` are CPU-bound
and I/O-bound sync functions (the parser is C-extension-free
pure Python; the dispatch opens an ``httpx.Client``). Both
must NOT block the Arq event loop, so each call is wrapped in
``asyncio.to_thread`` which offloads to the default
``ThreadPoolExecutor`` (Arq's own loop stays responsive for
the next job pickup).

Failure modes
=============

- ``process_parse`` raises: the Arq job re-raises; Arq's
  built-in retry kicks in. ``dispatch_for_upload`` is NOT
  called -- the parse is the gate. Future iteration:
  the plan documents exponential-backoff retry via
  ``ctx.job_try`` (Arq's ``Context`` object exposes
  ``job_try`` as an attribute, not a dict key -- the
  earlier docstring's ``ctx["job_try"]`` notation was
  stale from the pre-Arq design; a future caller must
  use attribute access). For v0.10.1 the default retry
  is fine.
- ``dispatch_for_upload`` raises after a successful parse:
  the exception is logged at EXCEPTION (with the
  ``parse already committed`` hint) and SWALLOWED. The
  parse is the user-visible contract; a missed webhook
  delivery is an operational concern (the operator can
  re-dispatch manually). Re-running the parse would
  duplicate the fight row, so the chain does NOT retry.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any
from uuid import UUID

from gw2analytics_api.config import setup_logging
from gw2analytics_api.database import get_sessionmaker
from gw2analytics_api.metrics import ARQ_JOB_DURATION, ARQ_JOBS_COMPLETED, ARQ_JOBS_FAILED
from gw2analytics_api.services import process_parse
from gw2analytics_api.workers.webhook_dispatch import dispatch_for_upload

# Phase 6.2: structured JSON logging for the Arq worker process.
setup_logging()

logger = logging.getLogger(__name__)

# Queue label for metrics (parser worker uses the "parser" queue)
_QUEUE_LABEL = "parser"


async def parse_job(
    ctx: Any,  # noqa: ARG001  # arq requires the first arg; unused in v0.10.1
    upload_id: str,
    raw_bytes: bytes,
) -> None:
    """Arq job: parse one upload, then dispatch webhooks (chained).

    Parameters
    ----------
    ctx:
        The Arq job context. Unused in v0.10.1 (no retry budget
        tweaking) but accepted because Arq requires the first
        parameter to be the context dict.
    upload_id:
        The :class:`uuid.UUID` of the :class:`Upload` row
        (serialised as ``str`` for the Redis transport).
    raw_bytes:
        The original ``.zevtc`` bytes that were POSTed to
        ``/api/v1/uploads``. The Arq enqueue serialises
        these as the second job argument; arq stores them
        in Redis with the standard ``LargeBinary`` encoding
        (no base64 round-trip).

    Raises
    ------
    Exception
        Any exception raised by :func:`process_parse` is
        re-raised so Arq's default retry mechanism kicks in.
        Exceptions raised by :func:`dispatch_for_upload` are
        LOGGED but NOT re-raised (the parse is the contract;
        the dispatch is best-effort).
    """
    sf = get_sessionmaker()
    parsed_upload_id = UUID(upload_id)
    start_time = time.monotonic()
    try:
        await asyncio.to_thread(process_parse, sf, parsed_upload_id, raw_bytes)
        del raw_bytes
    except Exception:
        elapsed = time.monotonic() - start_time
        ARQ_JOBS_FAILED.labels(queue=_QUEUE_LABEL, error_type="parse").inc()
        ARQ_JOB_DURATION.labels(queue=_QUEUE_LABEL, status="failed").observe(elapsed)
        logger.exception(
            "parse_job parse failed for upload %s; not dispatching webhooks",
            upload_id,
        )
        raise
    try:
        await dispatch_for_upload(sf, parsed_upload_id)
    except Exception:
        logger.exception(
            "parse_job dispatch failed for upload %s "
            "(parse already committed; webhook deliveries skipped)",
            upload_id,
        )
    elapsed = time.monotonic() - start_time
    ARQ_JOBS_COMPLETED.labels(queue=_QUEUE_LABEL).inc()
    ARQ_JOB_DURATION.labels(queue=_QUEUE_LABEL, status="success").observe(elapsed)


__all__ = ["parse_job"]
