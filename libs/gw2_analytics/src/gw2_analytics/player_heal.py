"""

Wave 3 / Tour 5 v0.10.23-pre: per-player healing roll-ups.

Workstream D of plan 045 (Combat readout, per ``docs/v0.9.0-combat-readout-design.md``
section 4). The Combat readout's ``Heal`` table is keyed on the
PLAYER who DEALT the heal (source-side attribution), not the
target (receiver). This module is the strict parallel of
:mod:`gw2_analytics.target_healing` with the grouping axis flipped
from ``target_agent_id`` (``TargetHealingRow``) to
``source_agent_id`` (``PlayerHealRow``); the input event stream is
unchanged (still ``Iterable[HealingEvent]``).

Conventions
===========

This module strictly mirrors :mod:`gw2_analytics.target_healing` for
diff-based maintenance -- the only structural differences are the
class names + the field-from-event datum (``e.source_agent_id``
vs ``e.target_agent_id``) + the row field rename. The conventions
below are inherited verbatim so the per-target + per-player
aggregator pair reads as one design.

- **Deterministic ordering.** Rows sorted by
  ``(-total_healing, source_agent_id)`` -- highest healing first;
  ties broken by ascending ``source_agent_id``. Two runs over the
  same input MUST yield byte-identical row output.
- **No defaults invented.** Empty input yields ``[]``; we never
  synthesise a placeholder row.
- **HPS = ``total_healing / duration_s`` when ``duration_s > 0``.``
  When ``duration_s == 0`` we emit ``hps=0.0`` (zero-duration is a
  sentinel "duration not provided" rather than a math singularity).
  The GW2 community standard term for the outgoing-heal rate is
  ``HPS`` (healing per second) -- documented inline so future
  readers do not have to grep the dashboard code to learn the
  abbreviation. Negative duration is rejected.

.. admonition:: Phase 6 v2 SCAFFOLD: barrier-applied split
   :class: tip

   Wave 6 added the ``barrier_total`` + ``barrier_ps`` rate columns
   + the pluggable ``barrier_portion_getter`` callable to thread
   the future parser-side per-heal ``barrier`` side table through
   the aggregator with ZERO wire-shape mutation cost. The
   CANONICAL v0.10.23 SCAFFOLD path leaves
   ``barrier_portion_getter=None`` which the aggregator internally
   substitutes with
   :func:`gw2_core._scaffold.default_barrier_portion_from_healing`
   (the zero-fallback) so the wire-shape stays ``barrier_total=0 +
   barrier_ps=0.0`` for pre-Phase-6-v2 streams. Phase 6 v2 closes
   over the parser-side barrier lookup; the SCAFFOLD absorbs the
   swap with a one-argument constructor change.

Cross-field invariants (validated post-construction; violations
raise ``ValueError``; Pydantic field constraints also enforce each
per-cell constraint):

- Sum of ``row.total_healing`` across all rows == sum of
  ``event.healing`` across input events (no event dropped, no
  double-counting).
- Sum of ``row.barrier_total`` across all rows == sum of
  ``barrier_portion_getter(e)`` across input events (the
  barrier-getter conservation contract).
- Rows monotonically non-increasing by ``total_healing``; ties
  broken by ascending ``source_agent_id``.
- Every row has ``heal_count >= 1``.
- For every row, ``abs(barrier_ps - barrier_total * (1.0 /
  duration_s)) < 1e-6`` when ``duration_s > 0`` (rate equality).

Forward compat
==============

The Combat readout's ``Heal`` table extends the per-player heal
output with a ``barrier_total`` column (the upcoming
``PlayerReadoutHealOut`` wire shape's barrier column). Barrier
separation is OOS for this Wave 3 aggregator (added in a follow-up
tour once the parser surfaces barrier events; the current
:mod:`gw2_core` ``HealingEvent`` does NOT carry a ``barrier`` field
yet).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from gw2_analytics._invariants import check_desc_asc_ordering
from gw2_core import HealingEvent, StunBreakEvent

# HPS sentinel when ``duration_s <= 0``: invalid (zero/negative)
# duration collapses to 0.0 rather than raising -- the canonical
# ``HealingEvent`` stream from the parser will always pair with a
# known fight duration so the zero path is purely defensive.
_DEFAULT_HPS: Final[float] = 0.0

#: Type signature (PEP 695 ``type`` statement) for the SCAFFOLD
#: barrier-getter (mirror of the damage-side
#: :data:`DpsSplitGetter`). The callable receives one
#: :class:`~gw2_core.HealingEvent` and returns the integer
#: ``barrier`` portion applied by that heal hit. Mirrors the
#: canonical ``barrier_portion_getter`` contract on
#: :class:`~gw2_analytics.player_defense.PlayerDefenseAggregator`
#: so the getters are interchangeable after Phase 6 v2 (the
#: parser-side barrier table is shared between damage + heal
#: streams).
# PEP 695 type statement; mypy may flag runtime use because mypy's strict
# Callable inference treats `type X = Callable[...]` differently from
# runtime-checked `Callable[...]`-typed aliases; the `type: ignore`
# suppresses the irrelevant strict-mode flag.
type HealBarrierGetter = Callable[[HealingEvent], int]


class PlayerHealRow(BaseModel):
    """One roll-up row: healing + HPS dealt BY a single player agent.

    The ``source_agent_id`` is the agent DISHING OUT the heal
    (mirrors the semantics of
    :class:`~gw2_analytics.target_healing.TargetHealingRow` but with
    the grouping axis flipped from the receiving end to the dealing
    end). For "top healers" + Combat readout ``Heal`` table (per
    ``docs/v0.9.0-combat-readout-design.md`` §4), this is the
    right axis.

    **Naming NIT (the convention-break vs the per-target side):**
    the per-player row uses the single-syllable ``Heal``
    (matching the wire-shape class
    :class:`~gw2analytics_api.schemas.fight.PlayerReadoutHealOut`
    AND the design doc §5.1 JSON ``"heal": {...}`` key), while
    the per-target row uses the full-syllable ``Healing``
    (:class:`~gw2_analytics.target_healing.TargetHealingRow`).
    The divergence mirrors the per-target + per-player wire-shape
    split: the existing ``TargetHealing`` (Phase 7 v1) predates
    the design doc convention; the new ``PlayerHeal`` aligns to
    it so the aggregator row + the wire-shape class + the JSON
    key all share the same ``Heal`` sub-word downstream.
    Annotating the break here so a future maintainer greping
    ``Healing`` doesn't accidentally miss the per-player
    :class:`PlayerHeal` (mirror fix path:
    ``grep -nEi 'Heal(ing)?'`` covers both).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_agent_id: int = Field(..., ge=0)
    total_healing: int = Field(..., ge=0)
    heal_count: int = Field(..., ge=1)
    hps: float = Field(..., ge=0.0)
    # Phase 6 v2 SCAFFOLD (Wave 6): barrier-applied total +
    # barrier-per-second rate. Pre-Phase-6-v2 SCAFFOLD:
    # ``barrier_total=0, barrier_ps=0.0`` (the canonical
    # "no side-table" wire shape). Wire-shape contract:
    # ``barrier_ps == barrier_total / duration_s`` within ``1e-6``
    # tolerance for ``duration_s > 0``.
    barrier_total: int = Field(
        default=0,
        ge=0,
        description=(
            "Phase 6 v2 SCAFFOLD: barrier applied by this player's "
            "heals across the fight. Pre-Phase-6-v2 streams "
            "return 0; the SCAFFOLD absorbs the parser-side "
            "barrier table with zero schema migration."
        ),
    )
    barrier_ps: float = Field(
        default=_DEFAULT_HPS,
        ge=0.0,
        description=(
            "Phase 6 v2 SCAFFOLD: barrier per-second rate. Pre-"
            "Phase-6-v2 streams return 0.0; the SCAFFOLD absorbs "
            "the parser-side barrier table when Phase 6 v2 lands."
        ),
    )
    # Tour 6 v0.10.24 close-out: per-fight count of
    # :class:`~gw2_core.StunBreakEvent` rows where this player is
    # the ``source_agent_id`` (actor-side attribution -- the
    # player broke the stun). Pre-Tour-6 SCAFFOLD: ``stun_breaks=0``.
    # Combat readout ``Heal`` table ``Breakstunt`` column per
    # ``docs/v0.9.0-combat-readout-design.md`` §4. Source-attributed
    # because the player RECEIVED the breakstunt credit (the
    # Phase 9 v2 rule -- the player who broke the stun); the
    # counter lives on the Heal aggregator rather than the
    # Defense aggregator because the design doc groups ``stun_breaks``
    # with the Heal aspect (not the Defense aspect).
    stun_breaks: int = Field(
        default=0,
        ge=0,
        description=(
            "Tour 6 v0.10.24 close-out: per-fight count of "
            "StunBreakEvent rows where this player is the source "
            "agent (the player broke the stun). Pre-Tour-6 "
            "streams return 0; the Wave 5 SCAFFOLD landed the "
            "StunBreakEvent subclass and Tour 6 wires the "
            "aggregator to count by source_agent_id."
        ),
    )
    # Optional player-name denormalisation (mirrors TargetHealingRow.name
    # convention for grep-ability + diff-based maintenance). Strict
    # parallel of the target-side row.
    name: str | None = None


@dataclass(slots=True)
class _HealAccumulator:
    """Mutable accumulator for one source agent's healing statistics."""

    total_healing: int = 0
    heal_count: int = 0
    barrier: int = 0
    stun_breaks: int = 0


class PlayerHealAggregator:
    """Stateless aggregator: heal events -> per-player HPS roll-up rows.

    Mirror of
    :class:`~gw2_analytics.target_healing.TargetHealingAggregator`
    with the grouping axis flipped from ``target_agent_id`` to
    ``source_agent_id``. Instantiate once and reuse -- the class
    holds no state.
    """

    def aggregate(
        self,
        events: Iterable[HealingEvent],
        duration_s: float,
        name_map: dict[int, str | None] | None = None,
        barrier_portion_getter: HealBarrierGetter | None = None,
        stun_break_events: Iterable[StunBreakEvent] = (),
    ) -> list[PlayerHealRow]:
        """Compute the per-player heal roll-up.

        ``duration_s`` is the fight duration (the time-bucket the
        HPS rate is measured against). Passed by the caller so the
        aggregator stays free of cross-source metadata.

        ``name_map`` is an OPTIONAL ``{agent_id: name}`` lookup for
        player-name denormalisation. See
        :meth:`~gw2_analytics.target_healing.TargetHealingAggregator.aggregate`
        for the full contract; this method is a strict parallel.

        ``barrier_portion_getter`` is OPTIONAL and provides the
        per-event ``barrier`` portion of a heal hit (mirrors the
        damage-side :func:`~gw2_analytics.player_defense.PlayerDefenseAggregator.aggregate`'s
        ``barrier_portion_getter``). When ``None`` (the canonical
        v0.10.23 SCAFFOLD path), the hot loop skips the barrier
        call entirely and the ``barrier`` accumulator stays at
        ``0`` -- the no-barrier fallback that preserves the
        pre-Phase-6-v2 wire shape where
        ``barrier_total=0, barrier_ps=0.0``. Phase 6 v2 wires the
        parser-side barrier lookup; the SCAFFOLD absorbs the swap
        via one constructor change.

        ``stun_break_events`` is OPTIONAL and provides the
        :class:`~gw2_core.StunBreakEvent` stream for the
        ``stun_breaks`` counter (Tour 6 v0.10.24 close-out). Each
        row contributes ``+1`` to the ``stun_breaks`` column of
        the row keyed on ``event.source_agent_id``. When empty
        (canonical pre-Tour-6 SCAFFOLD path), every row has
        ``stun_breaks=0``. The breakstunt attribution is
        actor-side -- the player who broke the stun gets the
        credit (per the design doc §4 + Phase 9 v2 breakstunt rule).

        Empty input across ALL streams (heal + stun_break) yields
        ``[]`` -- no placeholder row.
        """
        if duration_s < 0:
            msg = f"duration_s must be >= 0, got {duration_s!r}"
            raise ValueError(msg)

        stats_by_source: dict[int, _HealAccumulator] = defaultdict(_HealAccumulator)

        # Hoist the barrier-getter branch outside the hot loop so
        # the canonical SCAFFOLD path (``barrier_portion_getter is
        # None``) avoids a Python function call per event. The
        # explicit getter path pays the call cost only when a real
        # parser-side side-table is wired.
        if barrier_portion_getter is not None:
            barrier = barrier_portion_getter
            for e in events:
                acc = stats_by_source[e.source_agent_id]
                acc.total_healing += e.healing
                acc.heal_count += 1
                acc.barrier += barrier(e)
        else:
            for e in events:
                acc = stats_by_source[e.source_agent_id]
                acc.total_healing += e.healing
                acc.heal_count += 1

        # Tour 6 v0.10.24 close-out: per-source-agent stun-break
        # counter loop. Actor-side attribution (the player who
        # broke the stun is encoded as ``source_agent_id`` per the
        # actor-only :class:`~gw2_core.StunBreakEvent` shape).
        # Use C-level Counter for the pure-counting stream.
        stun_break_counts = Counter(sb.source_agent_id for sb in stun_break_events)
        for agent_id, count in stun_break_counts.items():
            stats_by_source[agent_id].stun_breaks = count

        hps_factor = 1.0 / duration_s if duration_s > 0 else _DEFAULT_HPS
        # ``name_map or {}`` -- see the parallel branch in
        # :meth:`~gw2_analytics.target_dps.TargetDpsAggregator.aggregate`
        # for the rationale (``dict.get`` returns ``None`` for
        # missing keys AND for explicit ``None`` values; both
        # surface as the ``name=None`` sentinel on the row).
        safe_name_map = name_map or {}
        rows = [
            PlayerHealRow(
                source_agent_id=source,
                total_healing=acc.total_healing,
                heal_count=acc.heal_count if acc.heal_count > 0 else 1,
                hps=acc.total_healing * hps_factor,
                barrier_total=acc.barrier,
                barrier_ps=acc.barrier * hps_factor,
                stun_breaks=acc.stun_breaks,
                name=safe_name_map.get(source),
            )
            for source, acc in stats_by_source.items()
        ]
        # Sort: highest total_healing first; ties broken by ascending source_agent_id.
        rows.sort(key=lambda r: (-r.total_healing, r.source_agent_id))

        # Tour 6 v0.10.24 close-out: the stun-break conservation
        # invariant (sum of per-row stun_breaks must equal the
        # total :class:`~gw2_core.StunBreakEvent` input count).
        # We sum the per-source-agent counter map because the
        # :class:`~gw2_core.StunBreakEvent` shape is actor-only
        # (one event = ``+1`` to the source-agent's counter).
        expected_stun_break_total = sum(
            acc.stun_breaks for acc in stats_by_source.values()
        )
        # The invariant total is derived from the aggregated rows
        # rather than accumulated in the hot loop, saving one integer
        # addition per input event.
        self._check_invariants(
            rows,
            sum(r.total_healing for r in rows),
            duration_s,
            expected_stun_break_total,
        )
        return rows

    @staticmethod
    def _check_invariants(
        rows: list[PlayerHealRow],
        expected_sum: int,
        duration_s: float,
        # Reviewer #1 fix: drop the `= 0` default. The aggregator
        # always passes the actual total (derived from
        # ``sum(acc.stun_breaks for acc in stats_by_source.values())``
        # upstream); making this arg required eliminates a
        # silent-failure trap if a future caller invokes
        # ``_check_invariants`` directly without thinking about the parm.
        expected_stun_break_total: int,
    ) -> None:
        """Raise ``ValueError`` if any cross-field invariant is violated.

        Invariants checked (Phase 6 v2 SCAFFOLD addition + Tour 6
        v0.10.24 stun-break conservation):
        1. Sum of ``row.total_healing`` == ``expected_sum`` (no
           event dropped on the source side).
        2. For every row, ``abs(barrier_ps - barrier_total /
           duration_s) < 1e-6`` when ``duration_s > 0`` (rate
           equality -- the SCAFFOLD path trivially satisfies; the
           post-Phase-6-v2 path enforces it so a buggy getter is
           caught at aggregator time).
        3. ``heal_count >= 1`` (Pydantic field constraint;
           redundant but explicit).
        4. Rows monotonic non-increasing by ``total_healing``;
           ties broken by ascending ``source_agent_id``.
        5. Sum of ``row.stun_breaks`` across all rows ==
           ``expected_stun_break_total`` (Tour 6 close-out: the
           :class:`~gw2_core.StunBreakEvent` count conservation
           contract; the canonical Wave 5 SCAFFOLD path with an
           empty iterable leaves every row ``stun_breaks=0`` which
           trivially satisfies when
           ``expected_stun_break_total=0``).
        """
        actual_sum = sum(r.total_healing for r in rows)
        if actual_sum != expected_sum:
            msg = (
                f"sum of row.total_healing ({actual_sum}) != sum of event.healing ({expected_sum})"
            )
            raise ValueError(msg)
        # Tour 6 v0.10.24 close-out: stun-break conservation.
        actual_stun_break_total = sum(r.stun_breaks for r in rows)
        if actual_stun_break_total != expected_stun_break_total:
            msg = (
                f"sum of row.stun_breaks ({actual_stun_break_total}) "
                f"!= count of StunBreakEvent input ({expected_stun_break_total}); "
                # The earlier ``expected_stun_break_total = 0`` default
                # has been retired -- the only path through this branch
                # is from ``aggregate`` (which always derives the
                # total upstream), so the trap is closed at the type
                # level (required positional arg).
                f"this signals a broken invariant in the dispatcher."
            )
            raise ValueError(msg)
        if duration_s > 0:
            # Rate equality: barrier_ps must equal
            # barrier_total / duration_s. Tolerance: 1e-6 covers
            # IEEE-754 rounding noise from the for-loop float
            # multiplication; exact equality would flag benign
            # rounding.
            for r in rows:
                expected_ps = r.barrier_total / duration_s
                rate_delta = abs(r.barrier_ps - expected_ps)
                if rate_delta > 1e-6:
                    msg = (
                        f"PlayerHealRow({r.source_agent_id}): "
                        f"rate equality violated -- "
                        f"barrier_ps ({r.barrier_ps}) != "
                        f"barrier_total / duration_s "
                        f"({expected_ps}); "
                        f"|delta| ({rate_delta:.3e}) > 1e-6"
                    )
                    raise ValueError(msg)
        for r in rows:
            if r.heal_count < 1:
                msg = f"PlayerHealRow({r.source_agent_id}).heal_count ({r.heal_count}) must be >= 1"
                raise ValueError(msg)
        # Pydantic field constraints already guarantee ``ge=0`` for total_healing;
        # the cross-row ordering invariant is the only ordering contract.
        check_desc_asc_ordering(
            rows,
            primary_key=lambda r: r.total_healing,
            secondary_key=lambda r: r.source_agent_id,
            primary_label="total_healing",
            secondary_label="source_agent_id",
        )


__all__ = ["HealBarrierGetter", "PlayerHealAggregator", "PlayerHealRow"]
