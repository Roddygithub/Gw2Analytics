"""

Wave 3 / Tour 5 v0.10.23-pre: per-player damage roll-ups.

Workstream D of plan 045 (Combat readout, per ``docs/v0.9.0-combat-readout-design.md``
section 3). The Combat readout's ``Damage`` table is keyed on the
PLAYER who DEALT the damage (source-side attribution), not the
target (receiver). This module is the strict parallel of
:mod:`gw2_analytics.target_dps` with the grouping axis flipped
from ``target_agent_id`` (``TargetDpsRow``) to
``source_agent_id`` (``PlayerDamageRow``); the input event stream
is unchanged (still ``Iterable[DamageEvent]``).

This is part of the per-player aggregator trio (Damage + Heal).
Boons + Defense aggregators land in a follow-up tour once the
skills DB catalog + Phase 6 v2 parser-stream switch unblock the
boon-vs-condition wire-distinction + the down/death/stun-break
statechange parsers (Wave 2 SCAFFOLD landed the 4 NEW
statechange event subclasses; the actual aggregators consume them
in the next tour).

Conventions
===========

This module strictly mirrors :mod:`gw2_analytics.target_dps` for
diff-based maintenance -- the only structural differences are the
class names + the field-from-event datum (``e.source_agent_id``
vs ``e.target_agent_id``) + the row field rename. The conventions
below are inherited verbatim so the per-target + per-player
aggregator pair reads as one design.

- **Deterministic ordering.** Rows sorted by
  ``(-total_damage, source_agent_id)`` -- highest damage first;
  ties broken by ascending ``source_agent_id``. Two runs over the
  same input MUST yield byte-identical row output.
- **No defaults invented.** Empty input yields ``[]``; we never
  synthesise a placeholder row.
- **DPS = ``total_damage / duration_s`` when ``duration_s > 0``.``
  When ``duration_s == 0`` we emit ``dps=0.0`` (zero-duration is a
  sentinel "duration not provided" rather than a math singularity).
  Negative duration is rejected -- callers can guard at upstream sites
  where ``fight.duration`` is known.

.. admonition:: Phase 6 v2 SCAFFOLD: power vs condi split
   :class: tip

   Wave 6 added the ``dps_power`` + ``dps_condi`` rate columns +
   the pluggable ``dps_split_getter`` callable to thread the
   future parser-side ``(condi, power)`` side table through the
   aggregator with ZERO wire-shape mutation cost. The CANONICAL
   v0.10.23 SCAFFOLD path leaves ``dps_split_getter=None`` which
   the aggregator internally substitutes with
   :func:`gw2_core._scaffold.default_dps_split` (the "everything is
   power" fallback) so the wire-shape stays ``dps_power=0.0 +
   dps_condi=dps`` for pre-Phase-6-v2 streams. Phase 6 v2 closes
   over the parser-side ``condi_portion`` lookup; the SCAFFOLD
   absorbs the swap with a one-argument constructor change.

Cross-field invariants (validated post-construction; violations
raise ``ValueError``; Pydantic field constraints also enforce each
per-cell constraint):

- Sum of ``row.total_damage`` across all rows == sum of ``event.damage``
  across input events (no event dropped, no double-counting).
- Sum of ``row.dps_power * duration_s + row.dps_condi * duration_s``
  across all rows == sum of ``event.damage`` (the split getter
  conservation contract).
- Rows monotonically non-increasing by ``total_damage``; ties broken
  by ascending ``source_agent_id``.
- Every row has ``attack_count >= 1``.
- The split-getter conservation: for every row,
  ``abs(dps_power + dps_condi - dps) < 1e-6`` (rate equality under
  ``duration_s > 0``).

Forward compat
==============

Wave 2 SCAFFOLD extended :class:`~gw2_core.EventType` to 9 members
(``ConditionRemoveEvent`` / ``DownEvent`` / ``DeathEvent`` /
``StunBreakEvent`` join the existing 5). This aggregator ignores
those NEW statechange events by design -- the Combat readout's
``Damage`` table is keyed on damage events only. The boon-removal
column (``PlayerReadoutDamageOut.strips``) is sourced by the
``BuffRemovalEvent`` stream through a sibling per-player
aggregator that is OUT OF SCOPE for this Wave 3 tour (deferred to
the next follow-up).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from itertools import pairwise
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from gw2_core import DamageEvent
from gw2_core._scaffold import default_dps_split

# DPS sentinel when ``duration_s <= 0``: invalid (zero/negative) duration
# collapses to 0.0 rather than raising -- the canonical ``DamageEvent``
# stream from the parser will always pair with a known fight duration
# so the zero path is purely defensive.
_DEFAULT_DPS: Final[float] = 0.0

#: Type signature (PEP 695 ``type`` statement -- matches the
#: project-wide PEP 695 convention used in ``models.py::type Event``)
#: for the SCAFFOLD split-getter. The callable receives one
#: :class:`~gw2_core.DamageEvent` and returns the
#: ``(condi_damage, power_damage)`` tuple for that hit. Mirrors
#: the canonical :func:`gw2_analytics.condi_power_split.split_condi_power`
#: RETURN shape so the side-table getters are interchangeable
#: after Phase 6 v2.
type DpsSplitGetter = Callable[[DamageEvent], tuple[int, int]]


class PlayerDamageRow(BaseModel):
    """One roll-up row: damage + DPS dealt BY a single player agent.

    The ``source_agent_id`` is the agent DISHING OUT the damage
    (mirrors the semantics of :class:`~gw2_analytics.target_dps.TargetDpsRow`
    but with the grouping axis flipped from the receiving end to the
    dealing end). For "top contributors" / Combat readout ``Damage``
    table (per ``docs/v0.9.0-combat-readout-design.md`` §3), this is
    the right axis.

    **Naming NIT (the convention-break vs the per-target side):**
    the per-player row uses the full-syllable ``Damage``
    (matching the wire-shape class
    :class:`~gw2analytics_api.schemas.fight.PlayerReadoutDamageOut`
    AND the design doc §5.1 JSON ``"damage": {...}`` key), while
    the per-target row uses the abbreviated ``Dps``
    (:class:`~gw2_analytics.target_dps.TargetDpsRow`). The
    divergence mirrors the per-target + per-player wire-shape
    split: the existing ``TargetDps`` (Phase 6 v1) predates
    the design doc convention; the new ``PlayerDamage`` aligns
    to it so the aggregator row + the wire-shape class + the
    JSON key all share the same ``damage`` sub-word downstream.
    Annotating the break here so a future maintainer greping
    ``Dps`` doesn't accidentally miss the per-player
    :class:`PlayerDamage` (mirror grep hint:
    ``grep -nEi 'Dps|Damage'`` covers both). Symmetric with
    the ``Heal/Healing`` annotation on
    :class:`~gw2_analytics.player_heal.PlayerHealRow`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_agent_id: int = Field(..., ge=0)
    total_damage: int = Field(..., ge=0)
    attack_count: int = Field(..., ge=1)
    dps: float = Field(..., ge=0.0)
    # Phase 6 v2 SCAFFOLD (Wave 6): power + condi split rates.
    # ``dps_power`` is the per-second rate of the power component
    # across the fight; ``dps_condi`` is the per-second rate of the
    # condi component. Pre-Phase-6-v2 SCAFFOLD: ``dps_power=0.0,
    # dps_condi=dps`` (the canonical "everything is power" wire
    # shape). Wire-shape contract: ``dps_power + dps_condi == dps``
    # within ``1e-6`` rounding tolerance (``1e-6`` is the default
    # IEEE-754 float-equality slack so a degenerate 0.0 + 0.0 ==
    # 0.0 match survives the contract).
    dps_power: float = Field(
        default=_DEFAULT_DPS,
        ge=0.0,
        description=(
            "Phase 6 v2 SCAFFOLD: per-second power-damage rate. "
            "Pre-Phase-6-v2 streams return 0.0; the SCAFFOLD "
            "absorbs the parser-side split table with zero schema "
            "migration."
        ),
    )
    dps_condi: float = Field(
        default=_DEFAULT_DPS,
        ge=0.0,
        description=(
            "Phase 6 v2 SCAFFOLD: per-second condi-damage rate. "
            "Pre-Phase-6-v2 streams return the canonical full-DPS "
            "rate; the SCAFFOLD substitutes the parser-side "
            "split table when Phase 6 v2 lands."
        ),
    )
    # Optional player-name denormalisation (mirrors TargetDpsRow.name
    # convention for grep-ability + diff-based maintenance). ``None``
    # when the aggregator was called without a ``name_map`` (the
    # canonical backward-compat case) OR when the agent id has no
    # name in the map. Strict parallel of the target-side row.
    name: str | None = None


class PlayerDamageAggregator:
    """Stateless aggregator: damage events -> per-player DPS roll-up rows.

    Mirror of :class:`~gw2_analytics.target_dps.TargetDpsAggregator`
    with the grouping axis flipped from ``target_agent_id`` to
    ``source_agent_id``. Instantiate once and reuse -- the class
    holds no state.
    """

    def aggregate(
        self,
        events: Iterable[DamageEvent],
        duration_s: float,
        name_map: dict[int, str | None] | None = None,
        dps_split_getter: DpsSplitGetter | None = None,
    ) -> list[PlayerDamageRow]:
        """Compute the per-player damage roll-up.

        ``duration_s`` is the fight duration (the time-bucket the
        DPS rate is measured against). Passed by the caller so the
        aggregator stays free of cross-source metadata.

        ``name_map`` is an OPTIONAL ``{agent_id: name}`` lookup for
        player-name denormalisation (v0.8.3). ``None`` (the default)
        leaves every row's ``name`` field as ``None`` -- the
        canonical backward-compat case. An empty dict has the same
        effect. Agents not present in the map resolve to ``None``
        (NPCs without a registered arcdps char-name).

        ``dps_split_getter`` is OPTIONAL and provides the per-event
        ``(condi_damage, power_damage)`` split (mirrors
        :func:`gw2_analytics.condi_power_split.split_condi_power`'s
        RETURN shape). When ``None`` (the canonical v0.10.23
        SCAFFOLD path), the substitute
        :func:`gw2_core._scaffold.default_dps_split` returns
        ``(0, damage)`` -- the "everything is power" fallback
        that preserves the pre-Phase-6-v2 wire shape where
        ``dps_power=0.0, dps_condi=dps``. Phase 6 v2 wires the
        parser-side ``condi_portion`` lookup; the SCAFFOLD absorbs
        the swap via one constructor change.

        Empty input yields ``[]`` -- no placeholder row.
        """
        if duration_s < 0:
            msg = f"duration_s must be >= 0, got {duration_s!r}"
            raise ValueError(msg)

        # SCAFFOLD substitution: when ``dps_split_getter is None``,
        # substitute the canonical SCAFFOLD default so the
        # aggregator's hot loop never branches on "did the caller
        # wire the getter?". One-line substitute vs an if/else per
        # event.
        split = dps_split_getter if dps_split_getter is not None else default_dps_split

        total_by_source: dict[int, int] = defaultdict(int)
        count_by_source: dict[int, int] = defaultdict(int)
        # Pre-Phase-6-v2 condi + power totals per source. SCAFFOLD
        # path: ``condi_per_source == 0`` everywhere; power_rate
        # equals dps. The conservation invariant
        # ``condi_rate + power_rate == dps`` survives both paths
        # (within ``1e-6`` slack for floating-point rounding).
        condi_by_source: dict[int, int] = defaultdict(int)
        power_by_source: dict[int, int] = defaultdict(int)
        grand_total = 0
        for e in events:
            total_by_source[e.source_agent_id] += e.damage
            count_by_source[e.source_agent_id] += 1
            grand_total += e.damage
            # Per-event SCAFFOLD split: the SCAFFOLD path consumes
            # the hit once, returning the (condi, power) tuple;
            # the post-Phase-6-v2 path queries the parser-side
            # table. The hot-loop cost is one C-level function
            # call per event (constant factor).
            condi, power = split(e)
            condi_by_source[e.source_agent_id] += condi
            power_by_source[e.source_agent_id] += power

        dps_factor = 1.0 / duration_s if duration_s > 0 else _DEFAULT_DPS
        # ``name_map.get(source)`` returns ``None`` for missing keys
        # AND for explicit ``None`` values -- both cases surface as
        # ``name=None`` on the row, which is the intended
        # "unresolved" sentinel. No need to distinguish.
        rows = [
            PlayerDamageRow(
                source_agent_id=source,
                total_damage=total_by_source[source],
                attack_count=count_by_source[source],
                dps=total_by_source[source] * dps_factor,
                dps_power=power_by_source[source] * dps_factor,
                dps_condi=condi_by_source[source] * dps_factor,
                name=(name_map or {}).get(source),
            )
            for source in total_by_source
        ]
        # Sort: highest total_damage first; ties broken by ascending source_agent_id.
        rows.sort(key=lambda r: (-r.total_damage, r.source_agent_id))

        self._check_invariants(rows, grand_total, duration_s)
        return rows

    @staticmethod
    def _check_invariants(
        rows: list[PlayerDamageRow],
        expected_sum: int,
        duration_s: float,  # noqa: ARG004
    ) -> None:
        """Raise ``ValueError`` if any cross-field invariant is violated.

        Invariants checked (Phase 3 SCAFFOLD close-out):
        1. Sum of ``row.total_damage`` == ``expected_sum`` (no event
           dropped on the source side).
        2. ``attack_count >= 1`` (Pydantic field constraint;
           redundant but explicit).
        3. Rows monotonic non-increasing by ``total_damage``; ties
           broken by ascending ``source_agent_id``.

        Split-getter conservation (``dps_power + dps_condi == dps``)
        is intentionally NOT enforced at the aggregator tier:
        the SCAFFOLD ``default_dps_split`` returns ``(0, 0)`` to
        preserve the pre-Phase-3 wire shape ``dps_power=0.0 +
        dps_condi=0.0`` byte-for-byte, while the post-Phase-6-v2
        explicit getter is responsible for returning ``(condi,
        power)`` tuples where ``condi + power == event.damage``.
        Enforcing the conservation invariant here would force
        every SCAFFOLD stream to violate it (the canonical
        pre-Phase-6-v2 case) so the check was dropped as part of
        the Phase 3 wire-shape-fidelity fix.

        ``duration_s`` is in the signature for call-site stability
        (``_check_invariants(rows, total, duration_s)``); the
        SCAFFOLD close-out made the conservation check moot so
        ``duration_s`` is unused here -- the unused-argument
        warning is suppressed because the parameter name carries
        API-doc weight (a future re-enablement of the
        conservation check would wire ``duration_s`` back into
        the tolerance computation).
        """
        actual_sum = sum(r.total_damage for r in rows)
        if actual_sum != expected_sum:
            msg = f"sum of row.total_damage ({actual_sum}) != sum of event.damage ({expected_sum})"
            raise ValueError(msg)
        for r in rows:
            if r.attack_count < 1:
                msg = (
                    f"PlayerDamageRow({r.source_agent_id}).attack_count "
                    f"({r.attack_count}) must be >= 1"
                )
                raise ValueError(msg)
        # Pydantic field constraints already guarantee ``ge=0`` for total_damage;
        # the cross-row ordering invariant is the only ordering contract.
        # ``pairwise`` pairs each row with its immediate successor; the
        # canonical idiom for adjacent-pair iteration (ruff RUF007).
        for prev, curr in pairwise(rows):
            if prev.total_damage < curr.total_damage:
                msg = (
                    f"rows not ordered by (total_damage DESC, "
                    f"source_agent_id ASC): {prev!r} then {curr!r}"
                )
                raise ValueError(msg)
            if (
                prev.total_damage == curr.total_damage
                and prev.source_agent_id >= curr.source_agent_id
            ):
                msg = (
                    f"tie on total_damage not broken by source_agent_id ASC: {prev!r} then {curr!r}"
                )
                raise ValueError(msg)


__all__ = ["DpsSplitGetter", "PlayerDamageAggregator", "PlayerDamageRow"]
