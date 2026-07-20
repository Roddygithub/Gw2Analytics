"""Fight context heuristic: classify fights by ally count.

Ported from WvW_Analytics ``context_detector.py``. The classification
is a simple ally-count heuristic:

- >= 30 allies → ZERG
- >= 10 allies → GUILD_RAID
- else → ROAM

The ally count is the number of ``OrmFightAgent`` rows where
``is_player=True`` (the player count from the fight header).
"""

from __future__ import annotations

ZERG_THRESHOLD: int = 30
GUILD_RAID_THRESHOLD: int = 10


def classify_fight_context(ally_count: int) -> str:
    """Return the context label for a fight with the given ally count."""
    if ally_count >= ZERG_THRESHOLD:
        return "zerg"
    if ally_count >= GUILD_RAID_THRESHOLD:
        return "guild_raid"
    return "roam"
