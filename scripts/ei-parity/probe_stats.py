#!/usr/bin/env python3
"""Show signed deltas per statsAll field so systematic over/under-counts show up."""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ei_diff import bucket, run_one  # noqa: E402

signed: dict[str, Counter[int]] = defaultdict(Counter)
totals: dict[str, list[int]] = defaultdict(list)

for stem in sys.argv[1:]:
    rep = run_one(stem)
    for key, value in rep["differences"].items():
        b = bucket(key)
        exp, act = value.get("expected"), value.get("actual")
        if isinstance(exp, (int, float)) and isinstance(act, (int, float)):
            delta = round(act - exp, 3)
            signed[b][delta] += 1
            totals[b].append(delta)

for b in sorted(totals, key=lambda k: -len(totals[k])):
    deltas = totals[b]
    pos = sum(d > 0 for d in deltas)
    neg = sum(d < 0 for d in deltas)
    common = signed[b].most_common(4)
    print(f"{len(deltas):>5}  {b:<52} +{pos}/-{neg}  common deltas={common}")
    print(f"       sum(actual-expected)={round(sum(deltas), 3)}")
