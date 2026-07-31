#!/usr/bin/env python3
"""For players whose connectedDamageCount is short, dump the disputed events."""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOGS = ROOT / "zevtc files"
EI_OUT = ROOT / ".tooling" / "ei-out"

from gw2_analytics.ei_compare import _connected  # noqa: E402
from gw2_core import DamageEvent  # noqa: E402
from gw2_evtc_parser import PythonEvtcParser, read_zevtc_archive  # noqa: E402

stem = sys.argv[1]
raw = read_zevtc_archive(LOGS / f"{stem}.zevtc")
parser = PythonEvtcParser()
fight = next(parser.parse(raw))
events = list(parser.parse_events(raw))
ei = json.loads((EI_OUT / f"{stem}_detailed_wvw_kill.json").read_text())

agents_by_account = {a.account_name.lstrip(":"): a for a in fight.agents if a.account_name}
inst_ids: dict[int, set[int]] = defaultdict(set)
for a in fight.agents:
    if a.instance_id:
        inst_ids[a.instance_id].add(a.id)
damage = [e for e in events if isinstance(e, DamageEvent)]

profile: Counter[tuple] = Counter()
for p in ei["players"]:
    agent = agents_by_account.get(p["account"])
    if agent is None:
        continue
    ids = inst_ids.get(agent.instance_id, {agent.id})
    ours = [
        e
        for e in damage
        if e.source_agent_id in ids and e.src_master_instid == 0 and e.result != 10
    ]
    want = p["statsAll"][0]["connectedDamageCount"]
    got = sum(_connected(e) for e in ours)
    if want == got:
        continue
    print(f"--- {p['account']}: EI connected={want} ours={got} (total counted={len(ours)})")
    for e in ours:
        if not _connected(e):
            profile[
                (e.is_condition, e.result, e.damage > 0, e.buff_dmg > 0, e.shield_damage > 0)
            ] += 1

print()
print(f"{'isCond':>7}{'result':>7}{'dmg>0':>7}{'buffDmg>0':>11}{'shield>0':>10}  count")
for key, n in sorted(profile.items(), key=lambda kv: -kv[1]):
    c, r, d, b, s = key
    print(f"{c!s:>7}{r:>7}{d!s:>7}{b!s:>11}{s!s:>10}  {n}")
