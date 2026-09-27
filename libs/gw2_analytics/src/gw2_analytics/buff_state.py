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

from gw2_core import (
    BoonApplyEvent,
    BuffApplyEvent,
    BuffExtensionEvent,
    BuffInfoEvent,
    BuffStackActiveEvent,
    BuffStackDeactiveEvent,
)

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
#: graft extensions by closest duration).
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
    "stealth": 5,
    "fury": 9,
    "quickness": 5,
    "alacrity": 9,
    "protection": 5,
    "vigor": 5,
    "aegis": 9,
    "swiftness": 9,
    "resistance": 5,
    "resolution": 5,
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
        self.regen_extensions: list[list[int]] = []
        self.queue_extensions: list[list[int]] = []
        # EI uses the last expired regeneration stack's seed source when an
        # extension creates a new stack without an active stack to extend.
        self.regen_last_removed_healing: int | None = None
        self.stack_ids: list[int] = []
        self.healing_scores: list[int] = []
        self.last_time_ms: int = 0
        self.cumulative_stack_ms: int = 0
        self.uptime_segments: list[tuple[int, int, int]] = []
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
        stability_duration_correction: bool = False,
        might_duration_correction: bool = False,
    ) -> None:
        # Per-agent per-buff stack state.
        # {agent_id: {buff_name: _BuffStack}}
        self._agent_buffs: dict[int, dict[str, _BuffStack]] = defaultdict(dict)
        # Outgoing: {source_agent_id: {buff_name: _OutgoingAccumulator}}
        self._outgoing: dict[int, dict[str, _OutgoingAccumulator]] = defaultdict(
            lambda: defaultdict(_OutgoingAccumulator),
        )
        self._start_time_ms = start_time_ms
        self._capacities: dict[str, int] = {}
        self._healing_by_agent = healing_by_agent or {}
        self._stability_duration_correction = stability_duration_correction
        self._might_duration_correction = might_duration_correction
        self._might_applies: dict[
            tuple[int, int | None], list[tuple[int, int, int]]
        ] = defaultdict(list)
        self._might_extensions: dict[
            tuple[int, int | None], list[tuple[int, int]]
        ] = defaultdict(list)
        self._stability_applies: dict[
            tuple[int, int | None], list[tuple[int, int, int]]
        ] = defaultdict(list)
        self._stability_extensions: dict[
            tuple[int, int | None], list[tuple[int, int]]
        ] = defaultdict(list)
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

    def _capacity_for(self, name: str) -> int:
        """Return EI's capacity override, or the existing fallback."""
        return self._capacities.get(name, _capacity_for(name))

    def _get_stack(self, agent_id: int, buff_name: str) -> _BuffStack:
        """Get or create the stack tracker for (agent, buff)."""
        agent = self._agent_buffs[agent_id]
        if buff_name not in agent:
            agent[buff_name] = _BuffStack(buff_name)
        return agent[buff_name]

    @staticmethod
    def _queue_total_duration(stack: _BuffStack, index: int) -> float:
        duration = stack.expirations[index]
        if duration is None:
            return float("inf")
        extensions = (
            stack.queue_extensions[index]
            if index < len(stack.queue_extensions)
            else []
        )
        return duration + sum(extensions)

    @staticmethod
    def _override_insert_index(durations: list[int], duration: int) -> int:
        """Mirror EI OverrideLogic's binary search, including equal-value ties."""
        low, high = 0, len(durations) - 1
        while low <= high:
            if durations[low] > duration:
                return low
            if durations[high] < duration:
                return high + 1
            middle = (low + high) // 2
            if durations[middle] == duration:
                return middle + 1
            if duration < durations[middle]:
                high = middle - 1
            else:
                low = middle + 1
        return low

    @staticmethod
    def _pending_extensions(stack: _BuffStack) -> list[list[int]] | None:
        if stack.name == "regeneration":
            return stack.regen_extensions
        if stack.name in _QUEUE_LOGIC_BUFFS:
            return stack.queue_extensions
        return None

    @staticmethod
    def _activate_regeneration_stack(stack: _BuffStack, index: int) -> None:
        """Activate one queued stack, replacing a front below 50ms TotalDuration."""
        expiry = stack.expirations.pop(index)
        stack_id = stack.stack_ids.pop(index)
        healing = stack.healing_scores.pop(index)
        total_duration = stack.total_durations.pop(index)
        extensions = (
            stack.regen_extensions.pop(index)
            if index < len(stack.regen_extensions)
            else []
        )
        if stack.expirations and stack.total_durations and stack.total_durations[0] < 50:
            stack.expirations[0] = expiry
            stack.stack_ids[0] = stack_id
            stack.healing_scores[0] = healing
            stack.total_durations[0] = total_duration
            stack.regen_extensions[0] = extensions
        else:
            stack.expirations.insert(0, expiry)
            stack.stack_ids.insert(0, stack_id)
            stack.healing_scores.insert(0, healing)
            stack.total_durations.insert(0, total_duration)
            stack.regen_extensions.insert(0, extensions)

    @staticmethod
    def _advance_single(stack: _BuffStack, new_time_ms: int) -> None:
        """Accumulate stack-time for single-stack (max_stacks=1) through expirations."""
        elapsed = new_time_ms - stack.last_time_ms
        interval_start = stack.last_time_ms
        if elapsed > 0 and stack.name == "regeneration" and stack.expirations:
            stack.regen_last_removed_healing = None
        while elapsed > 0 and stack.expirations:
            remaining = stack.expirations[0]
            if remaining is None:
                stack.uptime_segments.append((interval_start, new_time_ms, 1))
                stack.cumulative_stack_ms += elapsed
                break
            active = min(elapsed, remaining)
            active_end = interval_start + active
            if active:
                stack.uptime_segments.append((interval_start, active_end, 1))
            stack.cumulative_stack_ms += active
            if stack.name == "regeneration" and stack.total_durations:
                stack.total_durations[0] = max(0, stack.total_durations[0] - active)
            elapsed -= active
            remaining -= active
            interval_start = active_end
            if remaining == 0:
                stack.expirations.pop(0)
                pending_extensions = BuffStateTracker._pending_extensions(stack)
                if pending_extensions and pending_extensions[0]:
                    extension = pending_extensions[0].pop(0)
                    stack.expirations.insert(0, extension)
                    continue
                if pending_extensions:
                    pending_extensions.pop(0)
                if stack.name == "regeneration":
                    stack.regen_last_removed_healing = stack.healing_scores[0]
                if stack.total_durations:
                    stack.total_durations.pop(0)
                stack.stack_ids.pop(0)
                stack.healing_scores.pop(0)
                if elapsed > 0 and stack.expirations:
                    # EI's recursive Update(leftOver) clears _lastSrcRemove
                    # before advancing the next queued stack.
                    stack.regen_last_removed_healing = None
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
            if next_expiry is None or next_expiry > new_time_ms:
                break
            elapsed = next_expiry - stack.last_time_ms
            if elapsed:
                stack.uptime_segments.append(
                    (stack.last_time_ms, next_expiry, len(stack.expirations))
                )
            stack.cumulative_stack_ms += len(stack.expirations) * elapsed
            if stack.total_durations:
                stack.total_durations = [td - elapsed for td in stack.total_durations]
            stack.last_time_ms = next_expiry
            index = stack.expirations.index(next_expiry)
            stack.expirations.pop(index)
            if stack.total_durations:
                stack.total_durations.pop(index)
            stack.stack_ids.pop(index)
            stack.healing_scores.pop(index)
        elapsed = new_time_ms - stack.last_time_ms
        if elapsed > 0:
            stack.uptime_segments.append((stack.last_time_ms, new_time_ms, len(stack.expirations)))
            stack.cumulative_stack_ms += len(stack.expirations) * elapsed
            if stack.total_durations:
                stack.total_durations = [td - elapsed for td in stack.total_durations]
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
        hint: tuple[int, int, int] | None = None
        while index < len(hints) and hints[index][0] <= time_ms:
            hint = hints[index]
            index += 1
        self._regen_hint_cursor[agent_id] = index
        # Consume each displaced-stack record once; EI pairs a removal with
        # the application that follows it inside one server delay.
        if hint is None or time_ms - hint[0] >= 10:
            return None
        _, removed_duration, buff_instance = hint
        return removed_duration, buff_instance

    def _regen_eviction_index(
        self, stack: _BuffStack, event: BoonApplyEvent | BuffApplyEvent
    ) -> int:
        """Which queued regeneration stack this application displaces.

        Elite Insights' ``HealingLogic.FindLowestValue``: the stack whose
        buff instance arcdps named, else the one whose TotalDuration is closest
        to the removed one, else -- with nothing to go on -- the last (lowest healing).
        """
        hint = self._regen_overstack_hint(event.target_agent_id, event.time_ms)
        if hint is not None:
            removed_duration, buff_instance = hint
            if buff_instance and buff_instance in stack.stack_ids:
                return stack.stack_ids.index(buff_instance)
            if removed_duration > 0 and stack.total_durations:
                # EI compares TotalDuration (base + extensions), not remaining duration
                return min(
                    range(len(stack.total_durations)),
                    key=lambda i: abs(stack.total_durations[i] - removed_duration),
                )
        return len(stack.expirations) - 1

    def _relative_time(self, time_ms: int) -> int:
        return max(0, time_ms - self._start_time_ms)

    def end_agent(self, agent_id: int, time_ms: int) -> None:
        """Advance and clear every tracked buff when an agent despawns."""
        for stack in self._agent_buffs.get(agent_id, {}).values():
            self._advance(stack, self._relative_time(time_ms))
            stack.expirations.clear()
            stack.regen_extensions.clear()
            stack.queue_extensions.clear()
            stack.total_durations.clear()
            stack.stack_ids.clear()
            stack.healing_scores.clear()

    def process(  # noqa: PLR0911, PLR0912, PLR0915
        self,
        event: (
            BoonApplyEvent
            | BuffApplyEvent
            | BuffExtensionEvent
            | BuffInfoEvent
            | BuffStackActiveEvent
            | BuffStackDeactiveEvent
        ),
    ) -> None:
        """Process one ``BoonApplyEvent`` or ``BuffApplyEvent`` and update state.

        Events MUST be in chronological order (ascending ``time_ms``).
        Untracked buff IDs (not in ``TRACKED_BUFFS``) are silently ignored.

        Raises:
            TypeError: if ``event`` is not a supported buff event.
        """
        if isinstance(event, BuffInfoEvent):
            buff_name = _get_buff_name(event.skill_id)
            if buff_name is not None and event.max_stacks > 0:
                self._capacities[buff_name] = event.max_stacks
            return
        if isinstance(event, BuffStackDeactiveEvent):
            # Accepted for EI HasStackIDs detection; it does not affect uptime state.
            return
        if isinstance(event, BuffStackActiveEvent):
            buff_name = _get_buff_name(event.skill_id)
            if buff_name != "regeneration":
                return
            stack = self._get_stack(event.target_agent_id, buff_name)
            self._advance(stack, self._relative_time(event.time_ms))
            if event.stack_id in stack.stack_ids:
                self._activate_regeneration_stack(
                    stack, stack.stack_ids.index(event.stack_id)
                )
                self._healing_no_sort = True
            return
        if isinstance(event, BuffApplyEvent):
            if event.skill_id in (TRACKED_BUFFS["stability"], TRACKED_BUFFS["might"]):
                original_duration = (
                    event.original_duration_ms if event.initial else event.duration_ms
                )
                apply_history = (
                    self._stability_applies
                    if event.skill_id == TRACKED_BUFFS["stability"]
                    else self._might_applies
                )
                apply_history[(event.target_agent_id, event.stack_id)].append(
                    (event.time_ms, original_duration, event.duration_ms)
                )
            self._process_buff_apply(event)
            return
        if isinstance(event, BuffExtensionEvent):
            if event.skill_id in (TRACKED_BUFFS["stability"], TRACKED_BUFFS["might"]):
                extension_history = (
                    self._stability_extensions
                    if event.skill_id == TRACKED_BUFFS["stability"]
                    else self._might_extensions
                )
                extension_history[(event.target_agent_id, event.stack_id)].append(
                    (event.time_ms, event.extended_duration_ms)
                )
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
            if buff_name in ("stability", "might"):
                history = (
                    self._stability_applies
                    if buff_name == "stability"
                    else self._might_applies
                )
                for _ in range(event.stacks):
                    history[(event.target_agent_id, event.stack_id)].append(
                        (event.time_ms, event.duration_ms, event.duration_ms)
                    )
            # QueueLogic buffs (single-stack duration boons with queue behavior)
            # are handled separately even though they have max_stacks=1.
            if buff_name in _QUEUE_LOGIC_BUFFS:
                # QueueLogic (EI): capacity 9, only front stack counts.
                # Add new stack; on overflow EI FindLowestValue replaces the
                # shortest non-front stack IN PLACE (stacks[IndexOf(toRemove)]
                # = toAdd), preserving queue order -- not pop+append, which
                # would rotate the queue and change which stack fronts next.
                duration = event.duration_ms
                while len(target_tracker.queue_extensions) < len(target_tracker.expirations):
                    target_tracker.queue_extensions.append([])
                if len(target_tracker.expirations) >= self._capacity_for(buff_name):
                    if len(target_tracker.expirations) > 1:
                        # Find shortest by TotalDuration among non-front stacks.
                        min_idx = 1
                        min_dur = self._queue_total_duration(target_tracker, 1)
                        for i in range(2, len(target_tracker.expirations)):
                            duration_total = self._queue_total_duration(target_tracker, i)
                            if duration_total < min_dur:
                                min_dur = duration_total
                                min_idx = i
                        target_tracker.expirations[min_idx] = duration
                        target_tracker.stack_ids[min_idx] = event.stack_id
                        target_tracker.healing_scores[min_idx] = self._healing_by_agent.get(
                            event.source_agent_id, 0
                        )
                        target_tracker.queue_extensions[min_idx] = []
                    else:
                        # Only one stack (the front), replace it
                        target_tracker.expirations[0] = duration
                        target_tracker.stack_ids[0] = event.stack_id
                        target_tracker.healing_scores[0] = self._healing_by_agent.get(
                            event.source_agent_id, 0
                        )
                        target_tracker.queue_extensions[0] = []
                else:
                    target_tracker.expirations.append(duration)
                    target_tracker.stack_ids.append(event.stack_id)
                    target_tracker.healing_scores.append(
                        self._healing_by_agent.get(event.source_agent_id, 0)
                    )
                    target_tracker.queue_extensions.append([])
            elif _max_stacks_for(buff_name) > 1:
                if buff_name in _OVERRIDE_LOGIC_BUFFS:
                    # OverrideLogic (EI): sort by TotalDuration (shortest first),
                    # remove index 0 when at capacity.
                    # TotalDuration = base duration + extensions (initially just base).
                    for _ in range(event.stacks):
                        total_dur = event.duration_ms
                        if len(target_tracker.total_durations) >= self._capacity_for(buff_name):
                            # EI removes the shortest stack, then inserts into
                            # the remaining sorted list using its binary search.
                            target_tracker.expirations.pop(0)
                            target_tracker.total_durations.pop(0)
                            target_tracker.stack_ids.pop(0)
                            target_tracker.healing_scores.pop(0)
                        insert_idx = self._override_insert_index(
                            target_tracker.total_durations, total_dur
                        )
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
                    pairs = pairs[-self._capacity_for(buff_name) :]
                    target_tracker.expirations = [expiry for expiry, _, _ in pairs]
                    target_tracker.stack_ids = [stack_id for _, stack_id, _ in pairs]
                    target_tracker.healing_scores = [healing for _, _, healing in pairs]
            elif buff_name == "regeneration":
                # EI BuffSimulatorDuration + HealingLogic: capacity-5
                # queue, replace the lowest-heal stack on overflow
                # (wasting its remaining duration), re-sort by healing
                # until the first added_active apply pins no_sort, then
                # activate: move the new stack to the front (or replace
                # the active stack outright when it has <50 ms TotalDuration).
                new_duration = event.duration_ms
                new_healing = self._healing_by_agent.get(event.source_agent_id, 0)
                new_total_dur = event.duration_ms
                if len(target_tracker.expirations) >= self._capacity_for(buff_name):
                    victim = self._regen_eviction_index(target_tracker, event)
                    target_tracker.expirations[victim] = new_duration
                    if len(target_tracker.regen_extensions) < len(target_tracker.expirations):
                        missing = len(target_tracker.expirations) - len(
                            target_tracker.regen_extensions
                        )
                        target_tracker.regen_extensions.extend([[] for _ in range(missing)])
                    target_tracker.stack_ids[victim] = event.stack_id
                    target_tracker.healing_scores[victim] = new_healing
                    if target_tracker.total_durations:
                        target_tracker.total_durations[victim] = new_total_dur
                    target_tracker.regen_extensions[victim] = []
                else:
                    target_tracker.expirations.append(new_duration)
                    target_tracker.stack_ids.append(event.stack_id)
                    target_tracker.healing_scores.append(new_healing)
                    target_tracker.total_durations.append(new_total_dur)
                    target_tracker.regen_extensions.append([])
                if not self._healing_no_sort:
                    regeneration_pairs = sorted(
                        zip(
                            target_tracker.expirations,
                            target_tracker.stack_ids,
                            target_tracker.healing_scores,
                            target_tracker.total_durations,
                            target_tracker.regen_extensions,
                            strict=True,
                        ),
                        key=lambda pair: pair[2],
                        reverse=True,
                    )
                    target_tracker.expirations = [
                        expiry for expiry, _, _, _, _ in regeneration_pairs
                    ]
                    target_tracker.stack_ids = [
                        stack_id for _, stack_id, _, _, _ in regeneration_pairs
                    ]
                    target_tracker.healing_scores = [
                        healing for _, _, healing, _, _ in regeneration_pairs
                    ]
                    target_tracker.total_durations = [td for _, _, _, td, _ in regeneration_pairs]
                    target_tracker.regen_extensions = [ex for _, _, _, _, ex in regeneration_pairs]
            else:
                target_tracker.expirations.append(
                    event.duration_ms if event.duration_ms > 0 else None
                )
                target_tracker.stack_ids.append(event.stack_id)
                target_tracker.healing_scores.append(
                    self._healing_by_agent.get(event.source_agent_id, 0)
                )
                del target_tracker.expirations[self._capacity_for(buff_name) :]
                del target_tracker.stack_ids[self._capacity_for(buff_name) :]
                del target_tracker.healing_scores[self._capacity_for(buff_name) :]
        elif event.kind == "remove_single":
            if buff_name in _QUEUE_LOGIC_BUFFS and target_tracker.expirations:
                # EI's no-ID simulator matches Single removals by TotalDuration,
                # not the arcdps stack ID.
                stack_index = next(
                    (
                        i
                        for i in range(len(target_tracker.expirations))
                        if abs(
                            self._queue_total_duration(target_tracker, i)
                            - event.duration_ms
                        ) < 15
                    ),
                    None,
                )
                if stack_index is not None:
                    target_tracker.expirations.pop(stack_index)
                    target_tracker.stack_ids.pop(stack_index)
                    target_tracker.healing_scores.pop(stack_index)
                    target_tracker.queue_extensions.pop(stack_index)
            elif buff_name == "regeneration" and target_tracker.expirations:
                stack_index = next(
                    (
                        i
                        for i, total_duration in enumerate(target_tracker.total_durations)
                        if abs(total_duration - event.duration_ms) < 15
                    ),
                    None,
                )
                if stack_index is not None:
                    target_tracker.expirations.pop(stack_index)
                    target_tracker.total_durations.pop(stack_index)
                    target_tracker.stack_ids.pop(stack_index)
                    target_tracker.healing_scores.pop(stack_index)
                    target_tracker.regen_extensions.pop(stack_index)
            elif _max_stacks_for(buff_name) == 1 and target_tracker.expirations:
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
            elif buff_name in _OVERRIDE_LOGIC_BUFFS and target_tracker.total_durations:
                removed_duration = event.duration_ms
                correction_enabled = (
                    self._stability_duration_correction and buff_name == "stability"
                ) or (self._might_duration_correction and buff_name == "might")
                if correction_enabled and (
                    buff_name == "stability" or event.duration_ms == 2**31 - 1
                ):
                    key = (event.target_agent_id, event.stack_id)
                    applies_history = (
                        self._stability_applies if buff_name == "stability" else self._might_applies
                    )
                    extensions_history = (
                        self._stability_extensions
                        if buff_name == "stability"
                        else self._might_extensions
                    )
                    applies = [
                        row for row in applies_history[key] if row[0] <= event.time_ms
                    ]
                    if applies:
                        apply_time, original, applied = applies[-1]
                        extension_total = sum(
                            amount for ext_time, amount in extensions_history[key]
                            if apply_time <= ext_time <= event.time_ms
                        )
                        if original + extension_total == event.duration_ms:
                            elapsed = event.time_ms - apply_time
                            removed_duration = max(
                                event.duration_ms - (original - applied) - elapsed,
                                0,
                            )
                stack_index = next(
                    (
                        i
                        for i, total_dur in enumerate(target_tracker.total_durations)
                        if abs(total_dur - removed_duration) < 15
                    ),
                    None,
                )
                if stack_index is not None:
                    target_tracker.expirations.pop(stack_index)
                    target_tracker.total_durations.pop(stack_index)
                    target_tracker.stack_ids.pop(stack_index)
                    target_tracker.healing_scores.pop(stack_index)
            elif target_tracker.expirations:
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
        elif event.kind == "remove_all":
            target_tracker.expirations.clear()
            target_tracker.total_durations.clear()
            target_tracker.regen_extensions.clear()
            target_tracker.queue_extensions.clear()
            target_tracker.stack_ids.clear()
            target_tracker.healing_scores.clear()

        # --- Outgoing boon tracking (source-side) ---
        if event.kind == "apply" and event.source_agent_id != event.target_agent_id:
            self._outgoing[event.source_agent_id][buff_name].total_ms += (
                event.duration_ms * event.stacks
            )

    def _process_buff_apply(self, event: BuffApplyEvent) -> None:  # noqa: PLR0912, PLR0915
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
        expiry = time_ms + event.duration_ms
        if buff_name == "regeneration":
            # EI calls HealingLogic.Add for each initial stack, so overflow
            # selection and healing-priority sorting happen after every add.
            capacity = self._capacity_for(buff_name)
            for _ in range(event.stacks):
                if len(target_tracker.expirations) >= capacity:
                    victim = self._regen_eviction_index(target_tracker, event)
                    target_tracker.expirations[victim] = expiry
                    target_tracker.total_durations[victim] = event.duration_ms
                    target_tracker.regen_extensions[victim] = []
                    target_tracker.stack_ids[victim] = event.stack_id
                    target_tracker.healing_scores[victim] = self._healing_by_agent.get(
                        event.source_agent_id, 0
                    )
                else:
                    target_tracker.expirations.append(expiry)
                    target_tracker.total_durations.append(event.duration_ms)
                    target_tracker.regen_extensions.append([])
                    target_tracker.stack_ids.append(event.stack_id)
                    target_tracker.healing_scores.append(
                        self._healing_by_agent.get(event.source_agent_id, 0)
                    )
                if not self._healing_no_sort:
                    regen_pairs = sorted(
                        zip(
                            target_tracker.expirations,
                            target_tracker.total_durations,
                            target_tracker.regen_extensions,
                            target_tracker.stack_ids,
                            target_tracker.healing_scores,
                            strict=True,
                        ),
                        key=lambda pair: pair[4],
                        reverse=True,
                    )
                    target_tracker.expirations = [p[0] for p in regen_pairs]
                    target_tracker.total_durations = [p[1] for p in regen_pairs]
                    target_tracker.regen_extensions = [p[2] for p in regen_pairs]
                    target_tracker.stack_ids = [p[3] for p in regen_pairs]
                    target_tracker.healing_scores = [p[4] for p in regen_pairs]
            # added_active is an arcdps apply-record field, not present on
            # EI BoonApplyEvent snapshots; do not infer it from snapshots.

        # QueueLogic buffs (single-stack duration boons with queue behavior)
        elif buff_name in _QUEUE_LOGIC_BUFFS:
            # QueueLogic: add initial stacks one by one, using same overflow
            # logic as mid-combat applies (drop shortest non-front on overflow,
            # replacing it in place to preserve queue order).
            capacity = self._capacity_for(buff_name)
            while len(target_tracker.queue_extensions) < len(target_tracker.expirations):
                target_tracker.queue_extensions.append([])
            for _ in range(event.stacks):
                duration = event.duration_ms
                if len(target_tracker.expirations) >= capacity:
                    # Find shortest TotalDuration among non-front stacks.
                    if len(target_tracker.expirations) > 1:
                        min_idx = 1
                        min_dur = self._queue_total_duration(target_tracker, 1)
                        for i in range(2, len(target_tracker.expirations)):
                            duration_total = self._queue_total_duration(target_tracker, i)
                            if duration_total < min_dur:
                                min_dur = duration_total
                                min_idx = i
                        # Replace in place (EI behavior), not append
                        target_tracker.expirations[min_idx] = duration
                        target_tracker.stack_ids[min_idx] = event.stack_id
                        target_tracker.healing_scores[min_idx] = 0
                        target_tracker.queue_extensions[min_idx] = []
                    else:
                        # Only one stack (the front), replace it
                        target_tracker.expirations[0] = duration
                        target_tracker.stack_ids[0] = event.stack_id
                        target_tracker.healing_scores[0] = 0
                        target_tracker.queue_extensions[0] = []
                else:
                    target_tracker.expirations.append(duration)
                    target_tracker.stack_ids.append(event.stack_id)
                    target_tracker.healing_scores.append(0)
                    target_tracker.queue_extensions.append([])

        # Intensity buffs with max_stacks > 1 (might, stability)
        elif _max_stacks_for(buff_name) > 1:
            if buff_name in _OVERRIDE_LOGIC_BUFFS:
                # OverrideLogic: track TotalDuration for each stack
                total_dur = event.duration_ms
                # EI OverrideLogic.Add uses binary search and inserts immediately
                # after the midpoint when it encounters an equal duration.
                for _ in range(event.stacks):
                    low, high = 0, len(target_tracker.total_durations) - 1
                    insert_at = len(target_tracker.total_durations)
                    while low <= high:
                        if target_tracker.total_durations[low] > total_dur:
                            insert_at = low
                            break
                        if target_tracker.total_durations[high] < total_dur:
                            insert_at = high + 1
                            break
                        mid = (low + high) // 2
                        current = target_tracker.total_durations[mid]
                        if total_dur == current:
                            insert_at = mid + 1
                            break
                        if total_dur < current:
                            high = mid - 1
                        else:
                            low = mid + 1
                    target_tracker.expirations.insert(insert_at, expiry)
                    target_tracker.total_durations.insert(insert_at, total_dur)
                    target_tracker.stack_ids.insert(insert_at, event.stack_id)
                    target_tracker.healing_scores.insert(insert_at, 0)
                capacity = self._capacity_for(buff_name)
                del target_tracker.expirations[capacity:]
                del target_tracker.total_durations[capacity:]
                del target_tracker.stack_ids[capacity:]
                del target_tracker.healing_scores[capacity:]
            else:
                # Other intensity buffs (stability): sort by expiration
                target_tracker.expirations.extend([expiry] * event.stacks)
                target_tracker.stack_ids.extend([event.stack_id] * event.stacks)
                target_tracker.healing_scores.extend(
                    [self._healing_by_agent.get(event.source_agent_id, 0)] * event.stacks
                )
                other_intensity_pairs = sorted(
                    zip(
                        target_tracker.expirations,
                        target_tracker.stack_ids,
                        target_tracker.healing_scores,
                        strict=True,
                    )
                )
                other_intensity_pairs = other_intensity_pairs[-self._capacity_for(buff_name) :]
                target_tracker.expirations = [
                    expiry for expiry, _, _ in other_intensity_pairs
                ]
                target_tracker.stack_ids = [
                    stack_id for _, stack_id, _ in other_intensity_pairs
                ]
                target_tracker.healing_scores = [
                    healing for _, _, healing in other_intensity_pairs
                ]

        # Single-stack duration boons (fury, quickness, etc.) - original behavior
        else:
            target_tracker.expirations.append(event.duration_ms or None)
            target_tracker.stack_ids.append(event.stack_id)
            target_tracker.healing_scores.append(0)
            if buff_name == "regeneration":
                target_tracker.total_durations.append(event.duration_ms)
                target_tracker.regen_extensions.append([])
            del target_tracker.expirations[self._capacity_for(buff_name) :]
            del target_tracker.stack_ids[self._capacity_for(buff_name) :]
            del target_tracker.healing_scores[self._capacity_for(buff_name) :]
            if buff_name == "regeneration":
                del target_tracker.total_durations[self._capacity_for(buff_name) :]
            # Snapshots have no added_active flag; preserve EI stack order.

    def _extend_regeneration_front(
        self, stack: _BuffStack, event: BuffExtensionEvent, old_duration: int
    ) -> None:
        if stack.expirations and (
            old_duration > 0 or len(stack.expirations) >= self._capacity_for("regeneration")
        ):
            while len(stack.regen_extensions) < len(stack.expirations):
                stack.regen_extensions.append([])
            index = min(
                range(len(stack.total_durations)),
                key=lambda i: abs(stack.total_durations[i] - old_duration),
            )
            stack.total_durations[index] += event.extended_duration_ms
            stack.expirations[index] = (stack.expirations[index] or 0) + event.extended_duration_ms
            return

        seeded_from_removal = stack.regen_last_removed_healing is not None
        stack.expirations.append(event.new_duration_ms)
        stack.total_durations.append(event.new_duration_ms)
        stack.regen_extensions.append([])
        stack.stack_ids.append(event.stack_id)
        stack.healing_scores.append(stack.regen_last_removed_healing or 0)
        if not self._healing_no_sort:
            regen_pairs = sorted(
                zip(
                    stack.expirations,
                    stack.total_durations,
                    stack.regen_extensions,
                    stack.stack_ids,
                    stack.healing_scores,
                    strict=True,
                ),
                key=lambda pair: pair[4],
                reverse=True,
            )
            stack.expirations = [pair[0] for pair in regen_pairs]
            stack.total_durations = [pair[1] for pair in regen_pairs]
            stack.regen_extensions = [pair[2] for pair in regen_pairs]
            stack.stack_ids = [pair[3] for pair in regen_pairs]
            stack.healing_scores = [pair[4] for pair in regen_pairs]
        capacity = self._capacity_for("regeneration")
        for values in (
            stack.expirations,
            stack.total_durations,
            stack.regen_extensions,
            stack.stack_ids,
            stack.healing_scores,
        ):
            del values[capacity:]
        if event.stack_id in stack.stack_ids and not seeded_from_removal:
            self._activate_regeneration_stack(stack, stack.stack_ids.index(event.stack_id))
            self._healing_no_sort = True

    def _extend_override_stack(
        self, stack: _BuffStack, event: BuffExtensionEvent, time_ms: int, old_duration: int
    ) -> None:
        if stack.total_durations:
            index = min(
                range(len(stack.total_durations)),
                key=lambda i: abs(stack.total_durations[i] - old_duration),
            )
            stack.total_durations[index] += event.extended_duration_ms
            stack.expirations[index] = (stack.expirations[index] or 0) + event.extended_duration_ms
        else:
            duration = event.new_duration_ms
            stack.expirations.append(time_ms + duration)
            stack.total_durations.append(duration)
            stack.stack_ids.append(event.stack_id)
            stack.healing_scores.append(self._healing_by_agent.get(event.source_agent_id, 0))

    def _process_buff_extension(self, event: BuffExtensionEvent) -> None:
        buff_name = _get_buff_name(event.skill_id)
        if buff_name is None or event.extended_duration_ms < 1:
            return

        target_tracker = self._get_stack(event.target_agent_id, buff_name)
        time_ms = self._relative_time(event.time_ms)
        self._advance(target_tracker, time_ms)
        old_duration = event.new_duration_ms - event.extended_duration_ms
        if buff_name == "regeneration":
            self._extend_regeneration_front(target_tracker, event, old_duration)
            return
        if buff_name in _OVERRIDE_LOGIC_BUFFS:
            # EI creates oldValue + extension as a new stack if none is live.
            self._extend_override_stack(target_tracker, event, time_ms, old_duration)
            return
        if buff_name in _QUEUE_LOGIC_BUFFS:
            while len(target_tracker.queue_extensions) < len(target_tracker.expirations):
                target_tracker.queue_extensions.append([])
            if target_tracker.expirations and (
                old_duration > 0
                or len(target_tracker.expirations) >= self._capacity_for(buff_name)
            ):
                # EI BuffSimulatorDuration extends the active queue front;
                # the extension runs only after its current Duration expires.
                target_tracker.queue_extensions[0].append(event.extended_duration_ms)
                return

            # With no live front and room in the queue, EI adds oldValue +
            # extension as a new active stack.
            index = len(target_tracker.expirations)
            target_tracker.expirations.append(event.new_duration_ms)
            target_tracker.stack_ids.append(event.stack_id)
            target_tracker.healing_scores.append(
                self._healing_by_agent.get(event.source_agent_id, 0)
            )
            target_tracker.queue_extensions.append([])
            target_tracker.expirations.insert(0, target_tracker.expirations.pop(index))
            target_tracker.stack_ids.insert(0, target_tracker.stack_ids.pop(index))
            target_tracker.healing_scores.insert(0, target_tracker.healing_scores.pop(index))
            target_tracker.queue_extensions.insert(
                0, target_tracker.queue_extensions.pop(index)
            )
            return
        if target_tracker.expirations and (
            old_duration > 0 or len(target_tracker.expirations) >= self._capacity_for(buff_name)
        ):
            # EI BuffSimulatorIntensity.Extend grafts the extension onto the
            # stack whose remaining duration is closest to oldValue, not the
            # shortest one.
            candidates = [(i, e) for i, e in enumerate(target_tracker.expirations) if e is not None]
            if candidates:
                index, remaining = min(candidates, key=lambda pair: abs(pair[1] - old_duration))
                target_tracker.expirations[index] = remaining + event.extended_duration_ms
                if buff_name == "regeneration" and target_tracker.total_durations:
                    target_tracker.total_durations[index] += event.extended_duration_ms
            return
        target_tracker.expirations.append(event.new_duration_ms)
        target_tracker.stack_ids.append(event.stack_id)
        target_tracker.healing_scores.append(self._healing_by_agent.get(event.source_agent_id, 0))
        if buff_name == "regeneration":
            target_tracker.total_durations.append(event.new_duration_ms)
        del target_tracker.expirations[self._capacity_for(buff_name) :]
        del target_tracker.stack_ids[self._capacity_for(buff_name) :]
        del target_tracker.healing_scores[self._capacity_for(buff_name) :]
        if buff_name == "regeneration":
            del target_tracker.total_durations[self._capacity_for(buff_name) :]

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
            snapshot.total_durations = stack.total_durations.copy()
            snapshot.regen_extensions = [extensions.copy() for extensions in stack.regen_extensions]
            snapshot.queue_extensions = [extensions.copy() for extensions in stack.queue_extensions]
            snapshot.stack_ids = stack.stack_ids.copy()
            snapshot.healing_scores = stack.healing_scores.copy()
            snapshot.last_time_ms = stack.last_time_ms
            snapshot.cumulative_stack_ms = stack.cumulative_stack_ms
            end_time_ms = duration_ms if active_duration_ms is None else active_duration_ms
            self._advance(snapshot, min(duration_ms, end_time_ms))
            if _max_stacks_for(name) > 1:
                result[name] = snapshot.cumulative_stack_ms / duration_ms
            else:
                result[name] = min(
                    100.0,
                    (snapshot.cumulative_stack_ms / duration_ms) * 100.0,
                )
        return result

    def _merged_stack_uptime(self, stack: _BuffStack, start_ms: int, end_ms: int) -> int:
        """Return stack-time in a fight-relative interval without rewinding state."""
        total = sum(
            max(0, min(end_ms, segment_end) - max(start_ms, segment_start)) * stacks
            for segment_start, segment_end, stacks in stack.uptime_segments
        )
        if end_ms <= stack.last_time_ms:
            return total

        snapshot = _BuffStack(stack.name)
        snapshot.expirations = stack.expirations.copy()
        snapshot.total_durations = stack.total_durations.copy()
        snapshot.regen_extensions = [extensions.copy() for extensions in stack.regen_extensions]
        snapshot.queue_extensions = [extensions.copy() for extensions in stack.queue_extensions]
        snapshot.stack_ids = stack.stack_ids.copy()
        snapshot.healing_scores = stack.healing_scores.copy()
        snapshot.last_time_ms = stack.last_time_ms
        snapshot.cumulative_stack_ms = stack.cumulative_stack_ms
        self._advance(snapshot, max(start_ms, stack.last_time_ms))
        before_end = snapshot.cumulative_stack_ms
        self._advance(snapshot, end_ms)
        return total + snapshot.cumulative_stack_ms - before_end

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

        ``slice_lo_ms``, ``slice_hi_ms``, and awareness spans are fight-relative.
        For each agent, uptime is computed over its awareness span intersected
        with the slice window [slice_lo_ms, slice_hi_ms). The merged uptime is
        the sum of stack-time across all agents, divided by duration_ms.
        """
        if duration_ms <= 0:
            return {}

        if slice_hi_ms is None:
            slice_hi_ms = slice_lo_ms + duration_ms

        result: dict[str, float] = {}
        for name in TRACKED_BUFFS:
            total_stack_ms = 0

            for aid in agent_ids:
                stack = self._agent_buffs.get(aid, {}).get(name)
                if stack is None:
                    continue

                agent_start = max(0, slice_lo_ms)
                agent_end = min(duration_ms, slice_hi_ms)
                if awareness_spans and aid in awareness_spans:
                    span = awareness_spans[aid]
                    agent_start = max(agent_start, span[0])
                    agent_end = min(agent_end, span[1])
                if agent_end <= agent_start:
                    continue

                total_stack_ms += self._merged_stack_uptime(stack, agent_start, agent_end)

            if total_stack_ms == 0:
                result[name] = 0.0
                continue

            if _max_stacks_for(name) > 1:
                result[name] = total_stack_ms / duration_ms
            else:
                result[name] = min(
                    100.0,
                    (total_stack_ms / duration_ms) * 100.0,
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
