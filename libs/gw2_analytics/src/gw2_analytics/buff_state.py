"""Per-player buff state tracker for boon uptime + outgoing boon generation.

Phase C v0.11.0: foundation for the 14 boon uptime columns + 13 outgoing
boon columns in ``OrmFightPlayerSummary`` (plan 172 Phase B).

Algorithm
=========
1. Maintain per-agent per-buff stack count + last-update timestamp.
2. Process ``BoonApplyEvent`` stream chronologically (events are assumed
   to be in ascending ``time_ms`` order per the parser emit contract).
3. Before each state change, compute the elapsed time since the last
   event for that (agent, buff) pair and accumulate stack-time:
   ``cumulative_stack_ms += current_stacks * delta_time_ms``.
4. After processing all events, compute the tail period from the last
   event timestamp to the fight duration.
5. Uptime = ``cumulative_stack_ms / (duration_ms * max_stacks)`` where
   ``max_stacks`` is the maximum number of stacks a buff can have
   (1 for most boons, 25 for might).
6. Outgoing: on ``BoonApplyEvent`` where ``source != target``, accumulate
   ``duration_ms * stacks`` applied to others.

Tracked buffs
=============
The 14 GW2 boons tracked by WvW_Analytics, identified by their arcdps
skill_id. ``max_stacks`` is per the GW2 wiki:
- might: 25 stacks
- all others: 1 stack (boons don't stack beyond 1 application)
"""

from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel, ConfigDict

from gw2_core import BoonApplyEvent, BuffApplyEvent

#: The 14 tracked boons: name → arcdps skill_id.
#: Source: WvW_Analytics TRACKED_BUFFS mapping.
TRACKED_BUFFS: dict[str, int] = {
    "might": 740,
    "fury": 725,
    "quickness": 1187,
    "alacrity": 30328,
    "protection": 717,
    "regeneration": 718,
    "vigor": 726,
    "aegis": 743,
    "stability": 1122,
    "swiftness": 719,
    "resistance": 26980,
    "resolution": 873,
    "superspeed": 5974,
    "stealth": 13017,
}

#: Reverse lookup: skill_id → buff name.
BUFF_NAME_BY_ID: dict[int, str] = {v: k for k, v in TRACKED_BUFFS.items()}

#: Maximum stacks per buff. Most boons cap at 1; might caps at 25.
MAX_STACKS: dict[str, int] = {
    "might": 25,
}
# All other boons default to 1 stack max (handled in compute logic).


class PlayerBuffUptimeOut(BaseModel):
    """One player's boon uptime + outgoing generation results.

    All fields are nullable so pre-migration rows keep NULL
    (frontend treats NULL as "unavailable").
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_id: int
    # Uptime percentages [0.0, 100.0] for each tracked buff.
    might_uptime: float | None = None
    fury_uptime: float | None = None
    quickness_uptime: float | None = None
    alacrity_uptime: float | None = None
    protection_uptime: float | None = None
    regeneration_uptime: float | None = None
    vigor_uptime: float | None = None
    aegis_uptime: float | None = None
    stability_uptime: float | None = None
    swiftness_uptime: float | None = None
    resistance_uptime: float | None = None
    resolution_uptime: float | None = None
    superspeed_uptime: float | None = None
    stealth_uptime: float | None = None
    # Outgoing boon generation (total stack-ms applied to other players).
    outgoing_might: int | None = None
    outgoing_fury: int | None = None
    outgoing_quickness: int | None = None
    outgoing_alacrity: int | None = None
    outgoing_protection: int | None = None
    outgoing_regeneration: int | None = None
    outgoing_vigor: int | None = None
    outgoing_aegis: int | None = None
    outgoing_stability: int | None = None
    outgoing_swiftness: int | None = None
    outgoing_resistance: int | None = None
    outgoing_resolution: int | None = None
    outgoing_superspeed: int | None = None
    outgoing_stealth: int | None = None


def _get_buff_name(skill_id: int) -> str | None:
    """Return the tracked buff name for ``skill_id``, or ``None`` if untracked."""
    return BUFF_NAME_BY_ID.get(skill_id)


def _max_stacks_for(name: str) -> int:
    """Return the maximum stack count for a tracked buff."""
    return MAX_STACKS.get(name, 1)


class _BuffStack:
    """Mutable per-(agent, buff) stack tracking state."""

    __slots__ = ("cumulative_stack_ms", "last_time_ms", "name", "stacks")

    def __init__(self, name: str) -> None:
        self.stacks: int = 0
        self.last_time_ms: int = 0
        self.cumulative_stack_ms: int = 0
        self.name: str = name


class _OutgoingAccumulator:
    """Mutable per-(agent, buff) outgoing boon generation accumulator."""

    __slots__ = ("total_ms",)

    def __init__(self) -> None:
        self.total_ms: int = 0


class BuffStateTracker:
    """Tracks per-player buff stack state from a stream of ``BoonApplyEvent``
    and ``BuffApplyEvent``.

    Usage::

        tracker = BuffStateTracker()
        for event in boon_apply_events:
            tracker.process(event)
        uptimes = tracker.compute_all_uptimes(fight_duration_s)
        outgoing = tracker.compute_all_outgoing(fight_duration_s)

    Instantiate once per fight; call ``process(event)`` for each event.
    Events MUST be in chronological order (ascending ``time_ms``).
    """

    def __init__(self) -> None:
        # Per-agent per-buff stack state.
        # {agent_id: {buff_name: _BuffStack}}
        self._agent_buffs: dict[int, dict[str, _BuffStack]] = defaultdict(dict)
        # Outgoing: {source_agent_id: {buff_name: _OutgoingAccumulator}}
        self._outgoing: dict[int, dict[str, _OutgoingAccumulator]] = defaultdict(
            lambda: defaultdict(_OutgoingAccumulator),
        )

    def _get_stack(self, agent_id: int, buff_name: str) -> _BuffStack:
        """Get or create the stack tracker for (agent, buff)."""
        agent = self._agent_buffs[agent_id]
        if buff_name not in agent:
            agent[buff_name] = _BuffStack(buff_name)
        return agent[buff_name]

    def _accumulate_uptime(self, stack: _BuffStack, new_time_ms: int) -> None:
        """Accumulate stack-time for the period ``[stack.last_time_ms, new_time_ms)``."""
        if stack.last_time_ms < new_time_ms and stack.stacks > 0:
            delta = new_time_ms - stack.last_time_ms
            stack.cumulative_stack_ms += stack.stacks * delta

    def process(self, event: BoonApplyEvent | BuffApplyEvent) -> None:
        """Process one ``BoonApplyEvent`` or ``BuffApplyEvent`` and update state.

        Events MUST be in chronological order (ascending ``time_ms``).
        Untracked buff IDs (not in ``TRACKED_BUFFS``) are silently ignored.

        Raises:
            TypeError: if ``event`` is not a ``BoonApplyEvent`` or ``BuffApplyEvent``.
        """
        if isinstance(event, BuffApplyEvent):
            self._process_buff_apply(event)
            return
        if not isinstance(event, BoonApplyEvent):
            raise TypeError(
                f"Expected BoonApplyEvent or BuffApplyEvent, got {type(event).__name__}"
            )

        buff_name = _get_buff_name(event.skill_id)
        if buff_name is None:
            return  # untracked buff, skip

        # --- Self-uptime tracking (target-side) ---
        target_tracker = self._get_stack(event.target_agent_id, buff_name)
        self._accumulate_uptime(target_tracker, event.time_ms)

        if event.kind == "apply":
            target_tracker.stacks += event.stacks
        elif event.kind == "remove_single":
            target_tracker.stacks = max(0, target_tracker.stacks - 1)
        elif event.kind == "remove_all":
            target_tracker.stacks = 0

        target_tracker.last_time_ms = event.time_ms

        # --- Outgoing boon tracking (source-side) ---
        if event.source_agent_id != event.target_agent_id:
            self._outgoing[event.source_agent_id][buff_name].total_ms += (
                event.duration_ms * event.stacks
            )

    def _process_buff_apply(self, event: BuffApplyEvent) -> None:
        """Process a ``BuffApplyEvent`` (CBTS_BUFFAPPLY statechange).

        These are initial-stack snapshots: ``skill_id`` is the buff ID,
        and the event marks the target as having the buff active. Treat
        this as setting the stack count to 1 (arcdps doesn't encode the
        stack count on BUFFAPPLY statechanges).

        Outgoing generation is intentionally NOT tracked here. The
        statechange snapshot only records the presence of a buff on the
        target; the originating source is not part of the boon-generation
        contract, so crediting the source would be speculative.
        """
        buff_name = _get_buff_name(event.skill_id)
        if buff_name is None:
            return

        target_tracker = self._get_stack(event.target_agent_id, buff_name)
        self._accumulate_uptime(target_tracker, event.time_ms)

        target_tracker.stacks = max(1, target_tracker.stacks)

        target_tracker.last_time_ms = event.time_ms

    def compute_player_uptimes(self, agent_id: int, duration_ms: int) -> dict[str, float]:
        """Compute uptime percentages for one player after processing all events.

        Returns a dict mapping buff_name → uptime_pct [0.0, 100.0].
        Buffs not present for this player return 0.0.
        """
        if duration_ms <= 0:
            return {}

        agent = self._agent_buffs.get(agent_id, {})
        result: dict[str, float] = {}
        for name in TRACKED_BUFFS:
            stack = agent.get(name)
            if stack is None:
                result[name] = 0.0
                continue
            # Add tail using a local copy so repeated calls remain idempotent.
            total_cumulative_ms = stack.cumulative_stack_ms
            if stack.last_time_ms < duration_ms and stack.stacks > 0:
                tail_delta = duration_ms - stack.last_time_ms
                total_cumulative_ms += stack.stacks * tail_delta
            max_st = _max_stacks_for(name)
            max_possible = duration_ms * max_st
            if max_possible > 0:
                result[name] = min(100.0, (total_cumulative_ms / max_possible) * 100.0)
            else:
                result[name] = 0.0
        return result

    def compute_all_uptimes(self, duration_s: float) -> dict[int, dict[str, float]]:
        """Compute uptime percentages for all tracked players.

        Returns ``{agent_id: {buff_name: uptime_pct}}``.
        """
        duration_ms = int(duration_s * 1000)
        if duration_ms <= 0:
            return {}
        return {
            aid: self.compute_player_uptimes(aid, duration_ms)
            for aid in list(self._agent_buffs.keys())
        }

    def compute_player_outgoing(self, agent_id: int, duration_s: float) -> dict[str, int]:
        """Compute outgoing boon generation (total stack-ms) for one player.

        Returns a dict mapping buff_name → total_stack_ms.
        Buffs not applied by this player return 0.
        """
        _ = duration_s  # unused, outgoing is an absolute total
        agent_out = self._outgoing.get(agent_id, {})
        result: dict[str, int] = {}
        for name in TRACKED_BUFFS:
            acc = agent_out.get(name)
            result[name] = acc.total_ms if acc else 0
        return result

    def compute_all_outgoing(self, duration_s: float) -> dict[int, dict[str, int]]:
        """Compute outgoing boon generation for all tracked players.

        Returns ``{agent_id: {buff_name: total_stack_ms}}``.
        """
        return {
            aid: self.compute_player_outgoing(aid, duration_s)
            for aid in list(self._outgoing.keys())
        }

    @staticmethod
    def uptime_to_pct(cumulative_stack_ms: int, duration_ms: int, max_stacks: int = 1) -> float:
        """Convert cumulative stack-ms to a 0-100 percentage."""
        if duration_ms <= 0 or max_stacks <= 0:
            return 0.0
        return min(100.0, (cumulative_stack_ms / (duration_ms * max_stacks)) * 100.0)


__all__ = [
    "BUFF_NAME_BY_ID",
    "MAX_STACKS",
    "TRACKED_BUFFS",
    "BuffStateTracker",
    "PlayerBuffUptimeOut",
]
