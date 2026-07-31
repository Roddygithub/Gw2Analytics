#!/usr/bin/env python3
"""Check how EI's `targets[]` entries resolve onto parser agents."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOGS = ROOT / "zevtc files"
EI_OUT = ROOT / ".tooling" / "ei-out"

from gw2_evtc_parser import PythonEvtcParser, read_zevtc_archive  # noqa: E402

verdict: Counter[str] = Counter()
samples: list[str] = []

for stem in sys.argv[1:]:
    raw = read_zevtc_archive(LOGS / f"{stem}.zevtc")
    fight = next(PythonEvtcParser().parse(raw))
    ei = json.loads((EI_OUT / f"{stem}_detailed_wvw_kill.json").read_text())

    by_inst: dict[int, list] = {}
    for a in fight.agents:
        if a.instance_id:
            by_inst.setdefault(a.instance_id, []).append(a)
    # what ei_compare actually does: last-wins single mapping
    last_wins = {a.instance_id: a for a in fight.agents if a.instance_id}

    for t in ei.get("targets", []):
        inst = t.get("instanceID")
        cands = by_inst.get(inst, [])
        chosen = last_wins.get(inst)
        if not cands:
            verdict["unresolved"] += 1
            if len(samples) < 12:
                samples.append(f"[{stem}] NO AGENT for target inst={inst} {t.get('name')!r}")
        elif len(cands) > 1:
            verdict["ambiguous (instance reused)"] += 1
            if len(samples) < 12:
                names = [a.name for a in cands]
                samples.append(
                    f"[{stem}] AMBIGUOUS inst={inst} EI={t.get('name')!r} "
                    f"candidates={names} chose={chosen.name!r}"
                )
        else:
            verdict["unique"] += 1

    # cross-check: does the number of EI targets match dpsTargets length?
    for p in ei.get("players", [])[:1]:
        key = f"len(dpsTargets)=={len(p.get('dpsTargets', []))} vs targets=={len(ei['targets'])}"
        verdict[key] += 1

print(verdict)
print()
for s in samples:
    print(s)
