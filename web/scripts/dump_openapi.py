"""Dump the FastAPI ``app.openapi()`` JSON to stdout.

Used by the web/ TypeScript codegen pipeline. Replaces the previous
``uvicorn ... &`` + ``curl`` readiness loop in CI, which suffered
from port-collision risk, zombie processes, and a ~6-15 s startup
wait. ``app.openapi()`` returns the SAME dict that uvicorn would
serve over HTTP under ``GET /openapi.json`` -- the FastAPI source
calls the same helper -- so there is no drift risk.

Env vars (must match apps/api/src/gw2analytics_api/config.py:Settings)
=========================================================================
:class:`Settings` is required by :mod:`apps.api.config` and has no
defaults for ``DATABASE_URL`` / ``S3_*``. Importing the FastAPI app
triggers Pydantic validation that reads these env vars. At codegen
time no real connection is opened -- ``app.openapi()`` just walks
the route declarations -- so any non-empty string is fine.

We **self-default** the env vars to ``"ci-dummy"`` if absent:

- removes the entire ``env:`` block from the CI yaml step
- removes the silent Settings-vs-script-drift risk
- the existing validation in :class:`Settings` still serves as a
  fail-fast in production contexts where these vars are required
  for actual work

If you add a NEW required field to :class:`Settings`, add it to
``_REQUIRED_ENV`` below so the codegen step keeps running.
"""

from __future__ import annotations

import base64
import json
import os
import sys

_REQUIRED_ENV: tuple[str, ...] = (
    "DATABASE_URL",
    "S3_ENDPOINT",
    "S3_ACCESS_KEY",
    "S3_SECRET_KEY",
    "S3_BUCKET",
    "SECRETS_KEK",
)

# Self-default: the script never opens a connection, so any token
# shape satisfies :class:`Settings`. A true production call must
# supply real credentials (and :class:`Settings` validates them
# downstream); this default is purely for the codegen plumbing.
for var in _REQUIRED_ENV:
    default: str = "ci-dummy"
    if var == "SECRETS_KEK":
        # Settings validates SECRETS_KEK as a 44-char URL-safe
        # base64 Fernet key, so generate a deterministic dummy.
        default = base64.urlsafe_b64encode(b"a" * 32).decode()
    os.environ.setdefault(var, default)

# Suppress log output during import -- setup_logging() in main.py
# prints JSON log lines to stderr during app construction, which
# would contaminate the OpenAPI JSON stdout dump.
import logging

logging.disable(logging.CRITICAL)

from gw2analytics_api.main import app  # noqa: E402


def main() -> int:
    """Write the OpenAPI JSON spec to stdout, exit 1 on failure."""
    spec = app.openapi()
    json.dump(spec, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
