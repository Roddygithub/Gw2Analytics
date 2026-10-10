from __future__ import annotations

import hashlib
import json
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


def test_generated_v2_config_selects_only_v2_export(tmp_path: Path) -> None:
    config = TOOL["_config"](tmp_path, True, 2)

    assert "SaveOutWvwExport=true" not in config
    assert "SaveOutWvwExportV2=true" in config


def test_v2_event_inventory_uses_up_without_alive() -> None:
    assert "up" in TOOL["V2_KINDS"]
    assert "alive" not in TOOL["V2_KINDS"]


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


def test_repeat_export_bytes_reruns_and_reads_only_fresh_output(tmp_path: Path) -> None:
    (tmp_path / "log-one_wvw_export_v2.json").write_bytes(b"first")
    (tmp_path / "stale-witness").write_bytes(b"witness")

    def run() -> tuple[float, int]:
        assert not list(tmp_path.glob("log*_wvw_export_v2.json"))
        (tmp_path / "log-one_wvw_export_v2.json").write_bytes(b"first")
        return 1.5, 512

    second, wall_seconds, peak_rss_kib = TOOL["_repeat_export_bytes"](
        tmp_path, "log", "_wvw_export_v2.json", run
    )

    assert second == b"first"
    assert wall_seconds == 1.5
    assert peak_rss_kib == 512


def test_repeat_export_bytes_fails_when_second_run_writes_nothing(tmp_path: Path) -> None:
    (tmp_path / "log-one_wvw_export_v2.json").write_bytes(b"first")

    with pytest.raises(RuntimeError, match="no export output"):
        TOOL["_repeat_export_bytes"](tmp_path, "log", "_wvw_export_v2.json", lambda: (1.0, 0))


def test_repeat_export_bytes_fails_when_second_run_writes_multiple_outputs(tmp_path: Path) -> None:
    (tmp_path / "log-one_wvw_export_v2.json").write_bytes(b"first")

    def run() -> tuple[float, int]:
        (tmp_path / "log-one_wvw_export_v2.json").write_bytes(b"one")
        (tmp_path / "log-two_wvw_export_v2.json").write_bytes(b"two")
        return 1.0, 0

    with pytest.raises(RuntimeError, match="expected exactly one"):
        TOOL["_repeat_export_bytes"](tmp_path, "log", "_wvw_export_v2.json", run)


def test_repeat_export_bytes_requires_one_sidecar_before_rerun(tmp_path: Path) -> None:
    (tmp_path / "log-one_wvw_export_v2.json").write_bytes(b"first")
    (tmp_path / "log-two_wvw_export_v2.json").write_bytes(b"second")

    with pytest.raises(RuntimeError, match="before the repeat run"):
        TOOL["_repeat_export_bytes"](tmp_path, "log", "_wvw_export_v2.json", lambda: (1.0, 0))


def _fake_export_payload(schema_version: int) -> bytes:
    fixture = ROOT / f"libs/gw2_core/tests/fixtures/wvw_export_v{schema_version}.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    payload["parser_version"] = "3.26.0.0"
    return json.dumps(payload).encode()


def _fake_ei_script(tmp_path: Path, stem: str, schema_version: int, second_run: str) -> Path:
    export_name = f"{stem}_wvw_export_v{schema_version}.json"
    second: dict[str, list[str]] = {
        "none": [],
        "multi": [
            f'cp "$3" "$out/{export_name}"',
            f'cp "$3" "$out/{stem}-alt_wvw_export_v{schema_version}.json"',
        ],
        "differs": [
            f'cp "$3" "$out/{export_name}"',
            f'printf " " >> "$out/{export_name}"',
        ],
    }
    script = tmp_path / f"fake-ei-{second_run}-v{schema_version}.sh"
    body = [
        "#!/bin/sh",
        'dir=$(dirname "$2")',
        "out=$(sed -n 's/^OutLocation=//p' \"$2\")",
        'if [ -f "$dir/invocations" ]; then',
        *(f"  {line}" for line in second[second_run]),
        "else",
        '  touch "$dir/invocations"',
        f'  cp "$3" "$out/{export_name}"',
        "fi",
        "exit 0",
    ]
    script.write_text("\n".join(body) + "\n", encoding="utf-8")
    script.chmod(0o755)
    return script


def _run_fake_mode(tmp_path: Path, schema_version: int, second_run: str) -> dict[str, Any]:
    stem = "fake-cert-log"
    run_dir = tmp_path / f"run-{second_run}-v{schema_version}"
    run_dir.mkdir()
    log = run_dir / f"{stem}.zevtc"
    log.write_bytes(_fake_export_payload(schema_version))
    return TOOL["_run_mode"](
        [({"stem": stem}, log)],
        dotnet=Path("/bin/sh"),
        cli=_fake_ei_script(tmp_path, stem, schema_version, second_run),
        root_output=run_dir / "out",
        parse_replay=True,
        schema_version=schema_version,
    )


def test_run_mode_fails_when_repeat_run_produces_no_output(tmp_path: Path) -> None:
    mode = _run_fake_mode(tmp_path, 2, "none")

    assert mode["failures"] == [{"log": "fake-cert-log", "reason": "RuntimeError"}]
    assert mode["logs"] == []


def test_run_mode_fails_when_repeat_run_produces_multiple_outputs(tmp_path: Path) -> None:
    mode = _run_fake_mode(tmp_path, 2, "multi")

    assert mode["failures"] == [{"log": "fake-cert-log", "reason": "RuntimeError"}]
    assert mode["logs"] == []


def test_run_mode_reports_nondeterministic_repeat_from_different_second_bytes(
    tmp_path: Path,
) -> None:
    mode = _run_fake_mode(tmp_path, 2, "differs")

    assert mode["failures"] == [{"log": "fake-cert-log", "reason": "repeat_output_bytes_differ"}]
    row = mode["logs"][0]
    assert row["deterministic_repeat"] is False
    assert row["output_sha256"] != row["repeat_output_sha256"]
    assert mode["summary"]["deterministic_logs"] == 0


def test_v1_mode_also_requires_a_fresh_repeat_output(tmp_path: Path) -> None:
    mode = _run_fake_mode(tmp_path, 1, "none")

    assert mode["failures"] == [{"log": "fake-cert-log", "reason": "RuntimeError"}]
    assert mode["logs"] == []


def test_v2_transport_validation_captures_schema_failures() -> None:
    import json

    fixture = ROOT / "libs/gw2_core/tests/fixtures/wvw_export_v2.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    payload["fights"][0]["event_domain_end_ms"] = 1

    result = TOOL["_validation_result"](payload, 2)

    assert result["schema_valid"] is False
    assert result["validation_errors"]
    assert any("event_domain_end_ms" in error["message"] for error in result["validation_errors"])


def test_v2_summary_reports_family_amounts_without_identity_fields() -> None:
    import json

    fixture = ROOT / "libs/gw2_core/tests/fixtures/wvw_export_v2.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))

    summary = TOOL["_summarize"](payload, "fixture-log", 100, fixture.read_bytes(), 2)

    assert summary["events_by_kind"]["healing"] == 1
    assert summary["healing_amount_total"] == 75
    assert summary["events_by_kind"]["up"] == 1
    assert summary["events_by_kind"]["cc"] == 1
    assert summary["cc_duration_ms_total"] == 500
    assert summary["recording_end_ms"] == 2100
    assert summary["events_after_recording_end"] == 1
    assert "account" not in summary
    assert "character" not in summary
