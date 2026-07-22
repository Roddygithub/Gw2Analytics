"""Generate a valid sample.zevtc with a commander [CMDR] agent.

Creates:
- 2 player agents: one commander (is_commander=True via [CMDR] tag),
  one regular player
- 3 damage events: commander→target, player→target, player→target
- Position events for both players
- Output: sample.zevtc at the project root
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apps.api.tests.routes._evtc_builder import (
    build_2025_string,
    make_cbtevent,
    make_minimal_zevtc,
)

COMMANDER_ID = 1001
PLAYER_ID = 1002
TARGET_ID = 2000
DAMAGE_SKILL = 99901
HEAL_SKILL = 99902
BOON_SKILL = 99903
STRIP_SKILL = 99904


def main() -> None:
    suffix = "a1b2c3d4"
    blob = make_minimal_zevtc(
        agents=[
            # Commander: Warrior/Berserker, [CMDR] name tag
            (COMMANDER_ID, 2, 18, f"Commander {suffix} [CMDR]", True),
            # Regular player: Guardian/Firebrand
            (PLAYER_ID, 1, 62, f"Player {suffix}", True),
        ],
        build=build_2025_string(suffix),
        skills=[
            (DAMAGE_SKILL, "Slash"),
            (HEAL_SKILL, "Heal"),
            (BOON_SKILL, "Might"),
            (STRIP_SKILL, "Strip"),
        ],
        events=[
            # Commander damages target at t=1s
            make_cbtevent(1_000, src=COMMANDER_ID, dst=TARGET_ID, value=500, skill_id=DAMAGE_SKILL),
            # Player damages target at t=2s and t=3s
            make_cbtevent(2_000, src=PLAYER_ID, dst=TARGET_ID, value=300, skill_id=DAMAGE_SKILL),
            make_cbtevent(3_000, src=PLAYER_ID, dst=TARGET_ID, value=200, skill_id=DAMAGE_SKILL),
            # Commander heals player at t=4s
            make_cbtevent(4_000, src=COMMANDER_ID, dst=PLAYER_ID, value=800, skill_id=HEAL_SKILL, is_nondamage=1),
            # Player applies boon (Might) to commander at t=5s, 6s
            make_cbtevent(5_000, src=PLAYER_ID, dst=COMMANDER_ID, value=740, skill_id=BOON_SKILL, is_nondamage=1),
            make_cbtevent(6_000, src=PLAYER_ID, dst=COMMANDER_ID, value=740, skill_id=BOON_SKILL, is_nondamage=1),
            # Commander strips Might from target at t=7s
            make_cbtevent(7_000, src=COMMANDER_ID, dst=TARGET_ID, value=740, skill_id=STRIP_SKILL, is_nondamage=1),
        ],
    )

    out_path = Path(__file__).resolve().parent.parent / "sample.zevtc"
    out_path.write_bytes(blob)
    print(f"✅ sample.zevtc written: {len(blob)} bytes → {out_path}")
    print(f"   Commander: agent_id={COMMANDER_ID}, name='Commander {suffix} [CMDR]'")
    print(f"   Player:    agent_id={PLAYER_ID}, name='Player {suffix}'")
    print(f"   3 damage events, 2 agents, 2 skills")

if __name__ == "__main__":
    main()
