#!/usr/bin/env python3
"""Measure the exact canonical rotation-diff delta of each candidate table entry.

Parses each corpus log once, then re-runs compare_elite_insights per candidate
with the target table patched at runtime. Canonical = number of rotation buckets
whose expected or actual list is non-empty.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOGS = ROOT / "zevtc files"
EI_OUT = ROOT / ".tooling" / "ei-out"
CORPUS = Path(__file__).resolve().parent / "corpus.txt"

from gw2_analytics import rotation  # noqa: E402
from gw2_analytics.ei_compare import compare_elite_insights  # noqa: E402
from gw2_evtc_parser import PythonEvtcParser, read_zevtc_archive  # noqa: E402

# (table, key, value) — key is the buff/effect id, value the emitted skill id
CANDIDATES = [
    ("_BUFF_GAIN_CASTS", 32931, 31187),   # Dash <- UnhinderedCombatant
    ("_BUFF_GAIN_CASTS", 62931, 62758),   # Flame Wheel
    ("_BUFF_GAIN_CASTS", 9422, 9422),
    ("_BUFF_GAIN_CASTS", 29502, 30435),   # Berserk
    ("_BUFF_GAIN_CASTS", 76507, 5635),    # Arcane Echo
    ("_BUFF_GAIN_CASTS", 51664, 14410),   # Signet of Fury (known good)
    ("_DAMAGE_CASTS", 76783, 75),
    ("_DAMAGE_CASTS", 24305, 50),
    ("_DAMAGE_CASTS", 13907, 50),
    ("_INSTANT_CASTS_BY_EFFECT", "D6C8F406E4DEE04AB16A215BE068E910", 10302),
    ("_INSTANT_CASTS_BY_EFFECT", "E10D2D0DF7803146A69BBB5BD47944FC", 13684),
]


def canonical(buckets: dict[str, object]) -> int:
    n = 0
    for k, v in buckets.items():
        if "rotation" in k and isinstance(v, dict) and (v.get("expected") or v.get("actual")):
            n += 1
    return n


def main() -> int:
    stems = [s.strip() for s in CORPUS.read_text().splitlines() if s.strip()]
    baseline_total = 0
    per_log_baseline: dict[str, int] = {}
    # candidate -> total canonical delta
    deltas: dict[str, int] = {str(c): 0 for c in CANDIDATES}
    per_candidate_per_log: dict[str, dict[str, int]] = {str(c): {} for c in CANDIDATES}

    for stem in stems:
        ei = json.loads((EI_OUT / f"{stem}_detailed_wvw_kill.json").read_text())
        raw = read_zevtc_archive(LOGS / f"{stem}.zevtc")
        parser = PythonEvtcParser()
        fight = next(parser.parse(raw))
        events = list(parser.parse_events(raw))

        base = canonical(compare_elite_insights(fight, ei, events)["differences"])
        per_log_baseline[stem] = base
        baseline_total += base

        for cand in CANDIDATES:
            table_name, key, value = cand
            table = getattr(rotation, table_name)
            original = table.get(key)
            table[key] = value
            try:
                n = canonical(compare_elite_insights(fight, ei, events)["differences"])
            finally:
                if original is None:
                    del table[key]
                else:
                    table[key] = original
            deltas[str(cand)] += n - base
            per_candidate_per_log[str(cand)][stem] = n - base

    print(f"baseline canonical total: {baseline_total}")
    for cand in CANDIDATES:
        d = deltas[str(cand)]
        print(f"{cand!s:70} delta={d:+d}")
        if d < 0:
            improved = {s: x for s, x in per_candidate_per_log[str(cand)].items() if x < 0}
            worsened = {s: x for s, x in per_candidate_per_log[str(cand)].items() if x > 0}
            if improved:
                print(f"    improved logs: {improved}")
            if worsened:
                print(f"    worsened logs: {worsened}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
