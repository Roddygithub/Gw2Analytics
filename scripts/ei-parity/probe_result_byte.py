#!/usr/bin/env python3
"""Per-(player, skill) reconciliation of EI damage-dist counters vs our events."""

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

stem = sys.argv[1]
want_skill = int(sys.argv[2]) if len(sys.argv) > 2 else None

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
shown = 0

for p in ei["players"]:
    agent = agents_by_account.get(p["account"])
    if agent is None:
        continue
    ids = inst_ids.get(agent.instance_id, {agent.id})
    ours = [e for e in damage if e.source_agent_id in ids and e.src_master_instid == 0]
    by_skill: dict[int, list] = defaultdict(list)
    for e in ours:
        by_skill[e.skill_id].append(e)
    for entry in p["totalDamageDist"][0]:
        sid = entry["id"]
        if want_skill is not None and sid != want_skill:
            continue
        mine = by_skill.get(sid, [])
        our_connected = sum(
            (e.damage > 0) if e.buff_dmg > 0 else (e.result in {0, 1, 2, 8}) for e in mine
        )
        if entry.get("connectedHits", 0) == our_connected and want_skill is None:
            continue
        if shown >= 6:
            break
        shown += 1
        results = Counter((e.result, e.buff_dmg > 0, e.damage > 0) for e in mine)
        print(f"--- {p['account']} skill {sid}")
        print(
            "    EI: "
            + ", ".join(
                f"{k}={entry[k]}"
                for k in (
                    "hits",
                    "connectedHits",
                    "totalDamage",
                    "missed",
                    "invulned",
                    "interrupted",
                    "evaded",
                    "blocked",
                    "glance",
                    "crit",
                    "shieldDamage",
                )
                if k in entry
            )
        )
        print(
            f"    ours: {len(mine)} events, connected={our_connected}, "
            f"sumDamage={sum(e.damage for e in mine)}"
        )
        print(f"    (result, buffDmg>0, dmg>0) -> {dict(results)}")
