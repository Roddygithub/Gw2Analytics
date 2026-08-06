"""Per-player buff state tracker for boon uptime + outgoing boon generation.

Phase C v0.11.0: foundation for the 14 boon uptime columns + 13 outgoing
boon columns in ``OrmFightPlayerSummary`` (plan 172 Phase B).

Algorithm
=========
1. Maintain per-agent per-buff stack expirations + last-update timestamp.
2. Process ``BoonApplyEvent`` stream chronologically (events are assumed
   to be in ascending ``time_ms`` order per the parser emit contract).
3. Before each state change, compute the elapsed time since the last
   event for that (agent, buff) pair and accumulate stack-time:
   ``cumulative_stack_ms += current_stacks * delta_time_ms``.
4. Expire stacks at the duration encoded by arcdps, even when no explicit
   removal event follows.
5. Duration boons report percentage uptime; intensity boons report their
   average stack count, matching Elite Insights.
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

import math
from collections import defaultdict

from pydantic import BaseModel, ConfigDict

from gw2_core import BoonApplyEvent, BuffApplyEvent, BuffExtensionEvent, BuffStackActiveEvent

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

#: Maximum stacks per buff. Most boons cap at 1; intensity boons cap at 25.
MAX_STACKS: dict[str, int] = {
    "might": 25,
    "stability": 25,
}
_CAPACITIES = {
    "might": 25,
    "stability": 25,
    "regeneration": 5,
    "stealth": 5,
    "fury": 99,
    "quickness": 99,
    "protection": 99,
    "vigor": 99,
    "swiftness": 99,
    "resistance": 99,
    "resolution": 99,
}
# All other boons default to 1 stack max (handled in compute logic).


class PlayerBuffUptimeOut(BaseModel):
    """One player's boon uptime + outgoing generation results.

    All fields are nullable so pre-migration rows keep NULL
    (frontend treats NULL as "unavailable").
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_id: int
    # Duration boons use percentages; intensity boons use average stacks.
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


def _capacity_for(name: str) -> int:
    return _CAPACITIES.get(name, 9)


class _BuffStack:
    """Mutable per-(agent, buff) stack tracking state."""

    def __init__(self, name: str) -> None:
        self.expirations: list[int | None] = []
        self.stack_ids: list[int] = []
        self.healing_scores: list[int] = []
        self.last_time_ms: int = 0
        self.cumulative_stack_ms: int = 0
        self.name: str = name


class _OutgoingAccumulator:
    """Mutable per-(agent, buff) outgoing boon generation accumulator."""

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

    def __init__(
        self, start_time_ms: int = 0, healing_by_agent: dict[int, int] | None = None
    ) -> None:
        # Per-agent per-buff stack state.
        # {agent_id: {buff_name: _BuffStack}}
        self._agent_buffs: dict[int, dict[str, _BuffStack]] = defaultdict(dict)
        # Outgoing: {source_agent_id: {buff_name: _OutgoingAccumulator}}
        self._outgoing: dict[int, dict[str, _OutgoingAccumulator]] = defaultdict(
            lambda: defaultdict(_OutgoingAccumulator),
        )
        self._start_time_ms = start_time_ms
        self._healing_by_agent = healing_by_agent or {}
        # Elite Insights keeps its HealingLogic on a single shared instance,
        # so the first stack-active record anywhere in the log latches its
        # "stop sorting" flag for *every* actor, permanently. The flag is
        # therefore tracker-wide rather than per (agent, buff): scoping it
        # per player leaves regeneration sorted long after EI stopped, and
        # a differently ordered queue evicts a different stack on overflow.
        self._healing_no_sort = False

    def _get_stack(self, agent_id: int, buff_name: str) -> _BuffStack:
        """Get or create the stack tracker for (agent, buff)."""
        agent = self._agent_buffs[agent_id]
        if buff_name not in agent:
            agent[buff_name] = _BuffStack(buff_name)
        return agent[buff_name]

    @staticmethod
    def _advance(stack: _BuffStack, new_time_ms: int) -> None:
        """Accumulate stack-time through expirations up to ``new_time_ms``."""
        if _max_stacks_for(stack.name) == 1:
            elapsed = new_time_ms - stack.last_time_ms
            while elapsed > 0 and stack.expirations:
                remaining = stack.expirations[0]
                if remaining is None:
                    stack.cumulative_stack_ms += elapsed
                    break
                active = min(elapsed, remaining)
                stack.cumulative_stack_ms += active
                elapsed -= active
                remaining -= active
                if remaining == 0:
                    stack.expirations.pop(0)
                    stack.stack_ids.pop(0)
                    stack.healing_scores.pop(0)
                else:
                    stack.expirations[0] = remaining
            stack.last_time_ms = new_time_ms
            return
        while True:
            next_expiry = min(
                (expiry for expiry in stack.expirations if expiry is not None),
                default=None,
            )
            if next_expiry is None or next_expiry >= new_time_ms:
                break
            stack.cumulative_stack_ms += len(stack.expirations) * (next_expiry - stack.last_time_ms)
            stack.last_time_ms = next_expiry
            index = stack.expirations.index(next_expiry)
            stack.expirations.pop(index)
            stack.stack_ids.pop(index)
            stack.healing_scores.pop(index)
        stack.cumulative_stack_ms += len(stack.expirations) * (new_time_ms - stack.last_time_ms)
        stack.last_time_ms = new_time_ms

    def _relative_time(self, time_ms: int) -> int:
        return max(0, time_ms - self._start_time_ms)

    def end_agent(self, agent_id: int, time_ms: int) -> None:
        """Advance and clear every tracked buff when an agent despawns."""
        for stack in self._agent_buffs.get(agent_id, {}).values():
            self._advance(stack, self._relative_time(time_ms))
            stack.expirations.clear()
            stack.stack_ids.clear()
            stack.healing_scores.clear()

    def process(  # noqa: PLR0912, PLR0915
        self,
        event: BoonApplyEvent | BuffApplyEvent | BuffExtensionEvent | BuffStackActiveEvent,
    ) -> None:
        """Process one ``BoonApplyEvent`` or ``BuffApplyEvent`` and update state.

        Events MUST be in chronological order (ascending ``time_ms``).
        Untracked buff IDs (not in ``TRACKED_BUFFS``) are silently ignored.

        Raises:
            TypeError: if ``event`` is not a ``BoonApplyEvent`` or ``BuffApplyEvent``.
        """
        if isinstance(event, BuffStackActiveEvent):
            buff_name = _get_buff_name(event.skill_id)
            if buff_name != "regeneration":
                return
            stack = self._get_stack(event.target_agent_id, buff_name)
            self._advance(stack, self._relative_time(event.time_ms))
            if event.stack_id in stack.stack_ids:
                index = stack.stack_ids.index(event.stack_id)
                expiry = stack.expirations.pop(index)
                stack_id = stack.stack_ids.pop(index)
                healing = stack.healing_scores.pop(index)
                if stack.expirations and (stack.expirations[0] or 0) < 50:
                    stack.expirations[0] = expiry
                    stack.stack_ids[0] = stack_id
                    stack.healing_scores[0] = healing
                else:
                    stack.expirations.insert(0, expiry)
                    stack.stack_ids.insert(0, stack_id)
                    stack.healing_scores.insert(0, healing)
                self._healing_no_sort = True
            return
        if isinstance(event, BuffApplyEvent):
            self._process_buff_apply(event)
            return
        if isinstance(event, BuffExtensionEvent):
            self._process_buff_extension(event)
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
        time_ms = self._relative_time(event.time_ms)
        self._advance(target_tracker, time_ms)

        if event.kind == "apply":
            if _max_stacks_for(buff_name) > 1:
                target_tracker.expirations.extend([time_ms + event.duration_ms] * event.stacks)
                target_tracker.stack_ids.extend([event.stack_id] * event.stacks)
                target_tracker.healing_scores.extend(
                    [self._healing_by_agent.get(event.source_agent_id, 0)] * event.stacks
                )
                pairs = sorted(
                    zip(
                        target_tracker.expirations,
                        target_tracker.stack_ids,
                        target_tracker.healing_scores,
                        strict=True,
                    )
                )
                pairs = pairs[-_capacity_for(buff_name) :]
                target_tracker.expirations = [expiry for expiry, _, _ in pairs]
                target_tracker.stack_ids = [stack_id for _, stack_id, _ in pairs]
                target_tracker.healing_scores = [healing for _, _, healing in pairs]
            elif buff_name == "regeneration":
                # EI BuffSimulatorDuration + HealingLogic: capacity-5
                # queue, replace the lowest-heal stack on overflow
                # (wasting its remaining duration), re-sort by healing
                # until the first added_active apply pins no_sort, then
                # activate: move the new stack to the front (or replace
                # the active stack outright when it has <50 ms left).
                new_duration = event.duration_ms or None
                new_healing = self._healing_by_agent.get(event.source_agent_id, 0)
                if len(target_tracker.expirations) >= _capacity_for(buff_name):
                    target_tracker.expirations[-1] = new_duration
                    target_tracker.stack_ids[-1] = event.stack_id
                    target_tracker.healing_scores[-1] = new_healing
                else:
                    target_tracker.expirations.append(new_duration)
                    target_tracker.stack_ids.append(event.stack_id)
                    target_tracker.healing_scores.append(new_healing)
                if not self._healing_no_sort:
                    pairs = sorted(
                        zip(
                            target_tracker.expirations,
                            target_tracker.stack_ids,
                            target_tracker.healing_scores,
                            strict=True,
                        ),
                        key=lambda pair: pair[2],
                        reverse=True,
                    )
                    target_tracker.expirations = [expiry for expiry, _, _ in pairs]
                    target_tracker.stack_ids = [stack_id for _, stack_id, _ in pairs]
                    target_tracker.healing_scores = [healing for _, _, healing in pairs]
                if event.added_active and event.stack_id in target_tracker.stack_ids:
                    # An apply flagged active only moves its stack to the
                    # front. Elite Insights reaches the richer rule -- replace
                    # a nearly-spent active stack, and pin the ordering with
                    # ``no_sort`` -- through the *other* Activate overload,
                    # which only the explicit stack-active record calls.
                    new_index = target_tracker.stack_ids.index(event.stack_id)
                    target_tracker.expirations.insert(0, target_tracker.expirations.pop(new_index))
                    target_tracker.stack_ids.insert(0, target_tracker.stack_ids.pop(new_index))
                    target_tracker.healing_scores.insert(
                        0, target_tracker.healing_scores.pop(new_index)
                    )
            else:
                target_tracker.expirations.append(event.duration_ms or None)
                target_tracker.stack_ids.append(event.stack_id)
                target_tracker.healing_scores.append(
                    self._healing_by_agent.get(event.source_agent_id, 0)
                )
                del target_tracker.expirations[_capacity_for(buff_name) :]
                del target_tracker.stack_ids[_capacity_for(buff_name) :]
                del target_tracker.healing_scores[_capacity_for(buff_name) :]
        elif event.kind == "remove_single":
            if _max_stacks_for(buff_name) == 1 and target_tracker.expirations:
                stack_index = next(
                    (
                        i
                        for i, stack_id in enumerate(target_tracker.stack_ids)
                        if event.stack_id and stack_id == event.stack_id
                    ),
                    None,
                )
                if stack_index is None:
                    stack_index = next(
                        (
                            i
                            for i, duration in enumerate(target_tracker.expirations)
                            if duration is not None and abs(duration - event.duration_ms) < 15
                        ),
                        None,
                    )
                if stack_index is not None:
                    target_tracker.expirations.pop(stack_index)
                    target_tracker.stack_ids.pop(stack_index)
                    target_tracker.healing_scores.pop(stack_index)
            elif event.stacks and target_tracker.expirations:
                index = next(
                    (
                        i
                        for i, stack_id in enumerate(target_tracker.stack_ids)
                        if event.stack_id and stack_id == event.stack_id
                    ),
                    0,
                )
                target_tracker.expirations.pop(index)
                target_tracker.stack_ids.pop(index)
                target_tracker.healing_scores.pop(index)
        elif event.kind == "remove_all":
            target_tracker.expirations.clear()
            target_tracker.stack_ids.clear()
            target_tracker.healing_scores.clear()

        # --- Outgoing boon tracking (source-side) ---
        if event.kind == "apply" and event.source_agent_id != event.target_agent_id:
            self._outgoing[event.source_agent_id][buff_name].total_ms += (
                event.duration_ms * event.stacks
            )

    def _process_buff_apply(self, event: BuffApplyEvent) -> None:
        """Process a ``BuffApplyEvent`` (CBTS_BUFFAPPLY statechange).

        These are initial-stack snapshots: ``skill_id`` is the buff ID,
        and the event includes the active stack count and remaining duration.

        Outgoing generation is intentionally NOT tracked here. The
        statechange snapshot only records the presence of a buff on the
        target; the originating source is not part of the boon-generation
        contract, so crediting the source would be speculative.
        """
        buff_name = _get_buff_name(event.skill_id)
        if buff_name is None:
            return

        target_tracker = self._get_stack(event.target_agent_id, buff_name)
        time_ms = self._relative_time(event.time_ms)
        self._advance(target_tracker, time_ms)
        expiry = time_ms + event.duration_ms if event.duration_ms > 0 else None
        if _max_stacks_for(buff_name) > 1:
            target_tracker.expirations.extend([expiry] * event.stacks)
            target_tracker.stack_ids.extend([event.stack_id] * event.stacks)
            target_tracker.healing_scores.extend([0] * event.stacks)
            pairs = sorted(
                zip(
                    target_tracker.expirations,
                    target_tracker.stack_ids,
                    target_tracker.healing_scores,
                    strict=True,
                ),
                key=lambda pair: pair[0] if pair[0] is not None else math.inf,
            )[-_capacity_for(buff_name) :]
            target_tracker.expirations = [value for value, _, _ in pairs]
            target_tracker.stack_ids = [stack_id for _, stack_id, _ in pairs]
            target_tracker.healing_scores = [healing for _, _, healing in pairs]
        else:
            target_tracker.expirations.append(event.duration_ms or None)
            target_tracker.stack_ids.append(event.stack_id)
            target_tracker.healing_scores.append(0)
            del target_tracker.expirations[_capacity_for(buff_name) :]
            del target_tracker.stack_ids[_capacity_for(buff_name) :]
            del target_tracker.healing_scores[_capacity_for(buff_name) :]

    def _process_buff_extension(self, event: BuffExtensionEvent) -> None:
        buff_name = _get_buff_name(event.skill_id)
        if buff_name is None or event.extended_duration_ms < 1:
            return

        target_tracker = self._get_stack(event.target_agent_id, buff_name)
        time_ms = self._relative_time(event.time_ms)
        self._advance(target_tracker, time_ms)
        old_duration = event.new_duration_ms - event.extended_duration_ms
        if target_tracker.expirations and (
            old_duration > 0 or len(target_tracker.expirations) >= _capacity_for(buff_name)
        ):
            if target_tracker.expirations[0] is not None:
                target_tracker.expirations[0] += event.extended_duration_ms
            return
        target_tracker.expirations.append(event.new_duration_ms)
        target_tracker.stack_ids.append(event.stack_id)
        target_tracker.healing_scores.append(self._healing_by_agent.get(event.source_agent_id, 0))
        del target_tracker.expirations[_capacity_for(buff_name) :]
        del target_tracker.stack_ids[_capacity_for(buff_name) :]
        del target_tracker.healing_scores[_capacity_for(buff_name) :]

    def compute_player_uptimes(
        self, agent_id: int, duration_ms: int, active_duration_ms: int | None = None
    ) -> dict[str, float]:
        """Compute boon uptime for one player after processing all events.

        Duration boons return percentages; intensity boons return average stacks.
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
            # Advance a copy so repeated computations remain idempotent.
            snapshot = _BuffStack(name)
            snapshot.expirations = stack.expirations.copy()
            snapshot.stack_ids = stack.stack_ids.copy()
            snapshot.healing_scores = stack.healing_scores.copy()
            snapshot.last_time_ms = stack.last_time_ms
            snapshot.cumulative_stack_ms = stack.cumulative_stack_ms
            self._advance(snapshot, min(duration_ms, active_duration_ms or duration_ms))
            if _max_stacks_for(name) > 1:
                result[name] = snapshot.cumulative_stack_ms / duration_ms
            else:
                result[name] = min(
                    100.0,
                    (snapshot.cumulative_stack_ms / duration_ms) * 100.0,
                )
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
