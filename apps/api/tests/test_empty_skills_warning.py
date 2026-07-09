"""v0.10.2 hotfix followup #8: defensive WARNING when cf.skills is empty.

Background
==========

The arcdps EVTC parser's skill table walker is **lenient**: if
the first skill record's ``name_len`` exceeds the safety bound
(``MAX_SKILL_NAME_BYTES = 4096``) OR the skill table is
truncated before the first record, the walker logs its own
WARNING and stops reading -- yielding 0 skills even though the
header claimed ``skill_count > 0``.

Pre-v0.10.2 hotfix followup #8, the ``_save_fight`` write path
silently persisted 0 ``OrmFightSkill`` rows and the upload
flipped to ``status="completed"`` with no operator-visible
signal. The events blob may still reference ``skill_id``
integers that don't have a name in the ``fight_skills`` table
(the routes degrade gracefully -- the ``/fights/{id}/events``
route surfaces the events as raw ``skill_id`` integers, and
the SkillUsageTable component shows the id without a name --
but the missing-name state is silent).

v0.10.2 hotfix followup #8 adds a ``logger.warning(...)`` in
``_save_fight`` when ``head.skill_count > 0 and not cf.skills``.
The WARNING is non-fatal (the upload still completes), but it
makes the silent parser misread visible to operators
monitoring the parser logs. This mirrors the #4 followup's
"0-summary on non-empty source_map" WARNING.

(Module docstring compressed to fit the 100-char E501 line
limit; the full background lives in this expanded block.)

What this test pins
===================

Two scenarios, both via the public ``POST /api/v1/uploads``
route + the real parser + the real FastAPI + the real DB:

1. **A zevtc with a 5000-char skill name** triggers the
   parser's ``MAX_SKILL_NAME_BYTES`` safety bound on the
   first skill record, the parser yields 0 skills, and the
   services layer logs the new WARNING.

2. **A zevtc with ``skill_count=0`` in the header** (a
   legitimate "no skills" fight -- e.g. an NPC-only fight
   with no skill data) does NOT log the WARNING. The check
   is gated on ``head.skill_count > 0`` to avoid the false
   positive.

The WARNING is captured via pytest's ``caplog`` fixture (the
established pattern for asserting on log output in this
codebase; see ``test_dedup_skills.py`` for a precedent).
"""

from __future__ import annotations

import logging
import time
import uuid as _uuid

import pytest
from _fixtures import make_minimal_zevtc
from fastapi.testclient import TestClient

from gw2analytics_api.main import app
from gw2analytics_api.services import logger as services_logger

client: TestClient = TestClient(app)


def test_warning_fires_when_header_claims_skills_but_parser_yields_zero(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """v0.10.2 hotfix followup #8: header claims skill_count > 0 but parser yields 0 -> WARNING.

    The 5000-char skill name exceeds ``MAX_SKILL_NAME_BYTES``
    (4096) on the first skill record. The parser's
    ``_iter_skills`` logs its own WARNING and stops reading,
    yielding 0 skills. The header still claims
    ``skill_count=1``, so the new services.py WARNING fires.
    """
    suffix = _uuid.uuid4().hex[:8]
    build = f"2025{suffix[:4]}" if len(suffix) >= 4 else "20250925"

    # A 5000-char skill name triggers the parser's
    # ``MAX_SKILL_NAME_BYTES`` safety bound. The parser
    # logs its own WARNING and stops reading, yielding 0
    # skills. The header still claims ``skill_count=1``.
    overlong_skill_name = "A" * 5_000
    blob = make_minimal_zevtc(
        agents=[(11111, 2, 18, f"Player {suffix}", True)],
        skills=[(12345, overlong_skill_name)],
        build=build,
    )

    with caplog.at_level(logging.WARNING, logger=services_logger.name):
        resp = client.post(
            "/api/v1/uploads",
            files={"file": ("empty_skills.zevtc", blob, "application/octet-stream")},
        )
        assert resp.status_code == 201, resp.text
        upload_id = resp.json()["id"]

        # Wait for completion. 5s ceiling is generous: the
        # parse is milliseconds for a 1-agent/1-skill fixture.
        # The upload MUST reach ``completed`` (the WARNING is
        # non-fatal; the truncation is best-effort graceful
        # degradation).
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
            f"expected 'completed' (the WARNING is non-fatal), "
            f"got {upload_resp.json()['status']!r}; "
            f"error_message: {upload_resp.json().get('error_message')!r}"
        )

    # Verify the new services.py WARNING was logged. The
    # exact message is checked for the "skill_count" +
    # "0 skills" markers so a future regression that
    # changes the WARNING text (e.g. removes the
    # "skill_count" anchor) fires this test.
    warning_records = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING
        and r.name == services_logger.name
        and "skill_count" in r.message
        and "0 skills" in r.message
    ]
    assert len(warning_records) >= 1, (
        f"expected at least 1 services.py WARNING matching "
        f"'skill_count' + '0 skills', got: "
        f"{[(r.name, r.levelname, r.message) for r in caplog.records]}"
    )


def test_no_warning_when_skill_count_is_zero(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """v0.10.2 hotfix followup #8: a legitimate "no skills" fight does NOT log the WARNING.

    Pins the check's ``head.skill_count > 0`` guard: a fight
    whose header declares ``skill_count=0`` (e.g. an NPC-only
    fight with no skill data) is a legitimate "no skills"
    fight, NOT a parser misread. The WARNING must NOT fire
    in this case (false positive would be noisy in
    monitoring).
    """
    suffix = _uuid.uuid4().hex[:8]
    build = f"2025{suffix[:4]}" if len(suffix) >= 4 else "20250925"

    # ``skills=[]`` -> header has ``skill_count=0``. The
    # parser yields 0 skills (legitimate). The services
    # layer must NOT log the WARNING.
    blob = make_minimal_zevtc(
        agents=[(11111, 2, 18, f"Player {suffix}", True)],
        skills=[],
        build=build,
    )

    with caplog.at_level(logging.WARNING, logger=services_logger.name):
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

    # Verify the new WARNING was NOT logged (the
    # ``head.skill_count > 0`` guard prevents the false
    # positive).
    false_positive_warnings = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING
        and r.name == services_logger.name
        and "skill_count" in r.message
        and "0 skills" in r.message
    ]
    assert len(false_positive_warnings) == 0, (
        f"expected NO services.py WARNING for a skill_count=0 fight, "
        f"got {len(false_positive_warnings)}: "
        f"{[r.message for r in false_positive_warnings]}"
    )
