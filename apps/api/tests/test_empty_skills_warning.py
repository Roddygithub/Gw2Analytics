"""v0.10.2 hotfix followup #8: parser safety-bound graceful degradation.

Background
==========

The arcdps EVTC parser's skill table walker is **lenient**: if
the first skill record's ``name_len`` exceeds the safety bound
(``MAX_SKILL_NAME_BYTES = 4096``) OR the skill table is
truncated before the first record, the walker logs its own
WARNING and stops reading -- yielding 0 skills.

The parser computes ``actual_skill_count`` by walking the skill
table (NOT from the raw header byte). When the safety bound
fires, ``actual_skill_count = 0`` and ``cf.skills = []``.
``_save_fight`` receives this already-corrected count via
``head.skill_count``, so no additional services-layer warning
is needed -- the parser's own log is the operator signal.

What this test pins
===================

Two scenarios, both via the public ``POST /api/v1/uploads``
route + the real parser + the real FastAPI + the real DB:

1. **A zevtc with a 5000-char skill name** triggers the
   parser's ``MAX_SKILL_NAME_BYTES`` safety bound. The parser
   logs its own WARNING, yields 0 skills, and sets
   ``head.skill_count=0``. The upload completes gracefully
   (non-fatal degradation).

2. **A zevtc with no skills** (legitimate "no skills" fight)
   parses cleanly with 0 skills and no warnings.

The parser's WARNING is captured via pytest's ``caplog``
fixture to verify the safety-bound graceful degradation.
"""

from __future__ import annotations

import logging
import time
import uuid as _uuid

import pytest
from _fixtures import make_minimal_zevtc
from fastapi.testclient import TestClient

from gw2_evtc_parser.parser import logger as parser_logger
from gw2analytics_api.main import app

client: TestClient = TestClient(app)


def test_parser_safety_bound_graceful_degradation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """v0.10.2 hotfix followup #8: 5000-char skill name triggers parser safety bound.

    The 5000-char skill name exceeds ``MAX_SKILL_NAME_BYTES``
    (4096). The parser's ``_iter_skills`` logs its own WARNING
    and stops reading, yielding 0 skills. The parser computes
    ``actual_skill_count`` from the walk (NOT the raw header
    byte), so ``head.skill_count`` is already 0 when
    ``_save_fight`` receives it. The upload completes gracefully.
    """
    suffix = _uuid.uuid4().hex[:8]
    build = f"2025{suffix[:4]}" if len(suffix) >= 4 else "20250925"

    # A 5000-char skill name triggers the parser's
    # ``MAX_SKILL_NAME_BYTES`` safety bound.
    overlong_skill_name = "A" * 5_000
    blob = make_minimal_zevtc(
        agents=[(11111, 2, 18, f"Player {suffix}", True)],
        skills=[(12345, overlong_skill_name)],
        build=build,
    )

    with caplog.at_level(logging.WARNING, logger=parser_logger.name):
        resp = client.post(
            "/api/v1/uploads",
            files={"file": ("empty_skills.zevtc", blob, "application/octet-stream")},
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
        assert upload_resp.json()["status"] == "completed", (
            f"expected 'completed' (safety bound is non-fatal), "
            f"got {upload_resp.json()['status']!r}; "
            f"error_message: {upload_resp.json().get('error_message')!r}"
        )

    # Verify the parser's safety-bound WARNING was logged.
    # The parser logs "exceeding safety bound" when name_len
    # > MAX_SKILL_NAME_BYTES.
    safety_warnings = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING
        and r.name == parser_logger.name
        and "safety bound" in r.message
    ]
    assert len(safety_warnings) >= 1, (
        f"expected at least 1 parser WARNING with 'safety bound', got: "
        f"{[(r.name, r.levelname, r.message) for r in caplog.records]}"
    )


def test_no_warning_for_legitimate_zero_skills(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """v0.10.2 hotfix followup #8: a legitimate "no skills" fight has no warnings.

    A fight with ``skills=[]`` (no skill records in the EVTC
    body) parses cleanly: the parser yields 0 skills, no
    safety-bound WARNING fires, and the upload completes.
    """
    suffix = _uuid.uuid4().hex[:8]
    build = f"2025{suffix[:4]}" if len(suffix) >= 4 else "20250925"

    blob = make_minimal_zevtc(
        agents=[(11111, 2, 18, f"Player {suffix}", True)],
        skills=[],
        build=build,
    )

    with caplog.at_level(logging.WARNING, logger=parser_logger.name):
        resp = client.post(
            "/api/v1/uploads",
            files={"file": ("no_skills.zevtc", blob, "application/octet-stream")},
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
        assert upload_resp.json()["status"] == "completed", (
            f"expected 'completed', got {upload_resp.json()['status']!r}; "
            f"error_message: {upload_resp.json().get('error_message')!r}"
        )

    # Verify NO safety-bound WARNING was logged for a
    # legitimate zero-skills fight.
    false_positive_warnings = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING
        and r.name == parser_logger.name
        and "safety bound" in r.message
    ]
    assert len(false_positive_warnings) == 0, (
        f"expected NO parser WARNING for a skill_count=0 fight, "
        f"got {len(false_positive_warnings)}: "
        f"{[r.message for r in false_positive_warnings]}"
    )
