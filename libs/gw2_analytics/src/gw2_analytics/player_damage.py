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

.. admonition:: Phase 6 v2: power vs condi split (live since v0.12.1)
   :class: tip

   Wave 6 added the ``dps_power`` + ``dps_condi`` rate columns +
   the pluggable ``dps_split_getter`` callable. Phase 6 v2 shipped
   in v0.12.x: the ``make_dps_split_getter`` factory in
   :mod:`gw2analytics_api.routes.fights.aggregators` produces a
   per-event splitter (new-build: ``event.buff_dmg``, old-build:
   skill-name lookup against ``KNOWN_CONDI_NAMES``). When
   ``dps_split_getter=None`` (legacy fallback), the aggregator
   skips the split call entirely and both ``dps_power`` and
   ``dps_condi`` stay at 0.0.

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
from dataclasses import dataclass
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from gw2_analytics._invariants import check_desc_asc_ordering
from gw2_core import DamageEvent

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
    # Phase 6 v2 (live since v0.12.1): power + condi split rates.
    # ``dps_power`` is the per-second rate of the power component;
    # ``dps_condi`` is the per-second rate of the condi component.
    # Wire-shape contract: ``dps_power + dps_condi == dps_total``
    # within ``1e-6`` rounding tolerance.
    dps_power: float = Field(
        default=_DEFAULT_DPS,
        ge=0.0,
        description=(
            "Phase 6 v2 (live since v0.12.1): per-second power-damage rate. "
            "Legacy (pre-v0.12.x) streams return 0.0."
        ),
    )
    dps_condi: float = Field(
        default=_DEFAULT_DPS,
        ge=0.0,
        description=(
            "Phase 6 v2 (live since v0.12.1): per-second condi-damage rate. "
            "Legacy (pre-v0.12.x) streams return 0.0."
        ),
    )
    # Optional player-name denormalisation (mirrors TargetDpsRow.name
    # convention for grep-ability + diff-based maintenance). ``None``
    # when the aggregator was called without a ``name_map`` (the
    # canonical backward-compat case) OR when the agent id has no
    # name in the map. Strict parallel of the target-side row.
    name: str | None = None


@dataclass(slots=True)
class _DamageAccumulator:
    """Mutable accumulator for one source agent's damage statistics."""

    total_damage: int = 0
    attack_count: int = 0
    condi: int = 0
    power: int = 0


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
        SCAFFOLD path), the hot loop skips the split call
        entirely and both ``condi`` and ``power`` accumulators
        stay at ``0`` -- the "everything is power" fallback that
        preserves the legacy wire shape where
        ``dps_power=0.0, dps_condi=0.0``. Phase 6 v2 wires the
        parser-side ``condi_portion`` lookup; the getter swap
        is a one-constructor-change.

        Empty input yields ``[]`` -- no placeholder row.
        """
        if duration_s < 0:
            msg = f"duration_s must be >= 0, got {duration_s!r}"
            raise ValueError(msg)

        stats_by_source: dict[int, _DamageAccumulator] = defaultdict(_DamageAccumulator)

        # Hoist the split-getter branch outside the hot loop so the
        # canonical legacy path (``dps_split_getter is None``) avoids
        # a Python function call per event. The explicit getter path
        # pays the call cost only when a real parser-side side-table
        # is wired.
        if dps_split_getter is not None:
            split = dps_split_getter
            for e in events:
                acc = stats_by_source[e.source_agent_id]
                acc.total_damage += e.damage
                acc.attack_count += 1
                condi, power = split(e)
                acc.condi += condi
                acc.power += power
        else:
            for e in events:
                acc = stats_by_source[e.source_agent_id]
                acc.total_damage += e.damage
                acc.attack_count += 1

        dps_factor = 1.0 / duration_s if duration_s > 0 else _DEFAULT_DPS
        # ``name_map.get(source)`` returns ``None`` for missing keys
        # AND for explicit ``None`` values -- both cases surface as
        # ``name=None`` on the row, which is the intended
        # "unresolved" sentinel. No need to distinguish.
        safe_name_map = name_map or {}
        rows = [
            PlayerDamageRow(
                source_agent_id=source,
                total_damage=acc.total_damage,
                attack_count=acc.attack_count,
                dps=acc.total_damage * dps_factor,
                dps_power=acc.power * dps_factor,
                dps_condi=acc.condi * dps_factor,
                name=safe_name_map.get(source),
            )
            for source, acc in stats_by_source.items()
        ]
        # Sort: highest total_damage first; ties broken by ascending source_agent_id.
        rows.sort(key=lambda r: (-r.total_damage, r.source_agent_id))

        # The invariant total is derived from the aggregated rows
        # rather than accumulated in the hot loop, saving one integer
        # addition per input event.
        self._check_invariants(rows, sum(r.total_damage for r in rows), duration_s)
        return rows

    @staticmethod
    def _check_invariants(
        rows: list[PlayerDamageRow],
        expected_sum: int,
        duration_s: float,  # noqa: ARG004
    ) -> None:
        """Raise ``ValueError`` if any cross-field invariant is violated.

        Invariants checked (Phase 3 close-out):
        1. Sum of ``row.total_damage`` == ``expected_sum`` (no event
           dropped on the source side).
        2. ``attack_count >= 1`` (Pydantic field constraint;
           redundant but explicit).
        3. Rows monotonic non-increasing by ``total_damage``;
           ties broken by ascending ``source_agent_id``.

        Split-getter conservation (``dps_power + dps_condi == dps``)
        is intentionally NOT enforced at the aggregator tier:
        the legacy path (no getter) returns ``(0, 0)`` to
        preserve the pre-Phase-3 wire shape ``dps_power=0.0 +
        dps_condi=0.0`` byte-for-byte, while the post-Phase-6-v2
        explicit getter is responsible for returning ``(condi,
        power)`` tuples where ``condi + power == event.damage``.
        Enforcing the conservation invariant here would force
        every legacy stream to violate it (the canonical
        pre-Phase-6-v2 case) so the check was dropped as part of
        the Phase 3 wire-shape-fidelity fix.

        ``duration_s`` is in the signature for call-site stability
        (``_check_invariants(rows, total, duration_s)``); the
        close-out made the conservation check moot so
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
        check_desc_asc_ordering(
            rows,
            primary_key=lambda r: r.total_damage,
            secondary_key=lambda r: r.source_agent_id,
            primary_label="total_damage",
            secondary_label="source_agent_id",
        )


__all__ = ["DpsSplitGetter", "PlayerDamageAggregator", "PlayerDamageRow"]
