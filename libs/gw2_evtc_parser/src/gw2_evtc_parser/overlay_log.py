"""SCAFFOLD for the arcdps in-game overlay log (WAVE-8 v0.11.0 Blocker A.4.2).

This module is the SCAFFOLD for the new input format that the arcdps
in-game overlay logger writes alongside the EVTC binary: per-frame
player-action records (dodge / block / interrupt). The Wave 5 SCAFFOLD
docstrings on :class:`~gw2_core.DodgeEvent` + :class:`~gw2_core.BlockEvent`
+ :class:`~gw2_core.InterruptEvent` (in
:file:`libs/gw2_core/src/gw2_core/models.py`) call this out
explicitly: the EVTC binary does NOT surface these as statechange
records; the overlay logger is the canonical source.

WHY SCAFFOLD-zero
=================

The arcdps overlay log format has not been reverse-engineered end-to-end
in this repo. Until a format-spec landing lands in
:file:`docs/overlay-log-format.md` (NOT YET authored),
:func:`parse_overlay_events` is a well-typed stub that yields zero
events on every input. This SCAFFOLD-zero contract is the
backward-compat boundary that downstream consumers can rely on:

- ``defense.dodges`` + ``defense.blocks`` + ``defense.interrupts``
  columns stay at ``0`` (the existing Wave 5 SCAFFOLD-zero posture)
  until the format reverse-engineering lands.
- The CLI flag ``--overlay-log`` (deferred to a follow-up commit --
  see the A.4.2 plan section in ``plans/WAVE-8-parser-side.md`` §A.4.2)
  accepts a path, logs a warning that the format is pending, and
  continues with EVTC-only event emission (no crash, no exception,
  no spurious count).

SCAR-Safe preconditions before shipping production-realistic values
==================================================================

(Per the WAVE-8 v0.11.0 A.4.2 scari list + the F1 calibration pilot
post-mortem methodology. The 3 preconditions are sequential
additions -- each one unlocks the next deliverable.)

1. **Overlay log format reverse-engineering**: every record type +
   every attribute MUST be documented in
   :file:`docs/overlay-log-format.md` (NOT YET WRITTEN) before
   :func:`parse_overlay_events` returns a non-zero event count.
   Source for the format research: arcdps upstream
   (``<GW2-Arcdps-Mechanics-Log>/src/arcdps.h``) + Elite Insights C#
   (``<GW2-Elite-Insights-Parser>/GW2EIEvtcParser/ParserHelpers/``) +
   any community reverse-engineering write-up (gw2efficiency, etc.).

2. **Stream Merger**: the parser MUST merge the EVTC iterator +
   overlay iterator into a single chronologically-ordered event
   stream (per the thinker's SCAR analysis: dodge/block/interrupt
   records MUST share the EVTC epoch ``fight.started_at`` +
   ``time_ms`` so the per-player aggregator's time-windowing in
   :class:`~apps.gw2analytics_api.routes.fights.aggregators.PlayerDefenseAggregator`
   is correct. Without the merger, a down-state time_window = 0
   would silently mis-attribute block events during the down state
   + break the §6 ``Defense contribution DPS`` rollup).

3. **Real-fixture calibration pilot**: the merged event stream MUST
   be validated against the F1 calibration pilot's 12 real WvW
   fixtures (per the same F1 methodology that calibrated A.4.1's
   byte-48 lock + the A.4.3 cbtevent-derived event stream). A
   non-zero per-player ``dodges`` + ``blocks`` + ``interrupts``
   yield on a known fixture is the calibration gate.

The 3 preconditions are the reason this commit is SCAFFOLD-only --
the format-spec is the dominant blocker.

Backward compat
===============

Pre-A.4.2 callers are unaffected:

- ``PythonEvtcParser.parse_events(source)`` is unchanged (no new
  required parameters). The overlay log SCAFFOLD-zero contract is
  orthogonal to the existing dispatch table.

- ``apps/api/.../routes/fights/aggregators.py`` continues to read
  SCAFFOLD-zero counts from the defense section of the per-player
  readout payload. When the format-spec lands + parse_overlay_events
  yields a non-zero stream, the aggregator transitions to the
  real-yield surface WITHOUT a wire-contract bump (the
  :class:`~gw2_core.DodgeEvent` + :class:`~gw2_core.BlockEvent` +
  :class:`~gw2_core.InterruptEvent` Pydantic models already exist
  for the merge target).

Canonical reference for the future integration length:

- :file:`docs/statechange-ids.md` -- the existing arcdps
  ``StateChange`` enum reference (per the WAVE-8 A.4.1 commit).
- ``plans/WAVE-8-parser-side.md`` §A.4.2 -- the plan fragment.
- this module's ``__all__`` -- the SCAFFOLD surface.

A.4.2 ↔ A.4.3 layering boundary (cross-reference for the next sub-slice):
  A.4.2 is an **overlay-log stream** (a separate input file format
  arcdps writes alongside the EVTC binary). A.4.3 will derive
  DEATH + DOWN + CONDITION_REMOVE + CC events from the **EVTC
  cbtevent statechange bytes** via the A.4.1 dispatch table
  (:file:`gw2_evtc_parser.statechange_dispatch.STATECHANGE_MAP`) --
  NOT from :func:`parse_overlay_events`. The two streams are
  ortho: do NOT extend :class:`OverlayLogEvent` with cbtevent-derived
  fields (that breaks the layered design); instead, the A.4.3
  subclasses (:class:`~gw2_core.DeathEvent` /
  :class:`~gw2_core.DownEvent` / :class:`~gw2_core.ConditionRemoveEvent`
  / :class:`~gw2_core.CCEvent`) feed the shared Stream Merger that
  heapq.merges BOTH streams on the shared EVTC epoch.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class OverlayLogAction(StrEnum):
    """arcdps in-game overlay player-action kinds (per Wave 5 SCAFFOLD).

    The 3 canonical kinds awaited by the combat-readout §1 SCAFFOLD-zero
    columns (per ``plans/WAVE-8-parser-side.md`` §1):

    - ``defense.dodges`` -> :attr:`DODGE`
    - ``defense.blocks`` -> :attr:`BLOCK`
    - ``defense.interrupts`` -> :attr:`INTERRUPT`

    Attribute shape per the arcdps in-game overlay logger (canonical
    reference: ``<GW2-Arcdps-Mechanics-Log>/src/arcdps.h`` -- the
    ``cbtplayer`` event family). The 3 enumerated kinds are the
    in-scope surface for the §1 SCAFFOLD-zero columns; the future
    overlay log reverse-engineering may add more kinds (e.g.
    :attr:`RESURRECT`, :attr:`MOUNT`) -- those are NOT in this
    commit's scope and will land via the format-spec deliverable.
    """

    DODGE = "DODGE"
    BLOCK = "BLOCK"
    INTERRUPT = "INTERRUPT"


class OverlayLogEvent(BaseModel):
    """One arcdps in-game overlay log player-action record.

    SCAFFOLD shape mirror of :class:`~gw2_core.BaseEvent`. The
    ``action: OverlayLogAction`` discriminator differentiates the
    3 kinds (so the Stream Merger consumer can route per-kind to
    :class:`~gw2_core.DodgeEvent` + :class:`~gw2_core.BlockEvent` +
    :class:`~gw2_core.InterruptEvent` once the format is decoded).

    The forward-compat target_agent_id + skill_id Optional fields
    preserve :class:`~gw2_core.InterruptEvent`'s full :class:`BaseEvent`
    shape (per the gw2_core docstring: ``InterruptEvent`` carries
    target + skill for per-interrupt forensic attribution). The
    ``DODGE`` + ``BLOCK`` action kinds surface actor-only records
    (the `target_agent_id` + `skill_id` fields default to ``None``
    when not relevant, matching the gw2_core actor-only convention).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    time_ms: int = Field(
        ...,
        ge=0,
        description=(
            "Milliseconds since fight start. MUST share the EVTC epoch "
            "(fight.started_at) so the Stream Merger can heapq.merge() "
            "the overlay log stream against the EVTC cbtevent stream."
        ),
    )
    source_agent_id: int = Field(
        ...,
        ge=0,
        description=(
            "Actor agent id (the player who performed the dodge/block/"
            "interrupt). Mirrors :class:`~gw2_core.BaseEvent.source_agent_id`."
        ),
    )
    action: OverlayLogAction = Field(
        ...,
        description=(
            "Player-action kind discriminator. Routes the SCAFFOLD event "
            "to the matching gw2_core event subclass via the Stream Merger."
        ),
    )
    # InterruptEvent carries target + skill (per gw2_core.InterruptEvent
    # docstring). Dodge + Block are actor-only (defaulting the optional
    # target_agent_id + skill_id to ``None``).
    target_agent_id: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Target agent id (the enemy whose cast was interrupted, for "
            "INTERRUPT records). None for DODGE + BLOCK (actor-only)."
        ),
    )
    skill_id: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Skill id (the interrupt mechanic, for INTERRUPT records). "
            "None for DODGE + BLOCK (actor-only)."
        ),
    )


def parse_overlay_events(
    path: Path | str | None = None,
) -> Iterator[OverlayLogEvent]:
    """SCAFFOLD stub for the arcdps in-game overlay log parser.

    .. warning::

       SCAFFOLD-zero contract: until the overlay log format is
       reverse-engineered (``docs/overlay-log-format.md`` -- pending),
       this function yields zero events on any input. Callers should
       treat zero-yield as the canonical SCAFFOLD-zero surface; the
       pending format-spec deliverable is the go-signal for
       event-yield realism.

    Args:
        path: Optional path to the arcdps in-game overlay log file.
            When provided, the function logs a :data:`logging.warning`
            noting the format-spec is pending + the path is NOT yet
            consumed. When ``None``, the SCAFFOLD-zero contract holds
            silently (zero events, no log spam).

    Yields:
        :class:`OverlayLogEvent` records in chronological order.
        SCAFFOLD-zero: yields zero events for ALL inputs (existing
        files, non-existent paths, missing CLI flags, etc.) until the
        format-spec deliverable lands. A future yield-realistic
        implementation will read the overlay log records, normalise
        per-kind fields, and yield in time_ms-ascending order so the
        Stream Merger can heapq.merge() against the EVTC event stream.

    Side effects:
        Logs one :data:`logger.warning` per invocation when ``path``
        is provided. No file I/O. No network I/O. No heuristic
        inference from the EVTC payload.

    SCAR-Safe preconditions before flipping the SCAFFOLD-zero stub:
        See the module docstring + ``plans/WAVE-8-parser-side.md``
        §A.4.2. The 3 preconditions are sequential; each unlocks the
        next deliverable. Flipping the SCAFFOLD-zero stub without
        the preconditions is a SCAR-risk regression.
    """
    if path is not None:
        logger.warning(
            "gw2_evtc_parser.overlay_log.parse_overlay_events(%r) "
            "was called but the arcdps overlay-log format reverse-engineering "
            "is pending (see docs/overlay-log-format.md - not yet authored). "
            "SCAFFOLD-zero: zero events yielded until the format-spec lands. "
            "Pre-A.4.2 callers are unaffected because the existing "
            "PythonEvtcParser.parse_events() surface is unchanged.",
            str(path),
        )
    # SCAFFOLD-zero: empty iterator (NOT ``None``, NOT ``[]``) so
    # downstream ``for e in parse_overlay_events(path): ...`` works
    # (no ``TypeError: 'NoneType' object is not iterable``), and
    # ``len(list(parse_overlay_events(path))) == 0`` is type-honest.
    # An empty tuple iterator (`iter(())`) is the canonical SCAFFOLD
    # representation — NOT a `yield`-based generator (functionally
    # identical, but reads differently to mypy strict mode on
    # `-> Iterator[X]`.
    return iter(())
    # Format-realistic yield (deferred to the format-spec deliverable):
    #
    #   1. Open ``path`` (the arcdps overlay log file format TBD).
    #   2. Read records line-by-line (or struct-decoded if the format
    #      is binary -- the format-spec deliverable decides).
    #   3. For each record, normalise the per-kind fields:
    #      - DODGE may carry a SUCCEEDED/FAILED flag + the dodge-roll
    #        window time_ms delta.
    #      - BLOCK may carry an angle-of-block + the per-block damage
    #        absorbed.
    #      - INTERRUPT carries the casted skill_id of the interrupted
    #        skill + the target agent_id (per gw2_core.InterruptEvent
    #        forensic contract).
    #   4. Build :class:`OverlayLogEvent` records with the matching
    #      ``action`` discriminator + the (Optional) target_agent_id
    #      + skill_id.
    #   5. Yield them in time_ms-ascending order so the Stream Merger
    #      can heapq.merge() them against the EVTC event stream.
    #   See the module docstring for the Stream Merger precondition.


__all__ = [
    "OverlayLogAction",
    "OverlayLogEvent",
    "parse_overlay_events",
]
