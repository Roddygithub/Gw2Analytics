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


@pytest.mark.parametrize(
    ("interval_change", "actor_change", "message"),
    [
        ({"agent_id": "missing"}, {}, "unknown agent_id"),
        ({"start_ms": 99}, {}, "exceeds agent awareness"),
        ({"end_ms": 1801}, {}, "exceeds agent awareness"),
        ({"owner_actor_id": "missing"}, {}, "unknown owner_actor_id"),
        ({}, {"first_aware_ms": 101}, "not aware at ownership start_ms"),
    ],
)
def test_v2_ownership_rejects_invalid_references_and_awareness(
    interval_change: dict[str, Any], actor_change: dict[str, Any], message: str
) -> None:
    payload = _fixture()
    interval = payload["fights"][0]["ownership_intervals"][0]
    interval.update(interval_change)
    if actor_change:
        payload["fights"][0]["actors"][0].update(actor_change)

    with pytest.raises(ValidationError, match=message):
        WvwExportV2.model_validate(payload)


def test_v2_ownership_intervals_must_be_canonically_ordered() -> None:
    payload = _fixture()
    fight = payload["fights"][0]
    first = dict(fight["ownership_intervals"][0])
    second = dict(
        first,
        agent_id="a000000",
        owner_actor_id=None,
        owner_resolution="unresolved",
        start_ms=50,
        end_ms=80,
    )
    fight["ownership_intervals"] = [first, second]
    fight["ownership_observation_count"] = 2

    with pytest.raises(ValidationError, match="ownership_intervals must be ordered"):
        WvwExportV2.model_validate(payload)


@pytest.mark.parametrize(
    ("fight_change", "message"),
    [
        ({"fight_id": "wrong"}, "fight_id must be"),
        ({"source_log_index": 1}, "outside source_log_count"),
    ],
)
def test_v2_fight_identity_must_be_canonical(fight_change: dict[str, Any], message: str) -> None:
    payload = _fixture()
    payload["fights"][0].update(fight_change)

    with pytest.raises(ValidationError, match=message):
        WvwExportV2.model_validate(payload)


def test_v2_fights_must_have_unique_ids_and_canonical_order() -> None:
    payload = _fixture()
    second = json.loads(json.dumps(payload["fights"][0]))
    payload["fights"].append(second)
    with pytest.raises(ValidationError, match="fight_id values must be unique"):
        WvwExportV2.model_validate(payload)

    second["segment_index"] = 1
    second["fight_id"] = "log-0000/fight-0001"
    payload["fights"] = [second, payload["fights"][0]]
    with pytest.raises(ValidationError, match="fights must be ordered"):
        WvwExportV2.model_validate(payload)


def test_v2_allows_multiple_segments_for_one_source_log() -> None:
    payload = _fixture()
    second = json.loads(json.dumps(payload["fights"][0]))
    second["segment_index"] = 1
    second["fight_id"] = "log-0000/fight-0001"
    payload["fights"].append(second)

    export = WvwExportV2.model_validate(payload)

    assert export.source_log_count == 1
    assert [fight.segment_index for fight in export.fights] == [0, 1]


def test_healing_events_require_availability_but_availability_can_be_empty() -> None:
    payload = _fixture()
    payload["fights"][0]["healing_available"] = False
    with pytest.raises(ValidationError, match="healing_available=true"):
        WvwExportV2.model_validate(payload)

    payload = _fixture()
    fight = payload["fights"][0]
    fight["events"] = [event for event in fight["events"] if event["kind"] != "healing"]
    for sequence, event in enumerate(fight["events"]):
        event["sequence"] = sequence
    assert WvwExportV2.model_validate(payload).fights[0].healing_available


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
