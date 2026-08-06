#!/usr/bin/env python3
"""Find which of our events coincides with a cast EI reports and we do not.

`rotation.py` reimplements EI's `InstantCastFinder` set: each entry says
"when you see *this*, emit a cast of skill X". When a skill is missing from
our rotation the question is always the same -- what does EI key on? This
dumps every event we do have for the player around each of EI's cast times,
so the trigger shows up as the event that is present at every one of them.

Usage: probe_cast_trigger.py <stem> <account> <skill_id> [window_ms]
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

from gw2_evtc_parser import PythonEvtcParser, read_zevtc_archive  # noqa: E402


def main() -> int:
    stem, account, skill_id = sys.argv[1], sys.argv[2], int(sys.argv[3])
    window = int(sys.argv[4]) if len(sys.argv) > 4 else 30

    raw = read_zevtc_archive(ROOT / "zevtc files" / f"{stem}.zevtc")
    parser = PythonEvtcParser()
    fight = next(parser.parse(raw))
    events = list(parser.parse_events(raw))
    ei = json.loads((ROOT / ".tooling" / "ei-out" / f"{stem}_detailed_wvw_kill.json").read_text())

    origin = min(e.time_ms for e in events)
    by_inst: dict[int, list] = defaultdict(list)
    for agent in fight.agents:
        if agent.instance_id:
            by_inst[agent.instance_id].append(agent)

    entries = [p for p in ei["players"] if p["account"] == account]
    if not entries:
        print(f"no EI entry for {account!r}")
        return 1
    agent_ids = {a.id for a in by_inst.get(entries[0]["instanceID"], [])}

    cast_times = sorted(
        cast["castTime"]
        for entry in entries
        for group in entry.get("rotation", [])
        if group.get("id") == skill_id
        for cast in group.get("skills", [])
    )
    print(f"{stem} {account} skill {skill_id}: EI reports {len(cast_times)} casts")
    print(f"agent ids={sorted(agent_ids)}  window=+/-{window}ms\n")

    # Index our events by fight-relative time for the player's agents.
    mine: list[tuple[int, object]] = []
    for event in events:
        src = event.source_agent_id
        dst = getattr(event, "target_agent_id", 0)
        if src in agent_ids or dst in agent_ids:
            mine.append((event.time_ms - origin, event))

    coincident: Counter[tuple[str, int, str]] = Counter()
    for t in cast_times:
        for rel, event in mine:
            if abs(rel - t) > window:
                continue
            role = "src" if event.source_agent_id in agent_ids else "dst"
            coincident[(type(event).__name__, getattr(event, "skill_id", 0), role)] += 1

    print(f"{'event':<22}{'skill':>8}{'role':>6}  hits / {len(cast_times)} casts")
    for (kind, sid, role), n in coincident.most_common(18):
        marker = "  <== present at every cast" if n >= len(cast_times) else ""
        print(f"{kind:<22}{sid:>8}{role:>6}  {n}{marker}")

    print("\nfirst three casts in detail:")
    for t in cast_times[:3]:
        print(f"  --- EI cast at {t}")
        for rel, event in mine:
            if abs(rel - t) <= window:
                print(
                    f"      {rel - t:+5}ms {type(event).__name__:<20} "
                    f"skill={getattr(event, 'skill_id', 0):<8} "
                    f"src={event.source_agent_id} dst={getattr(event, 'target_agent_id', 0)}"
                )
    return 0


if __name__ == "__main__":
    sys.exit(main())
