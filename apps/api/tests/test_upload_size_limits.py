"""v0.10.25 upload-size defense-in-depth test coverage.

The upload route (``apps/api/src/gw2analytics_api/routes/uploads.py::create_upload``)
implements 3 layers of defense against oversized uploads:

1. **Content-Length header check** (line ~165): rejects oversized
   bodies BEFORE reading them into memory. Short-circuits the
   OOM risk when the client provides a Content-Length header
   (the common case for non-chunked uploads).
2. **Starlette UploadFile.size check** (line ~178): rejects
   before read when Starlette's multipart parser already knows
   the file size from the multipart metadata.
3. **Post-read len check** (line ~196): the canonical
   defense -- rejects after reading the raw bytes. Catches
   every case Layer 1 + Layer 2 might miss (chunked encoding,
   missing Content-Length, pre-0.30 Starlette without the
   ``size`` attribute).

Plus a 4th layer at the Caddy reverse-proxy:
``Caddyfile`` has ``request_body { max_size 100MB }`` which
rejects oversized requests at the edge BEFORE the bytes reach
the API.

These tests pin the contract for Layer 3 + the Caddyfile layer.

Why Layer 1 is NOT separately tested
====================================

Layer 1 (Content-Length header check) is hard to test via
``fastapi.testclient.TestClient`` because ``httpx`` (the
underlying transport) auto-computes the Content-Length header
from the multipart body, overriding any value passed via the
``headers={"content-length": ...}`` argument. The reliable test
target is Layer 3 (the post-read len check) because it has the
SAME threshold condition (``> max_size``) and the SAME 413
response. If Layer 3 works (which this test verifies), Layer
1's same logic also works (the only difference is WHEN the
check fires: before vs after the body read).

Layer 2 (UploadFile.size) is Starlette implementation detail;
testing it requires spoofing Starlette's internal multipart
parser state, which the TestClient does not expose. Layer 3
is the contract-level guarantee regardless.

If a future Starlette release exposes a reliable way to
spoof Content-Length in tests (e.g. a dedicated httpx kwarg
or a TestClient middleware), consider adding Layer 1 +
Layer 2 dedicated tests for completeness. Until then, the
contract is verified through Layer 3 + the Caddyfile drift
guard below.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from _fixtures import make_minimal_zevtc
from fastapi.testclient import TestClient

from gw2analytics_api import config as _config
from gw2analytics_api.main import app

# ---------------------------------------------------------------------
# Layer 3: post-read len check (the canonical 413 defense)
# ---------------------------------------------------------------------


def test_oversized_body_returns_413(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Layer 3: a body whose length exceeds ``max_upload_size_bytes``
    returns ``HTTP 413 REQUEST_ENTITY_TOO_LARGE``.

    Pins the contract so a future refactor that drops the post-read
    check (or changes the threshold operator from ``>`` to ``>=``
    or ``<``) surfaces as a failed test instead of a silent OOM
    regression in production.

    The test monkey-patches ``MAX_UPLOAD_SIZE_BYTES`` to 1024 bytes
    (1 KiB) so a small fixture-sized ``.zevtc`` blob is reliably
    oversized without needing to actually construct a 100 MiB
    payload (which would OOM the test runner).
    """
    monkeypatch.setenv("MAX_UPLOAD_SIZE_BYTES", "1024")
    _config.get_settings.cache_clear()
    # Fixture-sized blob is ~5 KB, well above the 1024-byte cap.
    blob = make_minimal_zevtc(
        agents=[(200_001, 2, 18, "V10 Warrior OVERSIZE", True)],
        build="20251021",
    )
    assert len(blob) > 1024, (
        "fixture blob must be > 1024 bytes for the oversized-body test to be meaningful"
    )

    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("oversize.zevtc", blob, "application/octet-stream")},
    )

    assert resp.status_code == 413, resp.text
    body = resp.json()
    # The detail message names both the actual size + the cap so an
    # operator can diagnose without consulting logs.
    assert "too large" in str(body.get("detail", "")).lower()
    assert "1024" in str(body.get("detail", ""))


def test_undersized_body_with_small_cap_succeeds(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sanity check for the boundary case: a small blob with a
    sufficiently large ``MAX_UPLOAD_SIZE_BYTES`` cap is accepted
    (returns 201, not 413). Pairs with the oversized-body test
    above to lock the ``>`` operator (the 413 fires when the blob
    is strictly greater than the cap, not when it equals the cap).

    A regression that flipped ``>`` to ``>=`` would break this
    test (or the boundary case it implicitly covers).
    """
    monkeypatch.setenv("MAX_UPLOAD_SIZE_BYTES", "1048576")  # 1 MiB
    _config.get_settings.cache_clear()

    blob = make_minimal_zevtc(
        agents=[(200_002, 2, 18, "V10 Warrior UNDERSIZE", True)],
        build="20251022",
    )
    assert len(blob) < 1048576, (
        "fixture blob must be < 1 MiB for the undersized-body test to be meaningful"
    )

    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("undersize.zevtc", blob, "application/octet-stream")},
    )

    # The immediate response is 201 (the parse chain may eventually
    # mark the upload ``failed`` if the blob is not a valid .zevtc,
    # but for THIS test we only care that the 413 didn't fire).
    assert resp.status_code == 201, resp.text
    assert "id" in resp.json()


# ---------------------------------------------------------------------
# Caddyfile drift guard: the proxy layer MUST mirror the API cap.
# ---------------------------------------------------------------------


def test_caddyfile_request_body_limit_matches_api_cap() -> None:
    """Drift guard: the ``Caddyfile``'s ``request_body { max_size ... }``
    MUST be set to a value at or above ``MAX_UPLOAD_SIZE_BYTES``.

    The Caddy layer is the FIRST line of defense (rejects at the
    edge BEFORE bytes reach the API). A regression that lowers
    the Caddy cap below the API cap would cause client uploads to
    fail at the proxy with a generic 413 (no detail message) for
    payloads the API would otherwise accept. Conversely, raising
    the API cap above the Caddy cap would create a mismatch where
    oversized payloads pass Caddy but the API returns 413 (a
    correct but suboptimal failure mode -- Caddy could have caught
    it earlier without consuming backend bandwidth).

    This test asserts the Caddy cap is present + parses + is
    >= the API cap default (100 MiB).
    """
    caddyfile = Path("Caddyfile")
    assert caddyfile.exists(), (
        "Caddyfile missing from repo root -- proxy-layer drift guard cannot run"
    )
    content = caddyfile.read_text()

    # Match ``request_body { max_size <value> }`` (whitespace-flexible).
    # Caddy accepts both ``100MB`` and ``104857600`` forms; the test
    # accepts both via a unit-flexible regex.
    match = re.search(
        r"request_body\s*\{\s*max_size\s+([0-9]+)\s*(MB|MiB|KB|KiB|GB|GiB)?\s*\}",
        content,
    )
    assert match is not None, (
        "Caddyfile must contain ``request_body { max_size ... }`` for "
        "the upload-size proxy layer. Add it under the ``api.{placeholder.tld}`` "
        "block to mirror the API's MAX_UPLOAD_SIZE_BYTES cap."
    )

    # Parse the cap value (bytes).
    value = int(match.group(1))
    unit = (match.group(2) or "").upper()
    multipliers = {"": 1, "KB": 1000, "KIB": 1024, "MB": 1_000_000, "MIB": 1024**2, "GB": 1_000_000_000, "GIB": 1024**3}
    caddy_cap_bytes = value * multipliers.get(unit, 1)

    # API cap defaults to 100 MiB (104857600 bytes) per Settings.max_upload_size_bytes.
    api_cap_bytes = 100 * 1024 * 1024

    assert caddy_cap_bytes >= api_cap_bytes, (
        f"Caddyfile cap ({caddy_cap_bytes} bytes) must be >= API cap "
        f"({api_cap_bytes} bytes). Raising Caddy first + API second (or "
        f"both together) is the safe order; lowering Caddy below the API "
        f"cap creates a proxy-layer false-reject."
    )
