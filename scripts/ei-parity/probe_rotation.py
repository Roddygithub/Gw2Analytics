#!/usr/bin/env python3
"""Drill into rotation diffs: which skill_ids are expected/actual-only, mismatched counts."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOGS = ROOT / "zevtc files"
EI_OUT = ROOT / ".tooling" / "ei-out"

from gw2_analytics.ei_compare import compare_elite_insights  # noqa: E402
from gw2_evtc_parser import PythonEvtcParser, read_zevtc_archive  # noqa: E402


def run(stem: str) -> None:
    raw = read_zevtc_archive(LOGS / f"{stem}.zevtc")
    parser = PythonEvtcParser()
    fight = next(parser.parse(raw))
    events = list(parser.parse_events(raw))
    ei = json.loads((EI_OUT / f"{stem}_detailed_wvw_kill.json").read_text())
    result = compare_elite_insights(fight, ei, events)
    diffs = result["differences"]
    total_xc, total_xe = Counter(), Counter()
    total_only_e, total_only_x = Counter(), Counter()
    for key, val in diffs.items():
        if "rotation" not in key:
            continue
        exp = [tuple(c) for c in val["expected"]]
        act = [tuple(c) for c in val["actual"]]
        ce = Counter(c[0] for c in exp)
        cx = Counter(c[0] for c in act)
        xc = ce - cx
        xe = cx - ce
        if xc or xe:
            print(f"\n--- {key} ---")
            exp_times = {c[0]: [] for c in exp}
            print(f"exp_only={dict(xc)}  act_only={dict(xe)}  exp_times={exp_times}")
        total_xc.update(xc)
        total_xe.update(xe)
        total_only_e.update(xc)
        total_only_x.update(xe)
    print(f"\n=== {stem} summary ===")
    print(f"only_in_expected (parser missing): {dict(total_only_e)}")
    print(f"only_in_actual   (parser extra):  {dict(total_only_x)}")


if __name__ == "__main__":
    for s in sys.argv[1:]:
        run(s)
