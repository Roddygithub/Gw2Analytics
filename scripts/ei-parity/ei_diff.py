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

from gw2_analytics.ei_compare import compare_elite_insights  # noqa: E402
from gw2_evtc_parser import PythonEvtcParser, read_zevtc_archive  # noqa: E402

_BRACKET = re.compile(r"\[[^\]]*\]")


def bucket(key: str) -> str:
    """Collapse ``players[foo.1234].statsAll.totalDmg`` -> ``players.statsAll.totalDmg``."""
    return _BRACKET.sub("", key)


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
    result = compare_elite_insights(fight, expected, events)
    diffs = result["differences"]
    if not isinstance(diffs, dict):  # pragma: no cover - contract of compare_elite_insights
        raise TypeError(f"expected a differences mapping, got {type(diffs).__name__}")

    return {
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

    print(f"\n=== TOTAL {sum(grand.values())} differences across {len(reports)} logs ===")
    for key, count in grand.most_common(args.top):
        print(f"{count:>8}  {key}")

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
