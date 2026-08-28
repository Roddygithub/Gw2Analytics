#!/usr/bin/env python3
"""Cross-validate candidate triggers for a missing instant cast.

A single player is not enough to pick a trigger: a boon the whole squad
receives, or an effect that happens to fire alongside the real one, will
coincide with every cast for that one player. A real `InstantCastFinder`
key holds 1:1 across *different* players and logs.

Scores each candidate on (a) how many of EI's casts it covers and (b) how
many extra occurrences it has. The winner covers everything and fires no
more often than the cast itself.

Usage: probe_cast_candidates.py <skill_id> <stem:account> [<stem:account> ...]
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

from gw2_core import EffectEvent  # noqa: E402
from gw2_evtc_parser import PythonEvtcParser, read_zevtc_archive  # noqa: E402

WINDOW = 30


def main() -> int:
    skill_id = int(sys.argv[1])
    pairs = [arg.split(":", 1) for arg in sys.argv[2:]]

    # candidate -> [covered casts, total occurrences, guid]
    covered: dict[tuple, int] = defaultdict(int)
    total: dict[tuple, int] = defaultdict(int)
    guids: dict[tuple, str] = {}
    expected_casts = 0

    for stem, account in pairs:
        raw = read_zevtc_archive(ROOT / "WvW" / f"{stem}.zevtc")
        parser = PythonEvtcParser()
        fight = next(parser.parse(raw))
        events = list(parser.parse_events(raw))
        ei = json.loads(
            (ROOT / ".tooling" / "ei-out" / f"{stem}_detailed_wvw_kill.json").read_text()
        )
        origin = min(e.time_ms for e in events)
        by_inst: dict[int, list] = defaultdict(list)
        for agent in fight.agents:
            if agent.instance_id:
                by_inst[agent.instance_id].append(agent)
        entries = [p for p in ei["players"] if p["account"] == account]
        if not entries:
            continue
        agent_ids = {a.id for a in by_inst.get(entries[0]["instanceID"], [])}
        casts = sorted(
            cast["castTime"]
            for entry in entries
            for group in entry.get("rotation", [])
            if group.get("id") == skill_id
            for cast in group.get("skills", [])
        )
        expected_casts += len(casts)

        mine = [(e.time_ms - origin, e) for e in events if e.source_agent_id in agent_ids]

        def key_of(event: object) -> tuple:
            # Effect ids are per-log ephemeral -- EI keys its effect finders on
            # the GUID, so keying on skill_id here would make the same effect
            # look like a different candidate in every log.
            if isinstance(event, EffectEvent):
                return ("EffectEvent", event.guid)
            return (type(event).__name__, getattr(event, "skill_id", 0))

        for _rel, event in mine:
            key = key_of(event)
            total[key] += 1
            if isinstance(event, EffectEvent):
                guids.setdefault(key, event.guid)
        for t in casts:
            seen = {key_of(event) for rel, event in mine if abs(rel - t) <= WINDOW}
            for key in seen:
                covered[key] += 1

    print(f"skill {skill_id}: {expected_casts} EI casts over {len(pairs)} (log, player) pairs\n")
    print(f"{'event':<22}{'skill or guid':>36}{'covers':>8}{'fires':>8}")
    ranked = sorted(covered.items(), key=lambda kv: (-kv[1], total[kv[0]]))
    for key, cov in ranked[:14]:
        if cov < expected_casts * 0.9:
            continue
        flag = "  <== 1:1" if total[key] == expected_casts else ""
        label = str(key[1])[:34]
        print(f"{key[0]:<22}{label:>36}{cov:>8}{total[key]:>8}{flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
