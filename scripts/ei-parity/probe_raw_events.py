#!/usr/bin/env python3
"""Dump the full raw cbtevent fields for one (agent, skill) pair."""

from __future__ import annotations

import struct
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOGS = ROOT / "zevtc files"

from gw2_evtc_parser import PythonEvtcParser, read_zevtc_archive  # noqa: E402
from gw2_evtc_parser.parser import (  # noqa: E402
    BUILD_OFFSET,
    EVENT_SIZE,
    _build_version_from_build_str,
    _compute_post_skills_offset,
)

FULL = struct.Struct("<QQQiiIIHHHH16B")

stem, account, skill = sys.argv[1], sys.argv[2], int(sys.argv[3])
raw = read_zevtc_archive(LOGS / f"{stem}.zevtc")
fight = next(PythonEvtcParser().parse(raw))
agent_ids = {a.id for a in fight.agents if (a.account_name or "").lstrip(":") == account}
print("agent ids:", agent_ids)

build = raw[BUILD_OFFSET : BUILD_OFFSET + 8].decode("ascii", "replace")
is2025 = _build_version_from_build_str(build) >= 2025_00_00
cursor = _compute_post_skills_offset(raw, is_evtc_2025=is2025)

profile: Counter[tuple] = Counter()
rows = []
while cursor + EVENT_SIZE <= len(raw):
    (
        t,
        src,
        dst,
        value,
        buff_dmg,
        overstack,
        sid,
        src_i,
        dst_i,
        src_mi,
        dst_mi,
        *flags,
    ) = FULL.unpack_from(raw, cursor)
    cursor += EVENT_SIZE
    if sid != skill or src not in agent_ids:
        continue
    iff, ev_buff, result, is_activation, is_buffremove = flags[0:5]
    is_ninety, is_fifty, is_moving, is_statechange = flags[5:9]
    is_flanking, is_shields, is_offcycle = flags[9:12]
    if is_statechange:
        continue
    profile[(result, value, buff_dmg, overstack > 0, is_shields, is_offcycle, ev_buff)] += 1
    rows.append((t, result, value, buff_dmg, overstack, is_shields, is_offcycle, ev_buff))

print(
    f"\n{'result':>7}{'value':>8}{'buffDmg':>9}{'overstk>0':>11}"
    f"{'shields':>9}{'offcyc':>8}{'ev.buff':>9}  count"
)
for key, n in sorted(profile.items(), key=lambda kv: -kv[1]):
    r, v, bd, ov, sh, oc, eb = key
    print(f"{r:>7}{v:>8}{bd:>9}{ov!s:>11}{sh:>9}{oc:>8}{eb:>9}  {n}")

print("\nfirst rows (time, result, value, buffDmg, overstack, shields, offcycle, ev.buff):")
for row in rows[:20]:
    print("   ", row)
