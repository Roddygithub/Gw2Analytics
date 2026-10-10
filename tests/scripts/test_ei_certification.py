from __future__ import annotations

import hashlib
import runpy
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL: dict[str, Any] = runpy.run_path(str(ROOT / "scripts/ei-certification/certify_wvw_export.py"))


def test_manifest_resolution_checks_all_35_hashes_and_unique_files(tmp_path: Path) -> None:
    entries = []
    for index in range(35):
        stem = f"fixture-{index:02d}"
        payload = f"private-log-{index}".encode()
        (tmp_path / f"{stem}.zevtc").write_bytes(payload)
        entries.append({"stem": stem, "evtc_sha256": hashlib.sha256(payload).hexdigest()})

    resolved = TOOL["_find_logs"]({"entries": entries}, tmp_path)

    assert len(resolved) == 35

    (tmp_path / "fixture-00.zevtc").write_bytes(b"modified")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        TOOL["_find_logs"]({"entries": entries}, tmp_path)


def test_generated_ei_config_enables_replay_and_wvw_export(tmp_path: Path) -> None:
    config = TOOL["_config"](tmp_path, True)

    assert "SaveOutWvwExport=true" in config
    assert "ParseCombatReplay=true" in config
    assert "DetailledWvW=true" in config
    assert "SaveAtOut=false" in config
    assert "UploadToDPSReports=false" in config


def test_summary_contains_only_aggregate_actor_free_fields() -> None:
    from gw2_core import WvwExportV1

    fixture = ROOT / "libs/gw2_core/tests/fixtures/wvw_export_v1.json"
    export = WvwExportV1.model_validate_json(fixture.read_bytes())
    output = fixture.read_bytes()

    summary = TOOL["_summarize"](export.model_dump(), "fixture-log", 100, output)

    assert summary["log"] == "fixture-log"
    assert summary["actors"] == len(export.fights[0].actors)
    assert "account" not in summary
    assert "character" not in summary
    assert sum(summary["events_by_kind"].values()) == summary["events"]


def test_invalid_export_is_reported_as_schema_invalid() -> None:
    import json

    fixture = ROOT / "libs/gw2_core/tests/fixtures/wvw_export_v1.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    payload["fights"][0]["events"][0]["time_ms"] = 3_000

    result = TOOL["_validation_result"](payload)

    assert result["schema_valid"] is False
    assert result["validation_errors"][0]["type"] == "value_error"
    assert "exceeds fight duration" in result["validation_errors"][0]["message"]


def test_different_repeat_bytes_are_reported_as_nondeterministic() -> None:
    comparison = TOOL["_compare_export_bytes"](b"first", b"second")

    assert comparison["deterministic_repeat"] is False
    assert comparison["output_sha256"] != comparison["repeat_output_sha256"]
