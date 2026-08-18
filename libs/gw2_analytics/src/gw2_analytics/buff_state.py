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

#: Intensity buffs that use Elite Insights' OverrideLogic (sort by TotalDuration,
#: drop shortest on overflow, graft extensions by closest TotalDuration).
_OVERRIDE_LOGIC_BUFFS: frozenset[str] = frozenset({"might", "stability"})

#: Single-stack duration boons that use Elite Insights' QueueLogic (capacity 9,
#: only front stack counts toward uptime, drop shortest on overflow,
#: graft extensions by closest duration, added_active moves to front).
#: Regeneration uses its own special queue logic; might/stability use OverrideLogic.
_QUEUE_LOGIC_BUFFS: frozenset[str] = frozenset(
    {
        "fury",
        "quickness",
        "alacrity",
        "protection",
        "vigor",
        "aegis",
        "swiftness",
        "resistance",
        "resolution",
        "superspeed",
        "stealth",
    }
)

_CAPACITIES = {
    "might": 25,
    "stability": 25,
    "regeneration": 5,
    "stealth": 9,
    "fury": 9,
    "quickness": 9,
    "alacrity": 9,
    "protection": 9,
    "vigor": 9,
    "aegis": 9,
    "swiftness": 9,
    "resistance": 9,
    "resolution": 9,
    "superspeed": 9,
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
        # TotalDuration = base + extensions (for OverrideLogic)
        self.total_durations: list[int] = []
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
        self,
        start_time_ms: int = 0,
        healing_by_agent: dict[int, int] | None = None,
        regen_overstacks: dict[int, list[tuple[int, int, int]]] | None = None,
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
        # ``{agent_id: [(time_ms, removed_duration_ms, buff_instance)]}`` from
        # :func:`gw2_evtc_parser.scan_regeneration_overstacks`. arcdps names
        # the regeneration stack an application displaced; without it the
        # queue can only guess, and guessing evicts a long stack where the
        # game dropped a spent one. ``_regen_hint_cursor`` walks each list
        # once, since applications arrive in order.
        self._regen_overstacks = regen_overstacks or {}
        self._regen_hint_cursor: dict[int, int] = {}

    def _get_stack(self, agent_id: int, buff_name: str) -> _BuffStack:
        """Get or create the stack tracker for (agent, buff)."""
        agent = self._agent_buffs[agent_id]
        if buff_name not in agent:
            agent[buff_name] = _BuffStack(buff_name)
        return agent[buff_name]

    @staticmethod
    def _advance_single(stack: _BuffStack, new_time_ms: int) -> None:
        """Accumulate stack-time for single-stack (max_stacks=1) through expirations."""
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
                if stack.total_durations:
                    stack.total_durations.pop(0)
                stack.stack_ids.pop(0)
                stack.healing_scores.pop(0)
            else:
                stack.expirations[0] = remaining
        stack.last_time_ms = new_time_ms

    @staticmethod
    def _advance_queue(stack: _BuffStack, new_time_ms: int) -> None:
        """Accumulate stack-time for QueueLogic (only front stack counts)."""
        # QueueLogic uses the same front-stack consumption logic as single-stack
        BuffStateTracker._advance_single(stack, new_time_ms)

    @staticmethod
    def _advance_intensity(stack: _BuffStack, new_time_ms: int) -> None:
        """Accumulate stack-time for intensity buffs (max_stacks > 1)."""
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
            if stack.total_durations:
                stack.total_durations.pop(index)
            stack.stack_ids.pop(index)
            stack.healing_scores.pop(index)
        stack.cumulative_stack_ms += len(stack.expirations) * (new_time_ms - stack.last_time_ms)
        stack.last_time_ms = new_time_ms

    @staticmethod
    def _advance(stack: _BuffStack, new_time_ms: int) -> None:
        """Accumulate stack-time through expirations up to ``new_time_ms``."""
        if _max_stacks_for(stack.name) == 1:
            if stack.name in _QUEUE_LOGIC_BUFFS:
                BuffStateTracker._advance_queue(stack, new_time_ms)
            else:
                BuffStateTracker._advance_single(stack, new_time_ms)
            return
        BuffStateTracker._advance_intensity(stack, new_time_ms)

    def _regen_overstack_hint(self, agent_id: int, time_ms: int) -> tuple[int, int] | None:
        """The displaced-stack hint arcdps recorded just before this apply."""
        hints = self._regen_overstacks.get(agent_id)
        if not hints:
            return None
        index = self._regen_hint_cursor.get(agent_id, 0)
        while index < len(hints) and hints[index][0] <= time_ms:
            index += 1
        self._regen_hint_cursor[agent_id] = index
        if index == 0:
            return None
        hint_time, removed_duration, buff_instance = hints[index - 1]
        # Elite Insights only pairs a removal with the application that
        # follows it inside one server delay.
        if time_ms - hint_time >= 10:
            return None
        return removed_duration, buff_instance

    def _regen_eviction_index(self, stack: _BuffStack, event: BoonApplyEvent) -> int:
        """Which queued regeneration stack this application displaces.

        Elite Insights' ``HealingLogic.FindLowestValue``: the stack whose
        buff instance arcdps named, else the one whose duration is closest
        to the removed one, else -- with nothing to go on -- the last.
        """
        hint = self._regen_overstack_hint(event.target_agent_id, event.time_ms)
        if hint is not None:
            removed_duration, buff_instance = hint
            if buff_instance and buff_instance in stack.stack_ids:
                return stack.stack_ids.index(buff_instance)
            if removed_duration > 0:
                return min(
                    range(len(stack.expirations)),
                    key=lambda i: abs((stack.expirations[i] or 0) - removed_duration),
                )
        return len(stack.expirations) - 1

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
            # QueueLogic buffs (single-stack duration boons with queue behavior)
            # are handled separately even though they have max_stacks=1.
            if buff_name in _QUEUE_LOGIC_BUFFS:
                # QueueLogic (EI): capacity 9, only front stack counts.
                # Add new stack to end; if at capacity, drop shortest (not front).
                duration = event.duration_ms if event.duration_ms > 0 else None
                if len(target_tracker.expirations) >= _capacity_for(buff_name):
                    # Find shortest duration (excluding front which is active)
                    # EI drops the shortest duration stack, not the front
                    if len(target_tracker.expirations) > 1:
                        # Find shortest among non-front stacks
                        min_idx = 1
                        min_dur = target_tracker.expirations[1]
                        for i in range(2, len(target_tracker.expirations)):
                            dur = target_tracker.expirations[i]
                            if dur is not None and (min_dur is None or dur < min_dur):
                                min_dur = dur
                                min_idx = i
                        target_tracker.expirations.pop(min_idx)
                        target_tracker.stack_ids.pop(min_idx)
                        target_tracker.healing_scores.pop(min_idx)
                    else:
                        # Only one stack, replace it
                        target_tracker.expirations.pop(0)
                        target_tracker.stack_ids.pop(0)
                        target_tracker.healing_scores.pop(0)
                target_tracker.expirations.append(duration)
                target_tracker.stack_ids.append(event.stack_id)
                target_tracker.healing_scores.append(
                    self._healing_by_agent.get(event.source_agent_id, 0)
                )
            elif _max_stacks_for(buff_name) > 1:
                if buff_name in _OVERRIDE_LOGIC_BUFFS:
                    # OverrideLogic (EI): sort by TotalDuration (shortest first),
                    # remove index 0 when at capacity.
                    # TotalDuration = base duration + extensions (initially just base).
                    for _ in range(event.stacks):
                        total_dur = event.duration_ms
                        # Binary search to find insertion index by TotalDuration
                        lo, hi = 0, len(target_tracker.total_durations)
                        while lo < hi:
                            mid = (lo + hi) // 2
                            if target_tracker.total_durations[mid] > total_dur:
                                hi = mid
                            else:
                                lo = mid + 1
                        insert_idx = lo
                        if len(target_tracker.total_durations) >= _capacity_for(buff_name):
                            # Remove shortest TotalDuration (index 0)
                            target_tracker.expirations.pop(0)
                            target_tracker.total_durations.pop(0)
                            target_tracker.stack_ids.pop(0)
                            target_tracker.healing_scores.pop(0)
                            if insert_idx > 0:
                                insert_idx -= 1
                        target_tracker.expirations.insert(insert_idx, time_ms + event.duration_ms)
                        target_tracker.total_durations.insert(insert_idx, total_dur)
                        target_tracker.stack_ids.insert(insert_idx, event.stack_id)
                        target_tracker.healing_scores.insert(
                            insert_idx, self._healing_by_agent.get(event.source_agent_id, 0)
                        )
                else:
                    # Other intensity buffs (stability): sort by expiration
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
                    victim = self._regen_eviction_index(target_tracker, event)
                    target_tracker.expirations[victim] = new_duration
                    target_tracker.stack_ids[victim] = event.stack_id
                    target_tracker.healing_scores[victim] = new_healing
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
                    # front when paired with an overstack hint (uncredited
                    # remove-single within 10 ms). Elite Insights reaches the
                    # richer rule -- replace a nearly-spent active stack, and
                    # pin the ordering with ``no_sort`` -- through the *other*
                    # Activate overload, which only the explicit stack-active
                    # record calls.
                    hint = self._regen_overstack_hint(event.target_agent_id, event.time_ms)
                    if hint is not None:
                        new_index = target_tracker.stack_ids.index(event.stack_id)
                        target_tracker.expirations.insert(
                            0, target_tracker.expirations.pop(new_index)
                        )
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
            if buff_name in _QUEUE_LOGIC_BUFFS and target_tracker.expirations:
                # QueueLogic: find stack by stack_id or closest duration
                stack_index = next(
                    (
                        i
                        for i, stack_id in enumerate(target_tracker.stack_ids)
                        if event.stack_id is not None and stack_id == event.stack_id
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
            elif _max_stacks_for(buff_name) == 1 and target_tracker.expirations:
                stack_index = next(
                    (
                        i
                        for i, stack_id in enumerate(target_tracker.stack_ids)
                        if event.stack_id is not None and stack_id == event.stack_id
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
                    if target_tracker.total_durations:
                        target_tracker.total_durations.pop(stack_index)
                    target_tracker.stack_ids.pop(stack_index)
                    target_tracker.healing_scores.pop(stack_index)
            elif event.stacks and target_tracker.expirations:
                index = next(
                    (
                        i
                        for i, stack_id in enumerate(target_tracker.stack_ids)
                        if event.stack_id is not None and stack_id == event.stack_id
                    ),
                    0,
                )
                target_tracker.expirations.pop(index)
                if target_tracker.total_durations:
                    target_tracker.total_durations.pop(index)
                target_tracker.stack_ids.pop(index)
                target_tracker.healing_scores.pop(index)
        elif event.kind == "remove_all":
            target_tracker.expirations.clear()
            target_tracker.total_durations.clear()
            target_tracker.stack_ids.clear()
            target_tracker.healing_scores.clear()

        # --- Outgoing boon tracking (source-side) ---
        if event.kind == "apply" and event.source_agent_id != event.target_agent_id:
            self._outgoing[event.source_agent_id][buff_name].total_ms += (
                event.duration_ms * event.stacks
            )

    def _process_buff_apply(self, event: BuffApplyEvent) -> None:  # noqa: PLR0915
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
        # QueueLogic buffs (single-stack duration boons with queue behavior)
        if buff_name in _QUEUE_LOGIC_BUFFS:
            # QueueLogic: add initial stacks as queue
            duration = event.duration_ms if event.duration_ms > 0 else None
            target_tracker.expirations.extend([duration] * event.stacks)
            target_tracker.stack_ids.extend([event.stack_id] * event.stacks)
            target_tracker.healing_scores.extend([0] * event.stacks)
            # No total_durations for QueueLogic buffs
            # Keep only up to capacity (drop oldest if over capacity)
            if len(target_tracker.expirations) > _capacity_for(buff_name):
                excess = len(target_tracker.expirations) - _capacity_for(buff_name)
                target_tracker.expirations = target_tracker.expirations[excess:]
                target_tracker.stack_ids = target_tracker.stack_ids[excess:]
                target_tracker.healing_scores = target_tracker.healing_scores[excess:]

        # Intensity buffs with max_stacks > 1 (might, stability)
        elif _max_stacks_for(buff_name) > 1:
            if buff_name in _OVERRIDE_LOGIC_BUFFS:
                # OverrideLogic: track TotalDuration for each stack
                total_dur = event.duration_ms
                target_tracker.expirations.extend([expiry] * event.stacks)
                target_tracker.total_durations.extend([total_dur] * event.stacks)
                target_tracker.stack_ids.extend([event.stack_id] * event.stacks)
                target_tracker.healing_scores.extend([0] * event.stacks)
                # Sort by TotalDuration (shortest first) for OverrideLogic
                pairs = sorted(
                    zip(
                        target_tracker.expirations,
                        target_tracker.total_durations,
                        target_tracker.stack_ids,
                        target_tracker.healing_scores,
                        strict=True,
                    ),
                    key=lambda pair: pair[1],
                )
                pairs = pairs[-_capacity_for(buff_name) :]
                target_tracker.expirations = [e for e, _, _, _ in pairs]
                target_tracker.total_durations = [td for _, td, _, _ in pairs]
                target_tracker.stack_ids = [sid for _, _, sid, _ in pairs]
                target_tracker.healing_scores = [h for _, _, _, h in pairs]
            else:
                # Other intensity buffs (stability): sort by expiration
                target_tracker.expirations.extend([expiry] * event.stacks)
                target_tracker.stack_ids.extend([event.stack_id] * event.stacks)
                target_tracker.healing_scores.extend(
                    [self._healing_by_agent.get(event.source_agent_id, 0)] * event.stacks
                )
                stability_pairs = sorted(
                    zip(
                        target_tracker.expirations,
                        target_tracker.stack_ids,
                        target_tracker.healing_scores,
                        strict=True,
                    )
                )
                stability_pairs = stability_pairs[-_capacity_for(buff_name) :]
                target_tracker.expirations = [expiry for expiry, _, _ in stability_pairs]
                target_tracker.stack_ids = [stack_id for _, stack_id, _ in stability_pairs]
                target_tracker.healing_scores = [healing for _, _, healing in stability_pairs]

        # Single-stack duration boons (fury, quickness, etc.) - original behavior
        else:
            target_tracker.expirations.append(event.duration_ms or None)
            target_tracker.stack_ids.append(event.stack_id)
            target_tracker.healing_scores.append(0)
            del target_tracker.expirations[_capacity_for(buff_name) :]
            del target_tracker.stack_ids[_capacity_for(buff_name) :]
            del target_tracker.healing_scores[_capacity_for(buff_name) :]
            if event.added_active and event.stack_id in target_tracker.stack_ids:
                index = target_tracker.stack_ids.index(event.stack_id)
                target_tracker.expirations.insert(0, target_tracker.expirations.pop(index))
                target_tracker.stack_ids.insert(0, target_tracker.stack_ids.pop(index))
                target_tracker.healing_scores.insert(0, target_tracker.healing_scores.pop(index))

    def _process_buff_extension(self, event: BuffExtensionEvent) -> None:
        buff_name = _get_buff_name(event.skill_id)
        if buff_name is None or event.extended_duration_ms < 1:
            return

        target_tracker = self._get_stack(event.target_agent_id, buff_name)
        time_ms = self._relative_time(event.time_ms)
        self._advance(target_tracker, time_ms)
        old_duration = event.new_duration_ms - event.extended_duration_ms
        if buff_name in _OVERRIDE_LOGIC_BUFFS and target_tracker.total_durations:
            # OverrideLogic: graft extension onto stack with TotalDuration closest to old_duration
            index = min(
                range(len(target_tracker.total_durations)),
                key=lambda i: abs(target_tracker.total_durations[i] - old_duration),
            )
            target_tracker.total_durations[index] += event.extended_duration_ms
            target_tracker.expirations[index] = (
                target_tracker.expirations[index] or 0
            ) + event.extended_duration_ms
            return
        if buff_name in _QUEUE_LOGIC_BUFFS and target_tracker.expirations:
            # QueueLogic: graft extension onto stack with duration closest to old_duration
            candidates = [(i, e) for i, e in enumerate(target_tracker.expirations) if e is not None]
            if candidates:
                index, remaining = min(candidates, key=lambda pair: abs(pair[1] - old_duration))
                target_tracker.expirations[index] = remaining + event.extended_duration_ms
            return
        if target_tracker.expirations and (
            old_duration > 0 or len(target_tracker.expirations) >= _capacity_for(buff_name)
        ):
            # EI BuffSimulatorIntensity.Extend grafts the extension onto the
            # stack whose remaining duration is closest to oldValue, not the
            # shortest one.
            candidates = [(i, e) for i, e in enumerate(target_tracker.expirations) if e is not None]
            if candidates:
                index, remaining = min(candidates, key=lambda pair: abs(pair[1] - old_duration))
                target_tracker.expirations[index] = remaining + event.extended_duration_ms
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

    def compute_merged_uptimes(
        self,
        agent_ids: list[int],
        duration_ms: int,
        slice_lo_ms: int = 0,
        slice_hi_ms: int | None = None,
        awareness_spans: dict[int, tuple[int, int]] | None = None,
    ) -> dict[str, float]:
        """Compute merged boon uptime for a group of agents as one entity.

        Used for instance-recycled minions (same instance_id, no master, no account)
        where EI reports a single uptime across all recycled agents over the
        full slice duration.

        For each agent, uptime is computed over its awareness span intersected
        with the slice window [slice_lo_ms, slice_hi_ms). The merged uptime is
        the sum of cumulative_stack_ms across all agents, divided by duration_ms.
        """
        if duration_ms <= 0:
            return {}

        if slice_hi_ms is None:
            slice_hi_ms = slice_lo_ms + duration_ms

        result: dict[str, float] = {}
        for name in TRACKED_BUFFS:
            total_cumulative_stack_ms = 0

            for aid in agent_ids:
                agent = self._agent_buffs.get(aid, {})
                stack = agent.get(name)
                if stack is None:
                    continue

                # Determine the time window for this agent within the slice
                agent_start = 0
                agent_end = duration_ms
                if awareness_spans and aid in awareness_spans:
                    span = awareness_spans[aid]
                    # Awareness spans are fight-relative; convert to slice-relative
                    abs_start = max(span[0], slice_lo_ms)
                    abs_end = min(span[1], slice_hi_ms) if slice_hi_ms is not None else span[1]
                    agent_start = max(0, abs_start - slice_lo_ms)
                    agent_end = min(duration_ms, abs_end - slice_lo_ms)
                    if agent_end <= agent_start:
                        continue

                # Compute uptime for this agent bounded by its effective window
                snapshot = _BuffStack(name)
                snapshot.expirations = stack.expirations.copy()
                snapshot.stack_ids = stack.stack_ids.copy()
                snapshot.healing_scores = stack.healing_scores.copy()
                snapshot.last_time_ms = stack.last_time_ms
                snapshot.cumulative_stack_ms = stack.cumulative_stack_ms
                self._advance(snapshot, agent_end)
                # Subtract uptime before agent_start
                if agent_start > 0:
                    snapshot_start = _BuffStack(name)
                    snapshot_start.expirations = stack.expirations.copy()
                    snapshot_start.stack_ids = stack.stack_ids.copy()
                    snapshot_start.healing_scores = stack.healing_scores.copy()
                    snapshot_start.last_time_ms = stack.last_time_ms
                    snapshot_start.cumulative_stack_ms = stack.cumulative_stack_ms
                    self._advance(snapshot_start, agent_start)
                    total_cumulative_stack_ms += (
                        snapshot.cumulative_stack_ms - snapshot_start.cumulative_stack_ms
                    )
                else:
                    total_cumulative_stack_ms += snapshot.cumulative_stack_ms

            if total_cumulative_stack_ms == 0:
                result[name] = 0.0
                continue

            if _max_stacks_for(name) > 1:
                result[name] = total_cumulative_stack_ms / duration_ms
            else:
                result[name] = min(
                    100.0,
                    (total_cumulative_stack_ms / duration_ms) * 100.0,
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
