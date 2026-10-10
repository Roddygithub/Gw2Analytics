"""V2 export transport contract tests."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from gw2_core import WvwExportV1, WvwExportV2

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture() -> dict[str, Any]:
    payload = json.loads((FIXTURES / "wvw_export_v2.json").read_text())
    assert isinstance(payload, dict)
    return payload


def test_v2_fixture_validates_all_event_families_and_preserves_v1() -> None:
    payload = _fixture()
    export = WvwExportV2.model_validate(payload)

    assert export.schema_version == 2
    assert [event.kind for event in export.fights[0].events] == [
        "damage",
        "healing",
        "up",
        "cc",
        "buff_apply",
    ]
    assert (
        WvwExportV1.model_validate(
            json.loads((FIXTURES / "wvw_export_v1.json").read_text())
        ).schema_version
        == 1
    )


def test_v2_rejects_cross_kind_payload_fields() -> None:
    payload = _fixture()
    payload["fights"][0]["events"][1]["buff_id"] = 42

    with pytest.raises(ValidationError, match="extra_forbidden"):
        WvwExportV2.model_validate(payload)


def test_v2_rejects_instance_id_in_actor_contract() -> None:
    payload = _fixture()
    payload["fights"][0]["actors"][0]["instance_id"] = 123

    with pytest.raises(ValidationError, match="extra_forbidden"):
        WvwExportV2.model_validate(payload)


def test_v2_contiguous_sequence_is_required() -> None:
    payload = _fixture()
    payload["fights"][0]["events"][2]["sequence"] = 9

    with pytest.raises(ValidationError, match="contiguous"):
        WvwExportV2.model_validate(payload)


def test_event_tail_is_valid_with_separate_ei_recording_domain() -> None:
    payload = _fixture()
    payload["fights"][0]["events"][0]["time_ms"] = 2100
    payload["fights"][0]["events"] = sorted(
        payload["fights"][0]["events"], key=lambda event: event["time_ms"]
    )
    for index, event in enumerate(payload["fights"][0]["events"]):
        event["sequence"] = index

    validated = WvwExportV2.model_validate(payload)
    assert validated.fights[0].duration_ms == 2000
    assert validated.fights[0].events[-1].time_ms == 2100


def test_event_outside_recording_domain_is_rejected() -> None:
    payload = _fixture()
    payload["fights"][0]["events"][-1]["time_ms"] = 2201

    with pytest.raises(ValidationError, match="event_domain_end_ms"):
        WvwExportV2.model_validate(payload)


def test_event_domain_must_cover_active_fight() -> None:
    payload = _fixture()
    payload["fights"][0]["event_domain_end_ms"] = 1999

    with pytest.raises(ValidationError, match="cover the active fight"):
        WvwExportV2.model_validate(payload)


def test_unknown_event_actor_reference_is_rejected() -> None:
    payload = _fixture()
    payload["fights"][0]["events"][1]["target_actor_id"] = "missing"

    with pytest.raises(ValidationError, match="unknown actor_id"):
        WvwExportV2.model_validate(payload)


def test_v2_position_values_must_be_finite() -> None:
    payload = _fixture()
    payload["fights"][0]["position_samples"] = [
        {"actor_id": "a000000", "time_ms": 10, "x": math.inf, "y": 0, "z": 0}
    ]

    with pytest.raises(ValidationError):
        WvwExportV2.model_validate(payload)
