"""Buff uptime tracker (v0.10.5 plan 137; Phase 9 forward-extended).

Pydantic v2 re-implementation of the chronological buff-history
pattern. The :class:`BuffState` model stores an append-only list of
``(time_ms, stacks)`` tuples. Callers append events in monotonic
order; the pure functions below compute total uptime and interval
percentage from that history.

Why chronological history?
==========================

The history list is appended at event time in monotonic order. This
keeps the read-side arithmetic simple: a single linear scan with no
sorting or reversing. Total uptime is ``O(history)``.

Invariants
==========

- ``history`` is a list of ``(time_ms, stacks)`` tuples.
- ``time_ms`` is non-decreasing across the list.
- ``stacks`` is non-negative.
- The caller must enforce the monotonic-time invariant when
  appending. The helper :func:`append_stacks` is provided for
  convenience and raises :class:`ValueError` on a backward-time
  append.

Phase 9 extension: :func:`accumulate_buff_events` folds a stream of
``BoonApplyEvent`` records into per-skill-id :class:`BuffState`
instances. Single linear scan over the event stream -- no sort,
no reverse. The 3-way ``kind`` discriminator (``apply``,
``remove_single``, ``remove_all``) translates to stack deltas:

- ``apply``         -> ``stacks += event.stacks``
- ``remove_single`` -> ``stacks -= 1`` (clamped at 0)
- ``remove_all``    -> ``stacks = 0``

The resulting :class:`BuffState` carries no pre-seed entry: the
first event for a skill_id becomes the first history entry, and
read-side functions (:func:`total_uptime_ms`,
:func:`interval_uptime_pct`) treat the pre-first-event interval as
implicitly 0-stacks. This keeps the history minimal ("every entry
came from a real event") without affecting the uptime arithmetic.
"""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field, field_validator

from gw2_core import BoonApplyEvent


class NonMonotonicHistoryError(ValueError):
    """Raised when a history list violates the monotonic-time invariant."""


class NegativeStacksError(ValueError):
    """Raised when a history entry contains a negative stack count."""


class BuffState(BaseModel):
    """Per-buff uptime tracker. History is append-only and chronological.

    The ``history`` field stores ``(time_ms, stacks)`` tuples.
    ``time_ms`` must be non-decreasing; ``stacks`` must be
    non-negative. Pydantic validates the tuple shape at
    construction time.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    history: list[tuple[int, int]] = Field(default_factory=list)

    @field_validator("history")
    @classmethod
    def _validate_history(cls, history: list[tuple[int, int]]) -> list[tuple[int, int]]:
        """Validate the chronological-history invariant at construction time."""
        prev_time: int | None = None
        for time_ms, stacks in history:
            if prev_time is not None and time_ms < prev_time:
                raise NonMonotonicHistoryError(
                    f"time_ms must be non-decreasing: {time_ms} < {prev_time}"
                )
            if stacks < 0:
                raise NegativeStacksError(f"stacks must be non-negative: {stacks}")
            prev_time = time_ms
        return history

    def append_stacks(self, time_ms: int, stacks: int) -> BuffState:
        """Return a new :class:`BuffState` with the appended history entry.

        The field validator on :class:`BuffState` enforces the
        chronological and non-negative-stacks invariants, so this
        method simply constructs a new instance.

        Parameters
        ----------
        time_ms:
            Timestamp in milliseconds. Must be >= the last entry's
            time (if any).
        stacks:
            Number of stacks at ``time_ms``. Must be >= 0.

        Returns
        -------
        A new :class:`BuffState` with the appended entry.
        """
        return BuffState(history=[*self.history, (time_ms, stacks)])


def total_uptime_ms(state: BuffState, fight_end_ms: int) -> int:
    """Return the total number of millisecond-seconds the buff was active.

    The history is scanned once. For each consecutive pair
    ``(t_i, s_i)`` and ``(t_{i+1}, s_{i+1})``, the contribution
    is ``s_i * (t_{i+1} - t_i)``. The final entry contributes
    ``s_last * (fight_end_ms - t_last)``.

    Parameters
    ----------
    state:
        The :class:`BuffState` to evaluate.
    fight_end_ms:
        The fight end time in milliseconds. Must be >= the last
        history time (if any).

    Returns
    -------
    Total uptime in millisecond-seconds (i.e. the sum of
    ``stacks * duration_ms`` across all intervals).

    Complexity
    ----------
    ``O(len(state.history))``.
    """
    history = state.history
    if not history:
        return 0
    if fight_end_ms < history[-1][0]:
        raise ValueError(
            f"fight_end_ms ({fight_end_ms}) must be >= last history time ({history[-1][0]})"
        )

    total = 0
    for i in range(len(history) - 1):
        t_i, s_i = history[i]
        t_next = history[i + 1][0]
        total += s_i * (t_next - t_i)
    total += history[-1][1] * (fight_end_ms - history[-1][0])
    return total


def interval_uptime_pct(
    state: BuffState,
    fight_end_ms: int,
    fight_start_ms: int = 0,
) -> float:
    """Return the percentage of the fight interval the buff was active.

    Computes ``total_uptime_ms / (fight_end_ms - fight_start_ms) * 100``.
    The result is clamped to ``[0.0, 100.0]``.

    Parameters
    ----------
    state:
        The :class:`BuffState` to evaluate.
    fight_end_ms:
        The fight end time in milliseconds.
    fight_start_ms:
        The fight start time in milliseconds. Defaults to 0.

    Returns
    -------
    Uptime percentage in ``[0.0, 100.0]``.
    """
    interval_ms = fight_end_ms - fight_start_ms
    if interval_ms <= 0:
        return 0.0
    uptime = total_uptime_ms(state, fight_end_ms)
    pct = uptime / interval_ms * 100.0
    return max(0.0, min(100.0, pct))


def accumulate_buff_events(
    events: Iterable[BoonApplyEvent],
) -> dict[int, BuffState]:
    """Build per-skill-id :class:`BuffState` instances from a stream of :class:`BoonApplyEvent`s.

    Each unique ``skill_id`` in the stream gets its own
    :class:`BuffState`. The history is event-driven only (no
    pre-seed entry): the first event for a skill_id becomes the
    first history entry, and read-side functions
    (:func:`total_uptime_ms`, :func:`interval_uptime_pct`) treat the
    implicitly-0-stacks pre-first-event interval as 0-stacks.

    The 3-way ``kind`` discriminator translates to stack deltas:

    - ``apply``         -> ``new_stacks = current_stacks + event.stacks``
    - ``remove_single`` -> ``new_stacks = max(0, current_stacks - 1)``
    - ``remove_all``    -> ``new_stacks = 0``

    Parameters
    ----------
    events:
        The :class:`BoonApplyEvent` stream (typically the output of
        :meth:`PythonEvtcParser.parse_events` filtered to ``BoonApplyEvent``
        via :func:`isinstance`).

    Returns
    -------
    Mapping ``skill_id -> BuffState`` for every distinct skill_id
    in the stream. An empty stream returns ``{}``.

    Complexity
    ----------
    ``O(len(events) + distinct_skill_ids)``.
    """
    per_skill: dict[int, BuffState] = {}
    for event in events:
        skill_id = event.skill_id
        if skill_id not in per_skill:
            per_skill[skill_id] = BuffState()
        state = per_skill[skill_id]
        current_stacks = state.history[-1][1] if state.history else 0
        if event.kind == "apply":
            new_stacks = current_stacks + event.stacks
        elif event.kind == "remove_single":
            new_stacks = max(0, current_stacks - 1)
        elif event.kind == "remove_all":
            new_stacks = 0
        else:
            # Forward-compat fallback for any future ``kind`` literal
            # not in the current 3-way enumeration. Pydantic will raise
            # at validation time for unknowns today (the Literal[...] type
            # rejects unknown strings before this branch runs); the
            # fall-through keeps static-type narrowing complete and
            # would also catch any future ``kind`` Pydantic accepts but
            # the aggregator doesn't yet know about.
            new_stacks = current_stacks + event.stacks
        per_skill[skill_id] = state.append_stacks(event.time_ms, new_stacks)
    return per_skill


__all__ = [
    "BuffState",
    "NegativeStacksError",
    "NonMonotonicHistoryError",
    "accumulate_buff_events",
    "interval_uptime_pct",
    "total_uptime_ms",
]
