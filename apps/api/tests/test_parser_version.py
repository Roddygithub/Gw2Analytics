"""v0.10.2 hotfix followup #6: ``upload.parser_version`` is stamped after a successful parse.

Background
==========

The ``Upload`` model has a ``parser_version`` column
(``String(64)``, default ``"0"``). The default ``"0"`` is a sentinel
that signals "not parsed yet" / "unknown parser version" (the
v0.10.x upload envelope exposes this column via the
``/api/v1/uploads/{id}`` route, so operators can see the value on
every upload).

Pre-v0.10.2 hotfix followup #6, the column stayed at ``"0"``
indefinitely -- even after a successful parse. Operators had no
way to correlate a ``completed`` row with the exact
``gw2_evtc_parser`` release that processed it, which made
post-mortem analysis of "this fight looks wrong, which parser
version produced it?" hard without a code grep.

v0.10.2 hotfix followup #6 stamps
``upload.parser_version = gw2_evtc_parser.__version__`` at the
end of :func:`process_parse` (right before the final commit), so
the column reflects the actual parser version that successfully
processed the upload. On failure, the sentinel stays (the
``failed`` branch in the except clauses short-circuits before
reaching the version stamp).

What this test pins
===================

A 1-fight zevtc POSTed through the real upload → parse → persist
pipeline lands with ``upload.parser_version`` set to the actual
``gw2_evtc_parser.__version__`` (imported dynamically so the
test survives future parser-version bumps).

The test also pins the "failed upload does NOT get a version
stamp" contract: a deliberately-broken zevtc (empty zip) that
fails to parse keeps ``parser_version = "0"`` (the sentinel).
This makes the sentinel semantics explicit: ``"0"`` means "not
successfully parsed", NOT "the parser is version 0".
"""

from __future__ import annotations

import io
import time
import uuid as _uuid
import zipfile

import pytest
from _fixtures import make_minimal_zevtc
from fastapi.testclient import TestClient

from gw2_evtc_parser import __version__ as PARSER_VERSION  # noqa: N812
from gw2analytics_api.main import app

client: TestClient = TestClient(app)


def test_parser_version_is_stamped_on_successful_parse() -> None:
    """A successful POST stamps ``upload.parser_version`` with the real parser version.

    Pre-v0.10.2 hotfix followup #6: the column stayed at the
    ``"0"`` sentinel indefinitely, even after a successful
    parse. Post-hotfix: the column reflects the actual
    ``gw2_evtc_parser.__version__`` (currently ``"0.5.0"``)
    imported dynamically so the test survives future
    parser-version bumps.
    """
    suffix = _uuid.uuid4().hex[:8]
    build = f"2025{suffix[:4]}" if len(suffix) >= 4 else "20250925"

    blob = make_minimal_zevtc(
        agents=[(11111, 2, 18, f"Player {suffix}", True)],
        skills=[(12345, f"SomeSkill {suffix}")],
        build=build,
    )

    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("parser_version.zevtc", blob, "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    upload_id = resp.json()["id"]

    # Poll for completion. 5s ceiling is generous: the parse
    # is milliseconds for a 1-agent/1-skill fixture. Pre-hotfix,
    # the upload would reach ``completed`` but the
    # ``parser_version`` would stay at the ``"0"`` sentinel.
    deadline = time.monotonic() + 5.0
    final_status = None
    final_parser_version = None
    while time.monotonic() < deadline:
        upload_resp = client.get(f"/api/v1/uploads/{upload_id}")
        assert upload_resp.status_code == 200
        body = upload_resp.json()
        if body["status"] in ("completed", "failed"):
            final_status = body["status"]
            final_parser_version = body["parser_version"]
            break
        time.sleep(0.1)
    else:
        pytest.fail(f"upload {upload_id} did not reach terminal status within 5s")

    assert final_status == "completed", (
        f"expected 'completed', got {final_status!r}; "
        f"error_message: {upload_resp.json().get('error_message')!r}"
    )

    # The core assertion: the parser version on the upload
    # envelope is the actual ``gw2_evtc_parser.__version__``,
    # NOT the ``"0"`` sentinel.
    assert final_parser_version == PARSER_VERSION, (
        f"expected parser_version={PARSER_VERSION!r} "
        f"(gw2_evtc_parser.__version__), got {final_parser_version!r}. "
        f"Pre-v0.10.2 hotfix followup #6, the column would be "
        f"the '0' sentinel even after a successful parse."
    )
    # Defensive: the sentinel must not appear on a successful
    # parse. This pins the semantic "0 = not successfully
    # parsed" (NOT "0 = the parser is version 0", which would
    # be ambiguous if a future gw2_evtc_parser ever released
    # a 0.0.x line).
    assert final_parser_version != "0", (
        f"parser_version should never be the '0' sentinel on a "
        f"successful parse; got {final_parser_version!r}"
    )


def test_parser_version_stays_at_sentinel_on_failed_parse() -> None:
    """A failed POST (empty zip) does NOT get a version stamp.

    Pins the contract: ``"0"`` means "not successfully
    parsed", NOT "the parser is version 0". A failed upload
    (the parser raises ``EvtcParseError`` before any
    ORM-side state is touched) keeps the sentinel, so an
    operator can grep ``parser_version = '0'`` to find
    every upload that needs a manual re-parse or operator
    intervention.
    """
    # An empty zip triggers the ``zevtc has no entries``
    # branch in the parser (see
    # ``parser.py::_first_entry``). The parser raises
    # ``EvtcParseError`` and the upload flips to
    # ``status="failed"``.

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        # Write a single entry that is an empty file so the
        # zip is structurally valid but the inner EVTC has
        # fewer than HEADER_SIZE (25) bytes. The parser
        # raises ``EVTC blob is N bytes, header needs 25``.
        zf.writestr("fight.evtc", b"")

    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("broken.zevtc", buf.getvalue(), "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    upload_id = resp.json()["id"]

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        upload_resp = client.get(f"/api/v1/uploads/{upload_id}")
        assert upload_resp.status_code == 200
        if upload_resp.json()["status"] in ("completed", "failed"):
            break
        time.sleep(0.1)
    else:
        pytest.fail(f"upload {upload_id} did not reach terminal status within 5s")

    body = upload_resp.json()
    assert body["status"] == "failed", (
        f"expected 'failed' for a broken zevtc, got {body['status']!r}"
    )
    # The core assertion: parser_version stays at the
    # sentinel on a failed parse. Pre-hotfix, this is the
    # default; post-hotfix, this is also the default (the
    # ``failed`` branch short-circuits before the version
    # stamp). The test pins that the version stamp is
    # ONLY applied on the success path.
    assert body["parser_version"] == "0", (
        f"expected parser_version='0' (sentinel) on a failed parse, "
        f"got {body['parser_version']!r}. The version stamp must only "
        f"land on the success path."
    )
    # Defensive: the error_message is set (not None) so an
    # operator can grep the failure mode.
    assert body["error_message"] is not None
    assert len(body["error_message"]) > 0
