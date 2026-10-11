"""Process-boundary tests for the bounded EI V2 process adapter.

The tests drive a fake EI executable (a small ``/bin/sh`` script, the
same technique as ``test_ei_certification.py``) so they never need the
private 35-log corpus, a real Elite Insights build, or a database. The
fake receives the adapter's argv — ``-c <config> <log>`` — copies the
input log bytes as the V2 export sidecar, and can simulate exit
failures, timeouts, missing and multiple outputs. Payloads come from
the committed V2 contract fixture.
"""

from __future__ import annotations

import concurrent.futures
import json
import math
from pathlib import Path

import pytest

from gw2_core import WvwExportV2
from gw2analytics_api.services.ei_v2_process_adapter import (
    CERTIFIED_EI_PARSER_VERSION,
    EiProcessAmbiguousOutputError,
    EiProcessConfigError,
    EiProcessContractError,
    EiProcessExitError,
    EiProcessMissingOutputError,
    EiProcessOutputFormatError,
    EiProcessTimeoutError,
    EiProcessVersionError,
    EiProcessWorkspaceError,
    EiV2ExportResult,
    EiV2ProcessAdapter,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "libs/gw2_core/tests/fixtures/wvw_export_v2.json"

_LOG_NAME = "demo.zevtc"


def _certified_payload() -> bytes:
    """Fixture payload stamped with the certified EI parser version."""
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["parser_version"] = CERTIFIED_EI_PARSER_VERSION
    return json.dumps(payload).encode()


def _fake_ei(tmp_path: Path, behavior: str, sentinel: Path | None = None) -> Path:
    """Write a fake EI executable that receives ``-c <config> <log>`` as $1..$3."""
    script = tmp_path / f"fake-ei-{behavior}.sh"
    lines = ["#!/bin/sh", "out=$(sed -n 's/^OutLocation=//p' \"$2\")", 'base=$(basename "$3")']
    if behavior == "ok":
        lines.append('cp "$3" "$out/${base%.*}_wvw_export_v2.json"')
        if sentinel is not None:
            lines.append(f'echo "$out" >> "{sentinel}"')
    elif behavior == "locked":
        lines.append('cp "$3" "$out/${base%.*}_wvw_export_v2.json"')
        lines.append('chmod 000 "$out/${base%.*}_wvw_export_v2.json"')
    elif behavior == "multi":
        lines.append('cp "$3" "$out/${base%.*}_wvw_export_v2.json"')
        lines.append('cp "$3" "$out/${base%.*}-alt_wvw_export_v2.json"')
    elif behavior == "exit":
        lines += ['echo "ei-stdout-marker"', 'echo "ei-stderr-marker" >&2', "exit 7"]
    elif behavior == "bigexit":
        lines += ["yes | head -c 4096", "echo tail-end-marker", "exit 1"]
    elif behavior == "sleep":
        lines.append("sleep 30")
    elif behavior == "none":
        pass
    else:
        raise ValueError(behavior)
    lines.append("exit 0")
    script.write_text("\n".join(lines) + "\n", encoding="utf-8")
    script.chmod(0o755)
    return script


def _workspace_root(tmp_path: Path) -> Path:
    root = tmp_path / "work"
    root.mkdir(exist_ok=True)
    return root


def _log_file(tmp_path: Path, payload: bytes) -> Path:
    log_dir = tmp_path / "logs"
    log_dir.mkdir(exist_ok=True)
    log = log_dir / _LOG_NAME
    log.write_bytes(payload)
    return log


def _adapter(script: Path, tmp_path: Path, **kwargs: object) -> EiV2ProcessAdapter:
    return EiV2ProcessAdapter(
        ei_command=("/bin/sh", str(script)),
        workspace_root=_workspace_root(tmp_path),
        **kwargs,  # type: ignore[arg-type]
    )


def _assert_workspace_clean(root: Path) -> None:
    assert not any(root.iterdir()), "invocation workspaces must not outlive the call"


def test_export_returns_validated_v2_document_and_cleans_workspace(tmp_path: Path) -> None:
    adapter = _adapter(_fake_ei(tmp_path, "ok"), tmp_path)
    log = _log_file(tmp_path, _certified_payload())

    result = adapter.export(log)

    assert isinstance(result, EiV2ExportResult)
    assert isinstance(result.export, WvwExportV2)
    assert result.export.schema_version == 2
    assert result.export.fights[0].duration_ms == 2000
    assert result.export.parser_version == CERTIFIED_EI_PARSER_VERSION
    assert result.source_log == log.resolve()
    assert result.elapsed_seconds >= 0
    assert result.ei_command[0] == "/bin/sh"
    assert log.is_file(), "the input log must never be deleted"
    _assert_workspace_clean(_workspace_root(tmp_path))


def test_export_rejects_unexpected_parser_version(tmp_path: Path) -> None:
    adapter = _adapter(_fake_ei(tmp_path, "ok"), tmp_path)
    log = _log_file(tmp_path, FIXTURE.read_bytes())

    with pytest.raises(EiProcessVersionError) as excinfo:
        adapter.export(log)

    error = excinfo.value
    assert error.expected_parser_version == CERTIFIED_EI_PARSER_VERSION
    assert error.actual_parser_version == "3.26.0.0-prototype"
    assert log.is_file()
    _assert_workspace_clean(_workspace_root(tmp_path))


def test_expected_parser_version_is_explicit_and_configurable(tmp_path: Path) -> None:
    adapter = EiV2ProcessAdapter(
        ei_command=("/bin/sh", str(_fake_ei(tmp_path, "ok"))),
        workspace_root=_workspace_root(tmp_path),
        expected_parser_version="3.26.0.0-prototype",
    )
    log = _log_file(tmp_path, FIXTURE.read_bytes())

    result = adapter.export(log)

    assert result.export.parser_version == "3.26.0.0-prototype"


def test_empty_expected_parser_version_is_a_configuration_error(tmp_path: Path) -> None:
    with pytest.raises(EiProcessConfigError, match="expected_parser_version"):
        EiV2ProcessAdapter(
            ei_command=("sh", str(_fake_ei(tmp_path, "ok"))),
            expected_parser_version="",
        )


def test_program_resolved_from_path_is_accepted(tmp_path: Path) -> None:
    adapter = EiV2ProcessAdapter(
        ei_command=("sh", str(_fake_ei(tmp_path, "ok"))),
        workspace_root=_workspace_root(tmp_path),
    )
    log = _log_file(tmp_path, _certified_payload())

    result = adapter.export(log)

    assert result.export.schema_version == 2


def test_missing_executable_is_a_configuration_error(tmp_path: Path) -> None:
    with pytest.raises(EiProcessConfigError, match="does not exist"):
        EiV2ProcessAdapter(ei_command=(str(tmp_path / "missing-ei"),))


def test_program_not_on_path_is_a_configuration_error(tmp_path: Path) -> None:
    with pytest.raises(EiProcessConfigError, match="not found on PATH"):
        EiV2ProcessAdapter(ei_command=("definitely-not-a-real-ei-program-xyz",))


def test_non_executable_program_is_a_configuration_error(tmp_path: Path) -> None:
    program = tmp_path / "ei-not-executable"
    program.write_text("#!/bin/sh\n", encoding="utf-8")

    with pytest.raises(EiProcessConfigError, match="not executable"):
        EiV2ProcessAdapter(ei_command=(str(program),))


@pytest.mark.parametrize("bad_command", [(), ("", "x"), ("sh", ""), ("ei", None)])
def test_malformed_ei_command_is_a_configuration_error(bad_command: object) -> None:
    with pytest.raises(EiProcessConfigError):
        EiV2ProcessAdapter(ei_command=bad_command)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_timeout", [-1, 0, math.inf, -math.inf, math.nan])
def test_non_finite_or_non_positive_timeout_is_a_configuration_error(
    bad_timeout: float,
) -> None:
    with pytest.raises(EiProcessConfigError, match="positive finite"):
        EiV2ProcessAdapter(ei_command=("sh", "ei"), timeout_seconds=bad_timeout)


def test_missing_workspace_root_is_a_configuration_error(tmp_path: Path) -> None:
    with pytest.raises(EiProcessConfigError, match="workspace_root"):
        EiV2ProcessAdapter(
            ei_command=("sh", "ei"),
            workspace_root=tmp_path / "does-not-exist",
        )


def test_missing_input_log_is_a_configuration_error(tmp_path: Path) -> None:
    adapter = _adapter(_fake_ei(tmp_path, "ok"), tmp_path)

    with pytest.raises(EiProcessConfigError, match="input log"):
        adapter.export(tmp_path / "logs" / "missing.zevtc")

    _assert_workspace_clean(_workspace_root(tmp_path))


def test_directory_as_input_log_is_a_configuration_error(tmp_path: Path) -> None:
    adapter = _adapter(_fake_ei(tmp_path, "ok"), tmp_path)
    log_dir = tmp_path / "logs"
    log_dir.mkdir(exist_ok=True)

    with pytest.raises(EiProcessConfigError, match="input log"):
        adapter.export(log_dir)


def test_non_zero_exit_surfaces_code_and_bounded_output_tails(tmp_path: Path) -> None:
    adapter = _adapter(_fake_ei(tmp_path, "exit"), tmp_path)
    log = _log_file(tmp_path, FIXTURE.read_bytes())

    with pytest.raises(EiProcessExitError) as excinfo:
        adapter.export(log)

    error = excinfo.value
    assert error.returncode == 7
    assert "ei-stdout-marker" in error.stdout_tail
    assert "ei-stderr-marker" in error.stderr_tail
    assert error.elapsed_seconds >= 0
    _assert_workspace_clean(_workspace_root(tmp_path))
    assert log.is_file()


def test_captured_process_output_is_truncated_to_a_bounded_tail(tmp_path: Path) -> None:
    adapter = _adapter(_fake_ei(tmp_path, "bigexit"), tmp_path)
    log = _log_file(tmp_path, FIXTURE.read_bytes())

    with pytest.raises(EiProcessExitError) as excinfo:
        adapter.export(log)

    error = excinfo.value
    assert len(error.stdout_tail.encode("utf-8")) == 2048
    assert error.stdout_tail.endswith("tail-end-marker\n")


def test_timeout_terminates_the_invocation_and_reports_it(tmp_path: Path) -> None:
    adapter = _adapter(_fake_ei(tmp_path, "sleep"), tmp_path, timeout_seconds=0.5)
    log = _log_file(tmp_path, FIXTURE.read_bytes())

    with pytest.raises(EiProcessTimeoutError) as excinfo:
        adapter.export(log)

    error = excinfo.value
    assert error.timeout_seconds == 0.5
    assert error.elapsed_seconds >= 0.5
    _assert_workspace_clean(_workspace_root(tmp_path))


def test_missing_v2_output_is_reported(tmp_path: Path) -> None:
    adapter = _adapter(_fake_ei(tmp_path, "none"), tmp_path)
    log = _log_file(tmp_path, FIXTURE.read_bytes())

    with pytest.raises(EiProcessMissingOutputError):
        adapter.export(log)

    _assert_workspace_clean(_workspace_root(tmp_path))


def test_multiple_v2_outputs_are_rejected(tmp_path: Path) -> None:
    adapter = _adapter(_fake_ei(tmp_path, "multi"), tmp_path)
    log = _log_file(tmp_path, FIXTURE.read_bytes())

    with pytest.raises(EiProcessAmbiguousOutputError, match="2"):
        adapter.export(log)

    _assert_workspace_clean(_workspace_root(tmp_path))


def test_stale_outputs_cannot_create_a_false_success(tmp_path: Path) -> None:
    # A stale sidecar sits directly in the workspace root (a sibling of the
    # isolated per-invocation workspace) and another sits next to the input
    # log; the fake EI produces no output, and the adapter must reject the
    # invocation instead of consuming either stale file.
    root = _workspace_root(tmp_path)
    (root / "stale_wvw_export_v2.json").write_bytes(FIXTURE.read_bytes())
    log = _log_file(tmp_path, FIXTURE.read_bytes())
    (log.parent / f"{log.stem}_wvw_export_v2.json").write_bytes(FIXTURE.read_bytes())
    adapter = _adapter(_fake_ei(tmp_path, "none"), tmp_path)

    with pytest.raises(EiProcessMissingOutputError):
        adapter.export(log)

    assert (log.parent / f"{log.stem}_wvw_export_v2.json").is_file(), "sidecars stay untouched"
    assert (root / "stale_wvw_export_v2.json").is_file()
    assert [path.name for path in root.iterdir()] == ["stale_wvw_export_v2.json"]


def test_malformed_export_json_is_a_format_error(tmp_path: Path) -> None:
    adapter = _adapter(_fake_ei(tmp_path, "ok"), tmp_path)
    log = _log_file(tmp_path, b"{ this is not valid json")

    with pytest.raises(EiProcessOutputFormatError) as excinfo:
        adapter.export(log)

    assert isinstance(excinfo.value.__cause__, json.JSONDecodeError)
    _assert_workspace_clean(_workspace_root(tmp_path))


def test_config_write_failure_is_a_typed_workspace_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = _fake_ei(tmp_path, "ok")
    log = _log_file(tmp_path, _certified_payload())

    def _raise_os_error(*args: object, **kwargs: object) -> None:
        raise OSError("simulated disk failure")

    monkeypatch.setattr(Path, "write_text", _raise_os_error)
    adapter = _adapter(script, tmp_path)

    with pytest.raises(EiProcessWorkspaceError, match="could not write"):
        adapter.export(log)

    _assert_workspace_clean(_workspace_root(tmp_path))


def test_unreadable_export_is_a_typed_workspace_error(tmp_path: Path) -> None:
    adapter = _adapter(_fake_ei(tmp_path, "locked"), tmp_path)
    log = _log_file(tmp_path, _certified_payload())

    with pytest.raises(EiProcessWorkspaceError, match="could not read"):
        adapter.export(log)

    _assert_workspace_clean(_workspace_root(tmp_path))


def test_contract_invalid_export_is_a_contract_error(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["fights"][0]["event_domain_end_ms"] = 1
    adapter = _adapter(_fake_ei(tmp_path, "ok"), tmp_path)
    log = _log_file(tmp_path, json.dumps(payload).encode())

    with pytest.raises(EiProcessContractError) as excinfo:
        adapter.export(log)

    error = excinfo.value
    assert error.field_errors, "contract field errors must be surfaced for diagnosis"
    assert any("event_domain_end_ms" in message for _, message in error.field_errors)
    assert "violates the certified WvwExportV2 contract" in str(error)
    _assert_workspace_clean(_workspace_root(tmp_path))


def test_concurrent_invocations_use_distinct_workspaces(tmp_path: Path) -> None:
    sentinel = tmp_path / "workspaces.log"
    adapter = EiV2ProcessAdapter(
        ei_command=("/bin/sh", str(_fake_ei(tmp_path, "ok", sentinel=sentinel))),
        workspace_root=_workspace_root(tmp_path),
    )
    log = _log_file(tmp_path, _certified_payload())

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: adapter.export(log), range(4)))

    assert all(result.export.schema_version == 2 for result in results)
    workspaces = {line for line in sentinel.read_text(encoding="utf-8").splitlines() if line}
    assert len(workspaces) == 4, "each invocation must own a distinct isolated workspace"
    assert all(Path(workspace).parent == _workspace_root(tmp_path) for workspace in workspaces)
    _assert_workspace_clean(_workspace_root(tmp_path))


def test_adapter_instance_is_reusable_across_invocations(tmp_path: Path) -> None:
    adapter = _adapter(_fake_ei(tmp_path, "ok"), tmp_path)
    log = _log_file(tmp_path, _certified_payload())

    first = adapter.export(log)
    second = adapter.export(log)

    assert first.export == second.export
    _assert_workspace_clean(_workspace_root(tmp_path))
