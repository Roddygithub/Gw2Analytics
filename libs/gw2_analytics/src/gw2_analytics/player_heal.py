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

from collections import defaultdict
from collections.abc import Callable, Iterable
from itertools import pairwise
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from gw2_core import HealingEvent
from gw2_core._scaffold import default_barrier_portion_from_healing

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
    # Optional player-name denormalisation (mirrors TargetHealingRow.name
    # convention for grep-ability + diff-based maintenance). Strict
    # parallel of the target-side row.
    name: str | None = None


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
        v0.10.23 SCAFFOLD path), the substitute
        :func:`gw2_core._scaffold.default_barrier_portion_from_healing`
        returns ``0`` -- the no-barrier fallback that preserves
        the pre-Phase-6-v2 wire shape where
        ``barrier_total=0, barrier_ps=0.0``. Phase 6 v2 wires the
        parser-side barrier lookup; the SCAFFOLD absorbs the swap
        via one constructor change.

        Empty input yields ``[]`` -- no placeholder row.
        """
        if duration_s < 0:
            msg = f"duration_s must be >= 0, got {duration_s!r}"
            raise ValueError(msg)

        # SCAFFOLD substitution: when ``barrier_portion_getter is
        # None``, substitute the canonical SCAFFOLD default so the
        # aggregator's hot loop never branches on "did the caller
        # wire the getter?". One-line substitute vs an if/else per
        # event.
        barrier = (
            barrier_portion_getter
            if barrier_portion_getter is not None
            else default_barrier_portion_from_healing
        )

        total_by_source: dict[int, int] = defaultdict(int)
        count_by_source: dict[int, int] = defaultdict(int)
        barrier_by_source: dict[int, int] = defaultdict(int)
        grand_total = 0
        for e in events:
            total_by_source[e.source_agent_id] += e.healing
            count_by_source[e.source_agent_id] += 1
            grand_total += e.healing
            # Per-event SCAFFOLD barrier: the SCAFFOLD path
            # consumes the heal hit once, returning 0; the
            # post-Phase-6-v2 path queries the parser-side barrier
            # table (shared with the damage-side barrier table +
            # the per-heal barrier side). The hot-loop cost is one
            # C-level function call per event.
            barrier_by_source[e.source_agent_id] += barrier(e)

        hps_factor = 1.0 / duration_s if duration_s > 0 else _DEFAULT_HPS
        # ``name_map or {}`` -- see the parallel branch in
        # :meth:`~gw2_analytics.target_dps.TargetDpsAggregator.aggregate`
        # for the rationale (``dict.get`` returns ``None`` for
        # missing keys AND for explicit ``None`` values; both
        # surface as the ``name=None`` sentinel on the row).
        rows = [
            PlayerHealRow(
                source_agent_id=source,
                total_healing=total_by_source[source],
                heal_count=count_by_source[source],
                hps=total_by_source[source] * hps_factor,
                barrier_total=barrier_by_source[source],
                barrier_ps=barrier_by_source[source] * hps_factor,
                name=(name_map or {}).get(source),
            )
            for source in total_by_source
        ]
        # Sort: highest total_healing first; ties broken by ascending source_agent_id.
        rows.sort(key=lambda r: (-r.total_healing, r.source_agent_id))

        self._check_invariants(rows, grand_total, duration_s)
        return rows

    @staticmethod
    def _check_invariants(
        rows: list[PlayerHealRow],
        expected_sum: int,
        duration_s: float,
    ) -> None:
        """Raise ``ValueError`` if any cross-field invariant is violated.

        Invariants checked (Phase 6 v2 SCAFFOLD addition):
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
        """
        actual_sum = sum(r.total_healing for r in rows)
        if actual_sum != expected_sum:
            msg = (
                f"sum of row.total_healing ({actual_sum}) != sum of event.healing ({expected_sum})"
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
        for prev, curr in pairwise(rows):
            if prev.total_healing < curr.total_healing:
                msg = (
                    f"rows not ordered by (total_healing DESC, "
                    f"source_agent_id ASC): {prev!r} then {curr!r}"
                )
                raise ValueError(msg)
            if (
                prev.total_healing == curr.total_healing
                and prev.source_agent_id >= curr.source_agent_id
            ):
                msg = (
                    f"tie on total_healing not broken by "
                    f"source_agent_id ASC: {prev!r} then {curr!r}"
                )
                raise ValueError(msg)


__all__ = ["HealBarrierGetter", "PlayerHealAggregator", "PlayerHealRow"]
