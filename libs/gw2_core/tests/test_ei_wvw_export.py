from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from gw2_core import WvwExportV1

_FIXTURE = Path(__file__).parent / "fixtures" / "wvw_export_v1.json"


def _payload() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(_FIXTURE.read_text(encoding="utf-8")))


def test_wvw_export_v1_fixture_and_explicit_missingness() -> None:
    export = WvwExportV1.model_validate(_payload())

    assert export.schema_version == 1
    assert export.fights[0].events[0].kind == "damage"
    assert export.fights[0].actors[0].account is None
    assert export.session_id is None
    assert export.fights[0].position_samples == []


def test_wvw_export_rejects_unknown_schema_version() -> None:
    payload = _payload()
    payload["schema_version"] = 2

    with pytest.raises(ValidationError, match="schema_version"):
        WvwExportV1.model_validate(payload)


def test_wvw_export_rejects_malformed_event_payload() -> None:
    payload = _payload()
    event = payload["fights"][0]["events"][0]
    event["damage"] = None

    with pytest.raises(ValidationError, match="damage events require damage"):
        WvwExportV1.model_validate(payload)


def test_wvw_export_accepts_buff_extension_events() -> None:
    payload = _payload()
    event = {
        "kind": "buff_extension",
        "sequence": 1,
        "time_ms": 600,
        "source_actor_id": "a000000",
        "target_actor_id": "a000001",
        "skill_id": 765,
        "damage": None,
        "shield_damage": None,
        "buff_id": 765,
        "buff_duration_ms": 250,
        "removed_stacks": None,
        "health_percent": None,
    }
    payload["fights"][0]["events"].append(event)

    export = WvwExportV1.model_validate(payload)

    assert export.fights[0].events[1].kind == "buff_extension"


def test_wvw_export_rejects_nondeterministic_event_order() -> None:
    payload = _payload()
    events = payload["fights"][0]["events"]
    later = dict(events[0], sequence=1, time_ms=600)
    events.extend([later, dict(events[0], sequence=2, time_ms=400)])

    with pytest.raises(ValidationError, match="ordered by time_ms"):
        WvwExportV1.model_validate(payload)


def test_wvw_export_requires_valid_owner_interval_shape() -> None:
    payload = _payload()
    payload["fights"][0]["ownership_intervals"][0]["end_ms"] = 100

    with pytest.raises(ValidationError, match="start_ms < end_ms"):
        WvwExportV1.model_validate(payload)


def test_wvw_export_rejects_unrecognized_fields() -> None:
    payload = _payload()
    payload["fights"][0]["events"][0]["ei_internal_object"] = {}

    with pytest.raises(ValidationError, match="ei_internal_object"):
        WvwExportV1.model_validate(payload)
