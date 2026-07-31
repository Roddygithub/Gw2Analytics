#!/usr/bin/env python3
"""Cross-check parser elite-spec decoding against EI's profession field."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOGS = ROOT / "zevtc files"
EI_OUT = ROOT / ".tooling" / "ei-out"

from gw2_evtc_parser import PythonEvtcParser, read_zevtc_archive  # noqa: E402

pairs: Counter[tuple[int, int, str]] = Counter()
stems = sys.argv[1:] or [
    line.strip()
    for line in (Path(__file__).resolve().parent / "corpus.txt").read_text().splitlines()
    if line.strip() and (EI_OUT / f"{line.strip()}_detailed_wvw_kill.json").exists()
]

for stem in stems:
    raw = read_zevtc_archive(LOGS / f"{stem}.zevtc")
    fight = next(PythonEvtcParser().parse(raw))
    by_inst = {a.instance_id: a for a in fight.agents if a.instance_id}
    ei = json.loads((EI_OUT / f"{stem}_detailed_wvw_kill.json").read_text())
    for p in ei.get("players", []):
        agent = by_inst.get(p.get("instanceID"))
        if agent is None:
            continue
        pairs[(agent.profession.value, agent.elite_raw, p["profession"])] += 1

print(f"{'prof':>5} {'elite_raw':>10}  {'EI profession':<16} count")
for (prof, elite_raw, ei_name), n in sorted(pairs.items()):
    print(f"{prof:>5} {elite_raw:>10}  {ei_name:<16} {n}")
