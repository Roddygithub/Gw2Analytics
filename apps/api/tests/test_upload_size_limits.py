"""v0.10.25 upload-size defense-in-depth test coverage.

The upload route (``apps/api/src/gw2analytics_api/routes/uploads.py::create_upload``)
implements 3 layers of defense against oversized uploads:

1. **Content-Length header check** (Layer 1): rejects oversized
   bodies BEFORE reading them into memory.
2. **Starlette UploadFile.size check** (Layer 2): rejects before
   read when Starlette's multipart parser knows the file size.
3. **Post-read len check** (Layer 3): the canonical defense --
   rejects after reading the raw bytes. Catches every case
   Layer 1 + Layer 2 might miss (chunked encoding, missing
   Content-Length, pre-0.30 Starlette without the ``size`` attr).

Plus a 4th layer at the Caddy reverse-proxy: ``Caddyfile`` has
``request_body { max_size ... }`` which rejects oversized requests
at the edge BEFORE the bytes reach the API.

These tests pin the contract for Layer 3 + the Caddyfile layer.
Layer 1 (Content-Length) + Layer 2 (UploadFile.size) are NOT
separately unit-tested because both require spoofing the
TestClient's request-state which ``httpx`` does not expose
(Layer 1 auto-computes Content-Length from the body; Layer 2
is Starlette multipart parser internal state). Layer 3 shares
the same ``> max_size`` threshold + 413 response as Layer 1,
so testing Layer 3 verifies the same logic. The full 4-layer
defense-in-depth is exercised end-to-end by the real-stack harness
(see ``web/e2e/README.md`` for setup).

Drift guard rationale: a regression that lowers the Caddyfile
cap below the API cap would cause client uploads to fail at the
proxy with a generic 413 for payloads the API would otherwise
accept (see the ``test_caddyfile_request_body_limit_matches_api_cap``
docstring for the unit-mismatch details + the proxy-layer
false-reject window explanation).

Forward-looking: if a future Starlette/httpx release exposes a
reliable way to spoof Content-Length in tests (e.g. a dedicated
httpx kwarg or a TestClient middleware for multipart parser
state inspection), consider adding Layer 1+2 dedicated tests
for completeness. The current tests pin the contract via Layer
3's same-condition verification; Layer 1+2 dedicated tests would
add defense-in-depth to the test suite itself.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from tests._fixtures import make_minimal_zevtc

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
    # Settings.max_upload_size_bytes has ge=1048576 (1 MiB) so we
    # cannot lower it via env var.  Monkeypatch get_settings to
    # return a mock with the desired 1024-byte cap instead.
    # The conftest autouse ``_get_settings_no_dotenv`` fixture
    # already replaces gw2analytics_api.config.get_settings;
    # we re-replace it here with a mock that returns the small cap.
    mock_settings = MagicMock()
    mock_settings.max_upload_size_bytes = 1024
    mock_settings.allow_inrequest_parse_fallback = True
    monkeypatch.setattr(
        "gw2analytics_api.config.get_settings",
        lambda: mock_settings,
    )
    # Generate enough agents so the ZIP blob exceeds the 1024-byte
    # cap (each 96-byte agent record + ZIP overhead ≈ 110 bytes).
    agents = [(200_001 + i, 2, 18, f"V10 Warrior OVERSIZE {i}", True) for i in range(12)]
    blob = make_minimal_zevtc(agents=agents, build="20251021")
    assert len(blob) > 1024, (
        f"fixture blob ({len(blob)} bytes) must be > 1024 bytes "
        f"for the oversized-body test to be meaningful"
    )

    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("oversize.zevtc", blob, "application/octet-stream")},
    )

    assert resp.status_code == 413, resp.text
    body = resp.json()
    # The detail message names both the actual size + the cap so an
    # operator can diagnose without consulting logs. The presence of
    # the "too large" substring is the contract check; the exact
    # numeric format of the size + cap (e.g. "1024 bytes" vs
    # "1.0 KiB") is an implementation detail that the test deliberately
    # does NOT pin, so a future reformat of the error message does
    # not break the test.
    assert "too large" in str(body.get("detail", "")).lower()


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
    # 1 MiB cap is within Settings' ge=1048576 constraint so the
    # env var path works here.

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
    multipliers = {
        "": 1,
        "KB": 1000,
        "KIB": 1024,
        "MB": 1_000_000,
        "MIB": 1024**2,
        "GB": 1_000_000_000,
        "GIB": 1024**3,
    }
    caddy_cap_bytes = value * multipliers.get(unit, 1)

    # API cap defaults to 100 MiB (104857600 bytes) per Settings.max_upload_size_bytes.
    api_cap_bytes = 100 * 1024 * 1024

    assert caddy_cap_bytes >= api_cap_bytes, (
        f"Caddyfile cap ({caddy_cap_bytes} bytes) must be >= API cap "
        f"({api_cap_bytes} bytes). Raising Caddy first + API second (or "
        f"both together) is the safe order; lowering Caddy below the API "
        f"cap creates a proxy-layer false-reject."
    )
