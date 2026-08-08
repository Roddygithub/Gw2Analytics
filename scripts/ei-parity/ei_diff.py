#!/usr/bin/env python3
"""Run the in-house parser against EI reference JSON and categorise the deltas.

Usage:
    uv run python .tooling/ei_diff.py [--json out.json] [log-stem ...]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOGS = ROOT / "zevtc files"
EI_OUT = ROOT / ".tooling" / "ei-out"
CORPUS = Path(__file__).resolve().parent / "corpus.txt"

KNOWN_ROTATION_DEAD_ENDS = {
    -41,
    -37,
    -29,
    -14,
    -11,
    -7,
    -6,
    1066,
    13046,
    29560,
    43470,
    44663,
    62834,
    62887,
    62975,
}

from gw2_analytics.ei_compare import compare_elite_insights  # noqa: E402
from gw2_evtc_parser import (  # noqa: E402
    PythonEvtcParser,
    read_zevtc_archive,
    scan_agent_awareness,
    scan_regeneration_overstacks,
)

_BRACKET = re.compile(r"\[[^\]]*\]")


def bucket(key: str) -> str:
    """Collapse ``players[foo.1234].statsAll.totalDmg`` -> ``players.statsAll.totalDmg``."""
    return _BRACKET.sub("", key)


def _rotation_deltas(diffs: dict[str, object]) -> tuple[Counter[int], Counter[int]]:
    missing: Counter[int] = Counter()
    extra: Counter[int] = Counter()
    for key, value in diffs.items():
        if not key.endswith(".rotation") or not isinstance(value, dict):
            continue
        expected_casts = {tuple(c) for c in value.get("expected") or ()}
        actual_casts = {tuple(c) for c in value.get("actual") or ()}
        missing.update(int(cast[0]) for cast in expected_casts - actual_casts if cast)
        extra.update(int(cast[0]) for cast in actual_casts - expected_casts if cast)
    return missing, extra


def _print_rotation_skill_deltas(
    reports: list[dict[str, object]],
    limit: int,
    *,
    show_known_dead_ends: bool,
) -> None:
    missing_by_skill: Counter[int] = Counter()
    extra_by_skill: Counter[int] = Counter()
    names: dict[int, str] = {}
    for rep in reports:
        missing_by_skill.update(rep["rotation_missing_by_skill"])
        extra_by_skill.update(rep["rotation_extra_by_skill"])
        names.update(rep["skill_names"])

    print(f"\n=== TOP {limit} rotation skill deltas ===")
    print(" missing  extra  skill")
    skills = set(missing_by_skill) | set(extra_by_skill)
    if not show_known_dead_ends:
        skipped = skills & KNOWN_ROTATION_DEAD_ENDS
        skills -= KNOWN_ROTATION_DEAD_ENDS
        if skipped:
            print(f" skipped {len(skipped)} known dead-end skills")
    ranked = sorted(
        skills,
        key=lambda skill_id: (
            missing_by_skill[skill_id] + extra_by_skill[skill_id],
            missing_by_skill[skill_id],
        ),
        reverse=True,
    )
    for skill_id in ranked[:limit]:
        name = names.get(skill_id, "?")
        print(f"{missing_by_skill[skill_id]:>8} {extra_by_skill[skill_id]:>6}  {skill_id} {name}")


def run_one(stem: str) -> dict[str, object]:
    log_path = LOGS / f"{stem}.zevtc"
    ei_path = EI_OUT / f"{stem}_detailed_wvw_kill.json"
    if not ei_path.exists():
        candidates = sorted(EI_OUT.glob(f"{stem}_detailed_wvw*.json"))
        if not candidates:
            raise SystemExit(f"no EI reference for {stem}")
        ei_path = candidates[0]

    started = time.monotonic()
    raw = read_zevtc_archive(log_path)
    parser = PythonEvtcParser()
    fight = next(parser.parse(raw))
    events = list(parser.parse_events(raw))
    parse_s = time.monotonic() - started

    expected = json.loads(ei_path.read_text())
    result = compare_elite_insights(
        fight,
        expected,
        events,
        scan_agent_awareness(raw),
        scan_regeneration_overstacks(raw),
    )
    diffs = result["differences"]
    if not isinstance(diffs, dict):  # pragma: no cover - contract of compare_elite_insights
        raise TypeError(f"expected a differences mapping, got {type(diffs).__name__}")

    # ``rotation`` is one difference key per player carrying the whole cast
    # list, so the bucket count only moves when a player's list matches
    # *exactly*. Wiring a single instant-cast finder can remove dozens of
    # missing casts and still show zero progress -- or hide a net regression,
    # if it also adds spurious ones. Count both sides separately.
    missing_by_skill, extra_by_skill = _rotation_deltas(diffs)
    skill_names = {
        int(skill_id[1:]): data["name"]
        for skill_id, data in expected.get("skillMap", {}).items()
        if skill_id.startswith("s") and isinstance(data, dict) and data.get("name")
    }

    return {
        "rotation_missing": sum(missing_by_skill.values()),
        "rotation_extra": sum(extra_by_skill.values()),
        "rotation_missing_by_skill": missing_by_skill,
        "rotation_extra_by_skill": extra_by_skill,
        "skill_names": skill_names,
        "stem": stem,
        "parse_seconds": round(parse_s, 2),
        "events": len(events),
        "agents": len(fight.agents),
        "ei_players": len(expected.get("players", [])),
        "ei_targets": len(expected.get("targets", [])),
        "n_diffs": len(diffs),
        "differences": diffs,
        "buckets": Counter(bucket(k) for k in diffs),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("stems", nargs="*")
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument(
        "--rotation-skills",
        type=int,
        default=15,
        help="print top rotation skill deltas",
    )
    ap.add_argument(
        "--show-known-rotation-dead-ends",
        action="store_true",
        help="include rotation skills already proven noisy or regressive",
    )
    ap.add_argument("--show", default=None, help="print raw diffs whose bucket matches this regex")
    args = ap.parse_args()

    stems = args.stems or [
        s
        for s in (line.strip() for line in CORPUS.read_text().splitlines())
        if s and (EI_OUT / f"{s}_detailed_wvw_kill.json").exists()
    ]
    reports = []
    grand = Counter()
    for stem in stems:
        rep = run_one(stem)
        reports.append(rep)
        grand.update(rep["buckets"])
        print(
            f"{stem}: {rep['n_diffs']:>6} diffs  "
            f"({rep['events']} events, {rep['agents']} agents, "
            f"{rep['ei_players']} EI players, {rep['ei_targets']} EI targets, "
            f"{rep['parse_seconds']}s)",
            flush=True,
        )

    missing = sum(int(r["rotation_missing"]) for r in reports)
    extra = sum(int(r["rotation_extra"]) for r in reports)
    print(f"\n=== TOTAL {sum(grand.values())} differences across {len(reports)} logs ===")
    if missing or extra:
        print(
            f"    (rotation: {missing} casts missing, {extra} extra -- the bucket "
            f"below counts player rows, not casts)"
        )
    for key, count in grand.most_common(args.top):
        print(f"{count:>8}  {key}")

    if args.rotation_skills and (missing or extra):
        _print_rotation_skill_deltas(
            reports,
            args.rotation_skills,
            show_known_dead_ends=args.show_known_rotation_dead_ends,
        )

    if args.show:
        pat = re.compile(args.show)
        print(f"\n=== samples matching /{args.show}/ ===")
        shown = 0
        for rep in reports:
            for key, value in rep["differences"].items():
                if pat.search(bucket(key)) and shown < 25:
                    print(f"[{rep['stem']}] {key}\n    {json.dumps(value)[:400]}")
                    shown += 1

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(
                [{**r, "buckets": dict(r["buckets"])} for r in reports],
                indent=2,
                default=str,
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
