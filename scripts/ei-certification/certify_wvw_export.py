#!/usr/bin/env python3
"""Certify a pinned WvW export contract against a private log manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable
from functools import partial
from itertools import pairwise
from pathlib import Path
from typing import Any

from gw2_core import WvwExportV1, WvwExportV2

ROOT = Path(__file__).resolve().parents[2]
PINNED_EI_COMMIT = "062e250d55c0a09a7f734524287043c7852483b4"
KINDS = (
    "damage",
    "buff_apply",
    "buff_extension",
    "buff_remove_all",
    "buff_remove_single",
    "buff_remove_manual",
    "down",
    "death",
    "alive",
    "spawn",
    "despawn",
    "health_update",
)
V2_KINDS = (
    "damage",
    "buff_apply",
    "buff_extension",
    "buff_remove_all",
    "buff_remove_single",
    "buff_remove_manual",
    "down",
    "death",
    "up",
    "spawn",
    "despawn",
    "health_update",
    "healing",
    "cc",
)


def _cli() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--corpus", type=Path, required=True, help="Root searched recursively for logs"
    )
    parser.add_argument(
        "--ei-source", type=Path, required=True, help="Clean checkout of the pinned EI fork"
    )
    parser.add_argument("--dotnet", type=Path, required=True, help="Local .NET SDK executable")
    parser.add_argument("--cli", type=Path, required=True, help="Built EI CLI DLL")
    parser.add_argument("--schema-version", type=int, choices=(1, 2), default=1)
    parser.add_argument("--expected-ei-commit", help="Required exact EI commit for V2 runs")
    parser.add_argument("--output", type=Path, required=True, help="Ignored local output directory")
    parser.add_argument(
        "--replay-disabled-report",
        type=Path,
        help="Optional output report for replay-disabled comparison on all 35 logs",
    )
    return parser.parse_args()


def _rss_kib(pid: int) -> int:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except (FileNotFoundError, ProcessLookupError, ValueError):
        pass
    return 0


def _run_ei(dotnet: Path, cli: Path, config: Path, log: Path, log_path: Path) -> tuple[float, int]:
    started = time.monotonic()
    with log_path.open("wb") as transcript:
        process = subprocess.Popen(  # noqa: S603 - arguments are explicit local paths
            [str(dotnet), str(cli), "-c", str(config), str(log)],
            stdout=transcript,
            stderr=subprocess.STDOUT,
        )
        peak_rss_kib = 0
        while process.poll() is None:
            peak_rss_kib = max(peak_rss_kib, _rss_kib(process.pid))
            time.sleep(0.01)
        return_code = process.wait()
        peak_rss_kib = max(peak_rss_kib, _rss_kib(process.pid))
    elapsed = time.monotonic() - started
    if return_code:
        raise RuntimeError(
            f"EI failed for manifest log {log.name}; see local transcript {log_path}"
        )
    return elapsed, peak_rss_kib


def _config(output_dir: Path, parse_replay: bool, schema_version: int = 1) -> str:
    settings = {
        "SaveAtOut": "false",
        "OutLocation": str(output_dir.resolve()),
        "SaveOutWvwExport": str(schema_version == 1).lower(),
        "SaveOutWvwExportV2": str(schema_version == 2).lower(),
        "SaveOutJSON": "false",
        "SaveOutHTML": "false",
        "SaveOutCSV": "false",
        "SaveOutTrace": "false",
        "SingleThreaded": "true",
        "ParsePhases": "true",
        "ParseCombatReplay": str(parse_replay).lower(),
        "ParseExtensions": "true",
        "ComputeDamage": "true",
        "ComputeBuff": "true",
        "ComputeCast": "true",
        "ComputeMechanics": "true",
        "ComputeDamageModifiers": "true",
        "ParseMultipleLogs": "false",
        "RawTimelineArrays": "false",
        "DetailledWvW": "true",
        "UploadToDPSReports": "false",
        "UploadToWingman": "false",
        "UploadToMistWarrior": "false",
        "UploadToRaidar": "false",
    }
    return "\n".join(f"{key}={value}" for key, value in settings.items()) + "\n"


def _find_logs(manifest: dict[str, Any], corpus: Path) -> list[tuple[dict[str, Any], Path]]:
    entries = manifest.get("entries")
    if not isinstance(entries, list) or len(entries) != 35:
        raise ValueError("certification manifest must contain exactly 35 entries")
    if len({entry.get("stem") for entry in entries}) != 35:
        raise ValueError("certification manifest stems must be unique")
    result: list[tuple[dict[str, Any], Path]] = []
    for entry in entries:
        stem = entry["stem"]
        matches = list(corpus.rglob(f"{stem}.zevtc"))
        if len(matches) != 1:
            raise ValueError(f"manifest stem {stem} resolved to {len(matches)} log files")
        path = matches[0].resolve()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != entry.get("evtc_sha256"):
            raise ValueError(f"manifest SHA-256 mismatch for {stem}")
        result.append((entry, path))
    return result


def _summarize(
    payload: dict[str, Any], stem: str, input_bytes: int, output: bytes, schema_version: int = 1
) -> dict[str, Any]:
    fight = payload["fights"][0]
    events = fight["events"]
    positions = fight["position_samples"]
    duration_ms = fight["duration_ms"]
    recording_end_ms = fight.get("recording_end_ms")
    event_counts: Counter[str] = Counter(event["kind"] for event in events)
    event_times = [event["time_ms"] for event in events]
    position_times = [point["time_ms"] for point in positions]
    ownership_by_agent: dict[str, list[dict[str, Any]]] = {}
    for interval in fight["ownership_intervals"]:
        ownership_by_agent.setdefault(interval["agent_id"], []).append(interval)
    owner_changes = sum(
        previous["owner_actor_id"] != current["owner_actor_id"]
        for intervals in ownership_by_agent.values()
        for previous, current in pairwise(intervals)
    )
    return {
        "log": stem,
        "input_bytes": input_bytes,
        "output_bytes": len(output),
        "expansion_ratio": round(len(output) / input_bytes, 4),
        "duration_ms": duration_ms,
        "actors": len(fight["actors"]),
        "events": len(events),
        "healing_amount_total": sum(
            event.get("amount", 0) for event in events if event["kind"] == "healing"
        ),
        "cc_duration_ms_total": sum(
            event.get("duration_ms", 0) for event in events if event["kind"] == "cc"
        ),
        "events_by_kind": {
            kind: event_counts[kind] for kind in (V2_KINDS if schema_version == 2 else KINDS)
        },
        "recording_end_ms": recording_end_ms,
        "event_domain_end_ms": fight.get("event_domain_end_ms"),
        "healing_available": fight.get("healing_available"),
        "ownership_observations": fight["ownership_observation_count"],
        "ownership_same_time_collisions": fight["ownership_same_time_collision_count"],
        "ownership_intervals": len(fight["ownership_intervals"]),
        "ownership_owner_changes": owner_changes,
        "unresolved_owners": sum(
            interval["owner_resolution"] == "unresolved"
            for interval in fight["ownership_intervals"]
        ),
        "positions": len(positions),
        "event_time_min_ms": min(event_times, default=None),
        "event_time_max_ms": max(event_times, default=None),
        "position_time_min_ms": min(position_times, default=None),
        "position_time_max_ms": max(position_times, default=None),
        "events_after_duration": sum(event["time_ms"] > duration_ms for event in events),
        "events_after_recording_end": (
            sum(event["time_ms"] > recording_end_ms for event in events)
            if recording_end_ms is not None
            else None
        ),
        "actors_after_duration": sum(
            actor["last_aware_ms"] > duration_ms for actor in fight["actors"]
        ),
        "ownership_intervals_after_duration": sum(
            interval["end_ms"] > duration_ms for interval in fight["ownership_intervals"]
        ),
        "positions_after_duration": sum(point["time_ms"] > duration_ms for point in positions),
        "output_sha256": hashlib.sha256(output).hexdigest(),
        "parser_version": payload["parser_version"],
    }


def _validation_errors(payload: dict[str, Any], schema_version: int = 1) -> list[dict[str, str]]:
    try:
        model = WvwExportV1 if schema_version == 1 else WvwExportV2
        validated = model.model_validate(payload)
        if validated.parser_version != "3.26.0.0":
            raise ValueError("unexpected_parser_version")
        if validated.source_log_count != 1 or len(validated.fights) != 1:
            raise ValueError("unexpected_source_or_fight_count")
        if validated.fights[0].fight_id != "log-0000/fight-0000":
            raise ValueError("unexpected_source_fight_identity")
    except Exception as exc:
        error_list = getattr(exc, "errors", None)
        if callable(error_list):
            return [
                {
                    "path": ".".join(str(part) for part in error.get("loc", ())),
                    "type": str(error.get("type", "validation_error")),
                    "message": str(error.get("msg", "")),
                }
                for error in error_list(include_input=False)
            ]
        return [{"path": "export", "type": "contract_invariant", "message": str(exc)}]
    return []


def _validation_result(payload: dict[str, Any], schema_version: int = 1) -> dict[str, Any]:
    errors = _validation_errors(payload, schema_version)
    return {"schema_valid": not errors, "validation_errors": errors}


def _compare_export_bytes(first: bytes, second: bytes) -> dict[str, str | bool]:
    return {
        "deterministic_repeat": first == second,
        "output_sha256": hashlib.sha256(first).hexdigest(),
        "repeat_output_sha256": hashlib.sha256(second).hexdigest(),
    }


def _repeat_export_bytes(
    output_dir: Path, stem: str, suffix: str, run: Callable[[], tuple[float, int]]
) -> tuple[bytes, float, int]:
    """Delete the first export sidecar, rerun EI, and read only a freshly produced output.

    The repeat run must produce exactly one new export sidecar: a missing or an additional
    output is a harness failure, and the fresh bytes are re-listed from disk so a stale
    path can never stand in for a new export.
    """
    pattern = f"{stem}*{suffix}"
    existing = list(output_dir.glob(pattern))
    if len(existing) != 1:
        raise RuntimeError(
            f"expected exactly one export sidecar before the repeat run of {stem}, "
            f"found {len(existing)}"
        )
    existing[0].unlink()
    if list(output_dir.glob(pattern)):
        raise RuntimeError(f"deleted export sidecar still matches the export pattern for {stem}")
    wall_seconds, peak_rss_kib = run()
    fresh = list(output_dir.glob(pattern))
    if not fresh:
        raise RuntimeError(f"repeat EI run produced no export output for {stem}")
    if len(fresh) > 1:
        raise RuntimeError(
            f"repeat EI run produced {len(fresh)} export outputs for {stem}, expected exactly one"
        )
    return fresh[0].read_bytes(), wall_seconds, peak_rss_kib


def _percentile95(values: list[float]) -> float:
    return sorted(values)[max(0, int(0.95 * len(values) + 0.999999) - 1)]


def _distribution(values: list[float]) -> dict[str, float | int]:
    ordered = sorted(values)
    return {
        "median": statistics.median(ordered),
        "p95": ordered[max(0, int(0.95 * len(ordered) + 0.999999) - 1)],
        "max": max(ordered),
    }


def _run_mode(
    logs: list[tuple[dict[str, Any], Path]],
    *,
    dotnet: Path,
    cli: Path,
    root_output: Path,
    parse_replay: bool,
    schema_version: int = 1,
) -> dict[str, Any]:
    mode = "replay_enabled" if parse_replay else "replay_disabled"
    mode_root = root_output / mode
    mode_root.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for index, (entry, log) in enumerate(logs, start=1):
        stem = entry["stem"]
        log_root = mode_root / stem
        output_dir = log_root / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        config = log_root / "ei.conf"
        config.write_text(_config(output_dir, parse_replay, schema_version), encoding="utf-8")
        suffix = f"_wvw_export_v{schema_version}.json"
        for previous in output_dir.glob(f"{stem}*{suffix}"):
            previous.unlink()
        transcript = log_root / "ei.log"
        try:
            first_wall, peak_rss = _run_ei(dotnet, cli, config, log, transcript)
            exports = list(output_dir.glob(f"{stem}*{suffix}"))
            if len(exports) != 1:
                raise RuntimeError(
                    f"EI produced {len(exports)} WvwExportV{schema_version} files "
                    f"for {stem}, expected exactly one"
                )
            exported = exports[0]
            first_bytes = exported.read_bytes()
            payload = json.loads(first_bytes)
            validation = _validation_result(payload, schema_version)
            validation_errors = validation["validation_errors"]
            second_bytes, repeat_wall, repeat_peak_rss = _repeat_export_bytes(
                output_dir,
                stem,
                suffix,
                partial(_run_ei, dotnet, cli, config, log, transcript),
            )
            repeat_comparison = _compare_export_bytes(first_bytes, second_bytes)
            identical = repeat_comparison["deterministic_repeat"]
            row = _summarize(payload, stem, log.stat().st_size, first_bytes, schema_version)
            row.update(
                wall_seconds=round(first_wall, 3),
                repeat_wall_seconds=round(repeat_wall, 3),
                peak_rss_mb=round(max(peak_rss, repeat_peak_rss) / 1024, 1),
                **repeat_comparison,
                **validation,
            )
            results.append(row)
            if validation_errors:
                failures.append({"log": stem, "reason": "schema_validation_failed"})
            if not identical:
                failures.append({"log": stem, "reason": "repeat_output_bytes_differ"})
        except Exception as exc:  # report failure without echoing EI transcript content
            failures.append({"log": stem, "reason": type(exc).__name__})
        print(f"{mode}: {index}/{len(logs)}", flush=True)

    if not results:
        return {"mode": mode, "logs": [], "failures": failures}
    return {
        "mode": mode,
        "logs": results,
        "failures": failures,
        "summary": {
            "logs": len(results),
            "input_bytes": sum(row["input_bytes"] for row in results),
            "output_bytes": sum(row["output_bytes"] for row in results),
            "expansion_ratio": round(
                sum(row["output_bytes"] for row in results)
                / sum(row["input_bytes"] for row in results),
                4,
            ),
            "wall_seconds_total": round(sum(row["wall_seconds"] for row in results), 3),
            "wall_seconds_median": round(
                statistics.median(row["wall_seconds"] for row in results), 3
            ),
            "wall_seconds_p95": round(_percentile95([row["wall_seconds"] for row in results]), 3),
            "wall_seconds_max": round(max(row["wall_seconds"] for row in results), 3),
            "output_bytes_distribution": _distribution([row["output_bytes"] for row in results]),
            "peak_rss_mb_distribution": _distribution([row["peak_rss_mb"] for row in results]),
            "duration_ms_distribution": _distribution([row["duration_ms"] for row in results]),
            "peak_rss_mb_max": max(row["peak_rss_mb"] for row in results),
            "actors": sum(row["actors"] for row in results),
            "events": sum(row["events"] for row in results),
            "healing_amount_total": sum(row["healing_amount_total"] for row in results),
            "cc_duration_ms_total": sum(row["cc_duration_ms_total"] for row in results),
            "events_by_kind": {
                kind: sum(row["events_by_kind"][kind] for row in results)
                for kind in (V2_KINDS if schema_version == 2 else KINDS)
            },
            "ownership_observations": sum(row["ownership_observations"] for row in results),
            "ownership_same_time_collisions": sum(
                row["ownership_same_time_collisions"] for row in results
            ),
            "ownership_intervals": sum(row["ownership_intervals"] for row in results),
            "ownership_owner_changes": sum(row["ownership_owner_changes"] for row in results),
            "unresolved_owners": sum(row["unresolved_owners"] for row in results),
            "logs_with_collisions": sum(
                row["ownership_same_time_collisions"] > 0 for row in results
            ),
            "logs_with_unresolved_owners": sum(row["unresolved_owners"] > 0 for row in results),
            "positions": sum(row["positions"] for row in results),
            "deterministic_logs": sum(row["deterministic_repeat"] for row in results),
            "schema_valid_logs": sum(row["schema_valid"] for row in results),
            "overall_pass_logs": sum(
                row["schema_valid"] and row["deterministic_repeat"] for row in results
            ),
            "logs_with_healing": sum(
                row["events_by_kind"].get("healing", 0) > 0 for row in results
            ),
            "logs_with_up": sum(row["events_by_kind"].get("up", 0) > 0 for row in results),
            "logs_with_cc": sum(row["events_by_kind"].get("cc", 0) > 0 for row in results),
            "logs_with_events_after_recording_end": sum(
                (row["events_after_recording_end"] or 0) > 0 for row in results
            ),
        },
    }


def main() -> int:
    args = _cli()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest["reference"]["ei_version"] != "3.26.0.0":
        raise SystemExit("manifest EI version is not the certified 3.26.0.0 baseline")
    commit = subprocess.check_output(  # noqa: S603 - fixed local git command
        ["git", "-C", str(args.ei_source), "rev-parse", "HEAD"],  # noqa: S607
        text=True,
    ).strip()
    expected_commit = args.expected_ei_commit or PINNED_EI_COMMIT
    if args.schema_version == 2 and not args.expected_ei_commit:
        raise SystemExit("--expected-ei-commit is required for V2 certification")
    if commit != expected_commit:
        raise SystemExit(f"EI checkout is not at the requested commit {expected_commit}")
    logs = _find_logs(manifest, args.corpus.resolve())
    tracked = set(
        subprocess.check_output(  # noqa: S603 - fixed local git command
            ["git", "-C", str(ROOT), "ls-files", "*.zevtc"],  # noqa: S607
            text=True,
        ).splitlines()
    )
    corpus_resolved = {path.resolve() for _, path in logs}
    for tracked_path in tracked:
        if (ROOT / tracked_path).resolve() in corpus_resolved:
            raise SystemExit("a certification corpus log is Git-tracked")

    args.output.mkdir(parents=True, exist_ok=True)
    enabled = _run_mode(
        logs,
        dotnet=args.dotnet.resolve(),
        cli=args.cli.resolve(),
        root_output=args.output,
        parse_replay=True,
        schema_version=args.schema_version,
    )
    report: dict[str, Any] = {
        "schema_version": args.schema_version,
        "ei_commit": commit,
        "ei_version": manifest["reference"]["ei_version"],
        "manifest_entries": len(logs),
        "replay_enabled": enabled,
    }
    if args.replay_disabled_report:
        disabled = _run_mode(
            logs,
            dotnet=args.dotnet.resolve(),
            cli=args.cli.resolve(),
            root_output=args.output,
            parse_replay=False,
            schema_version=args.schema_version,
        )
        report["replay_disabled"] = disabled
        enabled_summary = enabled.get("summary", {})
        disabled_summary = disabled.get("summary", {})
        report["replay_cost_comparison"] = {
            "output_bytes_delta_enabled_minus_disabled": enabled_summary.get("output_bytes", 0)
            - disabled_summary.get("output_bytes", 0),
            "wall_seconds_delta_enabled_minus_disabled": round(
                enabled_summary.get("wall_seconds_total", 0)
                - disabled_summary.get("wall_seconds_total", 0),
                3,
            ),
            "sampled_direct_dotnet_rss_max_mb_enabled": enabled_summary.get("peak_rss_mb_max"),
            "sampled_direct_dotnet_rss_max_mb_disabled": disabled_summary.get("peak_rss_mb_max"),
            "positions_enabled": enabled_summary.get("positions", 0),
            "positions_disabled": disabled_summary.get("positions", 0),
        }
    output = args.replay_disabled_report or (args.output / "aggregate-report.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"aggregate_report={output}")
    summary = enabled.get("summary", {})
    print(f"replay_enabled_schema_valid={summary.get('schema_valid_logs', 0)}/35")
    print(f"replay_enabled_deterministic={summary.get('deterministic_logs', 0)}/35")
    print(f"replay_enabled_passed={summary.get('overall_pass_logs', 0)}/35")
    if enabled["failures"]:
        return 1
    if args.replay_disabled_report and report.get("replay_disabled", {}).get("failures"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
