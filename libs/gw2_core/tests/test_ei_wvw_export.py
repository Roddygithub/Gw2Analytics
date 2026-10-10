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


def _validate_event(event: dict[str, Any]) -> None:
    payload = _payload()
    payload["fights"][0]["events"] = [event]
    WvwExportV1.model_validate(payload)


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


@pytest.mark.parametrize(
    "event",
    [
        {
            "kind": "damage",
            "sequence": 0,
            "time_ms": 100,
            "source_actor_id": "a000000",
            "target_actor_id": "a000001",
            "skill_id": 42,
            "damage": 100,
            "shield_damage": 0,
        },
        {
            "kind": "buff_apply",
            "sequence": 0,
            "time_ms": 100,
            "source_actor_id": "a000000",
            "target_actor_id": "a000001",
            "buff_id": 7,
            "duration_ms": 500,
        },
        {
            "kind": "buff_extension",
            "sequence": 0,
            "time_ms": 100,
            "source_actor_id": "a000000",
            "target_actor_id": "a000001",
            "buff_id": 7,
            "duration_ms": 250,
        },
        {
            "kind": "buff_remove_all",
            "sequence": 0,
            "time_ms": 100,
            "source_actor_id": "a000000",
            "target_actor_id": "a000001",
            "buff_id": 7,
            "duration_ms": 500,
            "removed_stacks": 3,
        },
        {
            "kind": "buff_remove_single",
            "sequence": 0,
            "time_ms": 100,
            "source_actor_id": "a000000",
            "target_actor_id": "a000001",
            "buff_id": 7,
            "duration_ms": 500,
            "removed_stacks": 1,
        },
        {
            "kind": "buff_remove_manual",
            "sequence": 0,
            "time_ms": 100,
            "source_actor_id": "a000000",
            "target_actor_id": "a000001",
            "buff_id": 7,
            "duration_ms": 500,
            "removed_stacks": 1,
        },
        *[
            {
                "kind": kind,
                "sequence": 0,
                "time_ms": 100,
                "target_actor_id": "a000001",
            }
            for kind in ("down", "death", "alive", "spawn", "despawn")
        ],
        {
            "kind": "health_update",
            "sequence": 0,
            "time_ms": 100,
            "target_actor_id": "a000001",
            "health_percent": 55.5,
        },
    ],
)
def test_wvw_export_accepts_each_discriminated_event_variant(event: dict[str, Any]) -> None:
    _validate_event(event)


def test_wvw_export_rejects_cross_kind_payload_fields() -> None:
    payload = _payload()
    payload["fights"][0]["events"][0]["buff_id"] = 7

    with pytest.raises(ValidationError, match="buff_id"):
        WvwExportV1.model_validate(payload)


def test_signed_ei_buff_and_skill_ids_are_preserved() -> None:
    payload = _payload()
    payload["fights"][0]["events"][0]["skill_id"] = -25

    export = WvwExportV1.model_validate(payload)

    assert export.fights[0].events[0].model_dump()["skill_id"] == -25


def test_event_sequence_must_be_zero_based_and_contiguous() -> None:
    payload = _payload()
    second = dict(payload["fights"][0]["events"][0], sequence=1, time_ms=600)
    payload["fights"][0]["events"].append(second)
    assert len(WvwExportV1.model_validate(payload).fights[0].events) == 2

    payload["fights"][0]["events"][1]["sequence"] = 2
    with pytest.raises(ValidationError, match="contiguous from zero"):
        WvwExportV1.model_validate(payload)


@pytest.mark.parametrize("coordinate", ["x", "y", "z"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_position_coordinates_must_be_finite(coordinate: str, value: float) -> None:
    payload = _payload()
    payload["fights"][0]["position_samples"] = [
        {"actor_id": "a000000", "time_ms": 1, "x": 0, "y": 0, "z": 0}
    ]
    payload["fights"][0]["position_samples"][0][coordinate] = value

    with pytest.raises(ValidationError):
        WvwExportV1.model_validate(payload)


def test_positions_use_full_canonical_order_for_equal_time_actor() -> None:
    payload = _payload()
    payload["fights"][0]["position_samples"] = [
        {"actor_id": "a000000", "time_ms": 1, "x": 2, "y": 0, "z": 0},
        {"actor_id": "a000000", "time_ms": 1, "x": 1, "y": 0, "z": 0},
    ]

    with pytest.raises(ValidationError, match="time, actor, x, y, z"):
        WvwExportV1.model_validate(payload)

    payload["fights"][0]["position_samples"].reverse()
    WvwExportV1.model_validate(payload)


def test_unresolved_observed_owner_is_distinct_from_no_interval() -> None:
    payload = _payload()
    interval = payload["fights"][0]["ownership_intervals"][0]
    interval["owner_actor_id"] = None
    interval["owner_resolution"] = "unresolved"

    export = WvwExportV1.model_validate(payload)

    assert export.fights[0].ownership_intervals[0].owner_resolution == "unresolved"


def test_owner_must_be_aware_at_observation_start_not_interval_end() -> None:
    payload = _payload()
    payload["fights"][0]["actors"][0]["last_aware_ms"] = 700

    WvwExportV1.model_validate(payload)

    payload["fights"][0]["ownership_intervals"][0]["start_ms"] = 701
    with pytest.raises(ValidationError, match="not aware at ownership start_ms"):
        WvwExportV1.model_validate(payload)


def test_ownership_interval_must_fit_minion_awareness() -> None:
    payload = _payload()
    payload["fights"][0]["ownership_intervals"][0]["end_ms"] = 1801

    with pytest.raises(ValidationError, match="exceeds agent awareness"):
        WvwExportV1.model_validate(payload)


def test_wvw_export_rejects_unrecognized_fields() -> None:
    payload = _payload()
    payload["fights"][0]["events"][0]["ei_internal_object"] = {}

    with pytest.raises(ValidationError, match="ei_internal_object"):
        WvwExportV1.model_validate(payload)
