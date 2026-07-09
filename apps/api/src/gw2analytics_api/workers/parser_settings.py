"""v0.10.1 plan 010: Arq ``WorkerSettings`` for the parser worker.

The worker is started in a separate process via the standard
arq CLI convention::

    cd apps/api && PYTHONPATH=. SECRETS_KEK=... \\
        arq gw2analytics_api.workers.parser_settings.WorkerSettings

The arq CLI looks up ``WorkerSettings`` by import path, calls
``WorkerSettings().redis_settings`` to connect to the broker,
and registers ``WorkerSettings().functions`` as the job
handlers. The CLI also wires up the ``on_startup`` /
``on_shutdown`` lifecycle hooks (none in v0.10.1; the worker
opens fresh sessions per-job via the standard
``get_sessionmaker()()`` pattern).

``max_jobs=2`` is conservative: the parser is CPU-bound
(``PythonEvtcParser.parse`` is pure Python, no C extension)
and 2 concurrent parses on a 4-core box leave headroom for
the OS + arq's own event loop + occasional webhook
dispatch. Raise to ``os.cpu_count()`` if the 20MB+ WvW log
files become the norm (currently 6 / 1,605 = 0.4% of the
user's archive).

``job_timeout=600`` (10 min) covers the 39MB max file size
observed in the user's archive; the parser completes a
5MB log in ~30s, a 20MB log in ~2min, so 10min is a safe
ceiling that does not mask a true hang (Arq will surface
the timeout as a job failure).
"""

from __future__ import annotations

import os

from arq.connections import RedisSettings  # arq ships no .pyi stubs; mypy infers Any

from gw2analytics_api.workers.parser_worker import parse_job

# v0.10.1 plan 010 followup (code-reviewer round-3): the
# Redis host is now read from env so a production deploy
# behind a remote broker does NOT require a code change.
# The ``localhost`` / 6379 defaults preserve the v0.10.1
# dev experience (the local ``docker compose up redis``
# listens on the default port). The CLI worker process
# reads these at module import; the FastAPI app's lifespan
# reads them via the same import chain.
_REDIS_HOST: str = os.environ.get("ARQ_REDIS_HOST", "localhost")
_REDIS_PORT: int = int(os.environ.get("ARQ_REDIS_PORT", "6379"))


class WorkerSettings:
    """Arq worker configuration for the parser pipeline.

    The class (not instance) is what the arq CLI imports; the
    arq runner reads the class attributes and constructs the
    worker without calling ``__init__``.

    ``functions = [parse_job]`` is a class attribute, NOT a
    mutable default; the ``noqa: RUF012`` silences ruff's
    false positive (the rule flags instance method defaults,
    not class attributes).
    """

    functions = [parse_job]  # noqa: RUF012
    redis_settings = RedisSettings(host=_REDIS_HOST, port=_REDIS_PORT)
    max_jobs = 2
    job_timeout = 600  # 10 min; covers 39MB WvW logs


__all__ = ["WorkerSettings"]
