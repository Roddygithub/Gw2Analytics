"""Arq ``WorkerSettings`` for the parser worker.

v0.10.1 plan 010: started as a separate process via ``arq`` CLI.
Phase 5.2: removed the ``if _REDIS_PORT == 1: raise RuntimeError`` guard
(the guard was dead code — port 1 is now rejected by the Settings
model's ``Field(ge=1)`` validation at startup, making the manual
import-time check redundant).

``max_jobs=2`` is conservative: the parser is CPU-bound and 2 concurrent
parses on a 4-core box leave headroom for the OS + arq's own event
loop + occasional webhook dispatch.

``job_timeout=600`` (10 min) covers the 39MB max file size observed
in the user's archive; the parser completes a 5MB log in ~30s,
a 20MB log in ~2min, so 10min is a safe ceiling.
"""

from __future__ import annotations

from arq.connections import RedisSettings

from gw2analytics_api.config import get_settings
from gw2analytics_api.workers.parser_worker import parse_job

_REDIS_HOST: str = get_settings().arq_redis_host
_REDIS_PORT: int = get_settings().arq_redis_port


class WorkerSettings:
    """Arq worker configuration for the parser pipeline."""

    functions = [parse_job]  # noqa: RUF012
    redis_settings = RedisSettings(host=_REDIS_HOST, port=_REDIS_PORT)
    max_jobs = 2
    job_timeout = 600


__all__ = ["WorkerSettings"]
