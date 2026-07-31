#!/usr/bin/env python3
"""Solve which arcdps `result` values EI treats as connected / invulned.

For every (player, skill) entry in EI's totalDamageDist we know how many
hits connected and how many were invulned. Restricting to entries whose
raw events all carry the SAME result byte turns each entry into a direct
observation of that value's meaning.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOGS = ROOT / "zevtc files"
EI_OUT = ROOT / ".tooling" / "ei-out"

from gw2_core import DamageEvent  # noqa: E402
from gw2_evtc_parser import PythonEvtcParser, read_zevtc_archive  # noqa: E402

# key: (era, is_condition, result) -> Counter of verdicts
connected_votes: dict[tuple, Counter[str]] = defaultdict(Counter)
invulned_votes: dict[tuple, Counter[str]] = defaultdict(Counter)

stems = sys.argv[1:] or [
    s
    for s in (Path(__file__).resolve().parent / "corpus.txt").read_text().split()
    if (EI_OUT / f"{s}_detailed_wvw_kill.json").exists()
]

for stem in stems:
    raw = read_zevtc_archive(LOGS / f"{stem}.zevtc")
    parser = PythonEvtcParser()
    fight = next(parser.parse(raw))
    events = list(parser.parse_events(raw))
    ei = json.loads((EI_OUT / f"{stem}_detailed_wvw_kill.json").read_text())
    build = int(fight.header.build_version) if fight.header else 0
    era = "new" if build >= 2026_05_07 else "old"

    agents_by_account = {a.account_name.lstrip(":"): a for a in fight.agents if a.account_name}
    inst_ids: dict[int, set[int]] = defaultdict(set)
    for a in fight.agents:
        if a.instance_id:
            inst_ids[a.instance_id].add(a.id)
    damage = [e for e in events if isinstance(e, DamageEvent)]

    for p in ei["players"]:
        agent = agents_by_account.get(p["account"])
        if agent is None:
            continue
        ids = inst_ids.get(agent.instance_id, {agent.id})
        by_skill: dict[int, list[DamageEvent]] = defaultdict(list)
        for e in damage:
            if e.source_agent_id in ids and e.src_master_instid == 0:
                by_skill[e.skill_id].append(e)
        for entry in p["totalDamageDist"][0]:
            mine = by_skill.get(entry["id"], [])
            if not mine:
                continue
            keys = {(e.is_condition, e.result) for e in mine}
            if len(keys) != 1 or len(mine) != entry.get("hits", -1):
                continue
            is_cond, result = next(iter(keys))
            k = (era, is_cond, result)
            connected_votes[k][
                "all"
                if entry["connectedHits"] == len(mine)
                else "none"
                if entry["connectedHits"] == 0
                else "partial"
            ] += 1
            invulned_votes[k][
                "all"
                if entry.get("invulned", 0) == len(mine)
                else "none"
                if entry.get("invulned", 0) == 0
                else "partial"
            ] += 1

print(f"{'era':<5}{'cond':>6}{'result':>8}   {'connected verdicts':<34}invulned verdicts")
for k in sorted(connected_votes, key=lambda x: (x[0], x[1], x[2])):
    era, cond, result = k
    print(
        f"{era:<5}{cond!s:>6}{result:>8}   "
        f"{dict(connected_votes[k])!s:<34}{dict(invulned_votes[k])}"
    )
