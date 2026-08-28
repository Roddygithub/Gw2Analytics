#!/usr/bin/env python3
"""Check whether buff uptime overcounts equal an agent's post-lastAware absence.

EI stops simulating a player's buffs when the log stops seeing them. Our
tracker only stops on an explicit despawn, so an agent that simply drops off
the log keeps every active buff running to the end of the fight. If that is
the cause, the excess uptime should equal the absence window exactly.

Usage: probe_lastaware.py <stem> [account ...]
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

from gw2_analytics.buff_state import TRACKED_BUFFS  # noqa: E402
from gw2_evtc_parser import PythonEvtcParser, read_zevtc_archive  # noqa: E402

BUFF_NAME = {v: k for k, v in TRACKED_BUFFS.items()}


def main() -> int:
    stem = sys.argv[1]
    wanted = set(sys.argv[2:])

    raw = read_zevtc_archive(ROOT / "WvW" / f"{stem}.zevtc")
    parser = PythonEvtcParser()
    fight = next(parser.parse(raw))
    events = list(parser.parse_events(raw))
    ei = json.loads((ROOT / ".tooling" / "ei-out" / f"{stem}_detailed_wvw_kill.json").read_text())

    origin = min(e.time_ms for e in events)
    duration = ei["durationMS"]

    # Last time each agent is referenced at all, in fight-relative ms.
    last_seen: dict[int, int] = defaultdict(int)
    for event in events:
        rel = event.time_ms - origin
        for agent_id in (event.source_agent_id, getattr(event, "target_agent_id", 0)):
            if agent_id:
                last_seen[agent_id] = max(last_seen[agent_id], rel)

    by_inst: dict[int, list] = defaultdict(list)
    for agent in fight.agents:
        if agent.instance_id:
            by_inst[agent.instance_id].append(agent)

    print(f"{stem}: durationMS={duration} origin={origin}")
    for player in ei["players"]:
        if wanted and player["account"] not in wanted:
            continue
        agents = by_inst.get(player["instanceID"], [])
        ours_last = max((last_seen.get(a.id, 0) for a in agents), default=0)
        absence = duration - player["lastAware"]
        if absence <= 0 and not wanted:
            continue
        print(
            f"\n  {player['account']!r} inst={player['instanceID']} "
            f"EI aware={player['firstAware']}..{player['lastAware']} "
            f"our last event={ours_last}  absence={absence}ms "
            f"({absence / duration * 100:.3f}% of fight)"
        )
        for entry in player.get("buffUptimes", []):
            name = BUFF_NAME.get(entry.get("id"))
            data = entry.get("buffData")
            if not name or not data:
                continue
            ei_uptime = data[0].get("uptime")
            if not isinstance(ei_uptime, (int, float)):
                continue
            predicted = ei_uptime + absence / duration * 100
            print(f"      {name:<13} EI={ei_uptime:<9} predicted-if-we-run-on={predicted:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
