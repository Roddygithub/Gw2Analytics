"""Shared fixtures and assertion helpers for webhook E2E tests.

Extracted from ``test_webhooks_e2e.py`` so the main E2E file stays
under 800 lines.
"""

from __future__ import annotations

import uuid as _uuid
from typing import Any, cast

from fastapi.testclient import TestClient
from httpx import Response

from gw2analytics_api.main import app

client = TestClient(app)


def _new_sub_url(suffix: str | None = None) -> str:
    """Return a unique HTTPS URL per test invocation.

    The uuid-derived suffix is appended to a public IPv4 literal
    URL so each test writes a UNIQUE ``url`` column value without
    triggering the SSRF block.
    """
    sfx = suffix or _uuid.uuid4().hex[:8]
    return f"https://93.184.216.34/wh-{sfx}"


def _post_sub(url: str = "") -> Response:
    """POST /api/v1/webhooks with the canonical test body."""
    body = {
        "url": url or _new_sub_url(),
        "filter": {"kind": "upload_completed"},
        "description": None,
    }
    return cast(
        Response,
        client.post("/api/v1/webhooks", json=body),
    )


def _bounds(field_info: Any) -> tuple[int | None, int | None]:
    """Extract min/max length from a Pydantic v2 FieldInfo metadata."""
    fmin: int | None = None
    fmax: int | None = None
    for entry in field_info.metadata:
        entry_min = getattr(entry, "min_length", None)
        entry_max = getattr(entry, "max_length", None)
        if isinstance(entry_min, int):
            fmin = entry_min
        if isinstance(entry_max, int):
            fmax = entry_max
    return fmin, fmax
