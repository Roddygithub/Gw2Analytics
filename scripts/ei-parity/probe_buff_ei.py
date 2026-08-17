#!/usr/bin/env python3
"""Replay one player's duration-boon event stream through (a) the in-house
BuffStateTracker and (b) a faithful port of EI's BuffSimulatorDuration +
QueueLogic, and compare both to EI's recorded uptime.

Pin the divergence model before touching buff_state.py.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOGS = ROOT / "zevtc files"
EI_OUT = ROOT / ".tooling" / "ei-out"

from gw2_analytics.buff_state import (  # noqa: E402
    TRACKED_BUFFS,
    BuffStateTracker,
    _capacity_for,
    _get_buff_name,
)
from gw2_core import BoonApplyEvent, BuffApplyEvent, BuffExtensionEvent  # noqa: E402
from gw2_evtc_parser import PythonEvtcParser, read_zevtc_archive  # noqa: E402

SWIFT = TRACKED_BUFFS["swiftness"]


class EIStackItem:
    __slots__ = ("duration", "start")

    def __init__(self, start: int, duration: int):
        self.start = start
        self.duration = duration


def ei_queue_uptime(stacks: list[EIStackItem], fight_end: int) -> int:
    """Port of BuffSimulatorDuration + QueueLogic (capacity-9, drop-shortest on
    overflow, only the FRONT counts while it lasts; added_active lifts it to front).
    Returns cumulative active ms."""
    cap = _capacity_for("swiftness")
    total = 0
    buf: list[EIStackItem] = []
    t = 0
    i = 0
    guard = 0
    while guard < 1_000_000:
        guard += 1
        # drain front (buf[0]); when it expires pop and continue with next
        while buf and t < fight_end:
            front = buf[0]
            remain = front.duration - (t - front.start)
            if remain <= 0:
                buf.pop(0)
                continue
            step = min(fight_end - t, remain)
            total += step
            t += step
        if t >= fight_end or i >= len(stacks):
            break
        # add next event (sorted by start) up to current t
        if not buf:
            # idle: jump to the next apply's start
            t = stacks[i].start
        while i < len(stacks) and stacks[i].start <= t:
            item = stacks[i]
            i += 1
            if len(buf) < cap:
                buf.append(item)
            else:
                # overflow: QueueLogic.FindLowestValue drops the shortest (not the front)
                not_front = buf[1:]
                shortest = min(not_front, key=lambda s: s.duration, default=None)
                if shortest is not None:
                    idx = buf.index(shortest)
                    buf[idx] = item
    return total


def main() -> int:
    stem = sys.argv[1] if len(sys.argv) > 1 else "20260128-160105"
    account = sys.argv[2] if len(sys.argv) > 2 else "Mikey.4982@3731"
    log_path = LOGS / f"{stem}.zevtc"
    candidates = sorted(EI_OUT.glob(f"{stem}_detailed_wvw*.json"))
    if not log_path.exists() or not candidates:
        print(f"missing log/EI for {stem}")
        return 1

    raw = read_zevtc_archive(log_path)
    parser = PythonEvtcParser()
    fight = next(parser.parse(raw))
    events = list(parser.parse_events(raw))
    expected = json.loads(candidates[0].read_text())
    header = fight.header
    duration_ms = header.duration_ms if header and header.duration_ms else 0
    origin = (
        header.start_time_ms
        if header and header.start_time_ms is not None
        else (min(e.time_ms for e in events) if events else 0)
    )

    # find agent ids for the account
    logger = getattr(fight, "agents", [])  # noqa
    ei_acct = account.split("@")[0]
    agent_ids = {
        a.id for a in fight.agents if a.account_name and a.account_name.lstrip(":") == ei_acct
    }
    print(f"account={account} agent_ids={sorted(agent_ids)} fight={duration_ms}ms")

    # collect the swiftness stream for those agents, chronologically
    stream = []
    for e in events:
        if e.target_agent_id in agent_ids and _get_buff_name(e.skill_id) == "swiftness":
            stream.append(e)
    print(f"swiftness events: {len(stream)}")

    # (a) current tracker
    tracker = BuffStateTracker(start_time_ms=origin)
    for e in events:
        if isinstance(e, (BoonApplyEvent, BuffApplyEvent, BuffExtensionEvent)):
            tracker.process(e)
    cur = tracker.compute_player_uptimes(next(iter(agent_ids)), duration_ms)["swiftness"]
    print(f"(a) current tracker : {cur:.3f}")

    # (b) EI queue port: each apply/refresh adds a fresh full-duration stack
    stacks: list[EIStackItem] = []
    for e in sorted(stream, key=lambda e: e.time_ms):
        if (isinstance(e, BoonApplyEvent) and e.kind == "apply") or isinstance(e, BuffApplyEvent):
            stacks.append(EIStackItem(e.time_ms - origin, e.duration_ms))
    stacks.sort(key=lambda s: s.start)
    ei_ms = ei_queue_uptime(stacks, duration_ms)
    print(f"(b) EI queue port   : {min(100.0, ei_ms / duration_ms * 100):.3f}")

    # EI recorded value
    for p in expected.get("players", []):
        if p.get("account", "").split("@")[0] != account.split("@")[0]:
            continue
        for bu in p.get("buffUptimes", []):
            if bu.get("id") == SWIFT:
                print(f"(EI recorded)       : {bu['buffData'][0]['uptime']:.3f}")
                return 0
    print("(EI recorded)       : not found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
