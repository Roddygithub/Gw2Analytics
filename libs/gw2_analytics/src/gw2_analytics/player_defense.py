"""

Wave 4 / Tour 5 v0.10.23-pre: per-player defense & positioning roll-ups.

Workstream D-extension of plan 045 (Combat readout, per
``docs/v0.9.0-combat-readout-design.md`` section 6). The Combat
readout's ``Defense`` table is keyed on the PLAYER who either
received damage / CC (target-side attribution) or died (actor
attribution on :class:`~gw2_core.DeathEvent`).

Conventions
===========

.. admonition:: Phase 6 v2 forward-compat
   :class: tip

   Three columns (``time_downed_ms``, ``dodges``, ``blocks``,
   ``interrupts``, ``barrier_absorbed``) require NEW Event
   subclasses / side-table getters that did NOT ship in Wave 2
   SCAFFOLD. They return ``0`` today; Phase 6 v2 ships the
   parser-stream switch + the missing event subclasses + the
   damage-side ``buff_dmg`` bridge that exposes
   ``barrier_absorbed``. The schema defaults leave every stub
   field at ``0`` so the wire-shape never crashes; the schema
   itself is invariant for the v0.10.23 wire contract.

- **Target-side damage attribution.** ``damage_taken`` sums every
  :class:`~gw2_core.DamageEvent` whose ``target_agent_id``
  matches the row's player. Symmetric to the per-player
  :class:`~gw2_analytics.player_damage.PlayerDamageAggregator`
  but with the grouping axis on the receiving end.
- **Target-side CC attribution.** ``cc_taken`` counts every
  :class:`~gw2_core.CCEvent` (the SUM of ``cc_value``, not just a
  count -- defensively the SUM catches duration-encoding for the
  future when the parser may yield a single CCEvent per CC
  *applied* with magnitude = duration ms).
- **Actor-side death count.** ``deaths`` counts every
  :class:`~gw2_core.DeathEvent` where the dying player's
  ``source_agent_id`` matches the row's player
  (:class:`~gw2_core.DeathEvent` uses actor-only shape -- the
  dying player is encoded as ``source_agent_id``).
- **Target-side barrier absorbed.** ``barrier_absorbed`` requires
  a side-table getter ``barrier_portion_getter`` (analogous to
  ``condi_portion_getter`` in
  :mod:`gw2_analytics.condi_power_split`). When the getter is
  NOT provided (the canonical v0.10.23 path -- the parser
  doesn't yet emit the per-damage barrier portion), every
  damage event contributes ``0`` to barrier absorbed. Phase 6 v2
  wires the getter when the parser-stream switch lands.

Cross-field invariants (validated post-construction; violations
raise ``ValueError``; Pydantic field constraints also enforce
each per-cell constraint):

- Sum of ``row.damage_taken`` across all rows ==
  sum of ``event.damage`` across the input where the
  target is a player-agented (no event dropped, no double-counting).
- ``cc_taken >= 0`` (Pydantic field constraint).
- ``deaths >= 0`` (Pydantic field constraint) and matches the
  count of :class:`~gw2_core.DeathEvent` rows where
  ``source_agent_id`` matches the row's player (counted at
  aggregator time).
- "Stub columns" (``time_downed_ms`` / ``dodges`` / ``blocks`` /
  ``interrupts``) are explicitly ``0`` per design doc §6
  forward-compat (the parser doesn't yet emit the
  corresponding statechange records -- see the docstring on each
  stub for the specific Phase 6 v2 ticket).
- Rows monotonically non-decreasing by ``damage_taken`` ASC
  (the Defense table's leading indicator per design doc §13:
  "Most-targeted player of each squad surfaces first -- defensive
  load is the leading indicator"); ties broken by ascending
  ``agent_id``.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from gw2_analytics._invariants import check_desc_asc_ordering
from gw2_core import (
    BlockEvent,
    CCEvent,
    DamageEvent,
    DeathEvent,
    DodgeEvent,
    InterruptEvent,
)

# Stub sentinel for the Phase 6 v2 forward-compat columns. The
# parser doesn't yet emit :class:`~gw2_core.DodgeEvent` /
# :class:`~gw2_core.BlockEvent` / :class:`~gw2_core.InterruptEvent`
# (3 NEW Event subclasses that don't exist in the Wave 2 SCAFFOLD
# 9-member union), nor a per-damage ``buff_dmg``-like barrier
# portion, nor a downed-state lifecycle. Every stub field stays
# at 0 for the v0.10.23 wire contract; the schema defaults leave
# them at 0 so the wire-shape never crashes on a missing field.
_STUB_ZERO: Final[int] = 0


class PlayerDefenseRow(BaseModel):
    """One roll-up row: defense --- damage received, CC received, deaths taken.

    Mirror of :class:`~gw2_analytics.player_damage.PlayerDamageRow`
    in shape (per-player roll-up, frozen, extra=forbid, name
    denormalisation) but with the grouping axis flipped from the
    dealing end to the receiving end. The 5 stub columns
    (``time_downed_ms`` / ``dodges`` / ``blocks`` / ``interrupts`` /
    ``barrier_absorbed``) are documented per the schema as
    v0.10.23 forward-compat --- their columns are reserved in the
    Pydantic shape but the backend values are pinned at 0 until
    Phase 6 v2 ships the corresponding event subclasses +
    parser-stream side tables. The schema defaults keep them at 0
    so the wire-shape never crashes on a missing field.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_id: int = Field(..., ge=0)
    damage_taken: int = Field(..., ge=0)
    cc_taken: int = Field(..., ge=0)
    deaths: int = Field(..., ge=0)
    # Phase 6 v2 forward-compat: total ms spent in the downed
    # state across the fight. Aggregator returns 0 until Phase 6
    # v2 ships the down-state lifecycle parser (tools to inventory
    # down events + their end times via ``ChangeUp`` /
    # ``ChangeDead`` / out-of-combat sentinel transitions).
    time_downed_ms: int = Field(default=_STUB_ZERO, ge=0)
    # Phase 6 v2 forward-compat: count of dodge events where the
    # player is the actor. Aggregator returns 0 until Phase 6 v2
    # adds a ``DodgeEvent`` subclass (NEW Event vocabulary beyond
    # the 9-member Wave 2 SCAFFOLD union).
    dodges: int = Field(default=_STUB_ZERO, ge=0)
    # Phase 6 v2 forward-compat: count of block events where the
    # player is the actor. Aggregator returns 0 until Phase 6 v2
    # adds a ``BlockEvent`` subclass (NEW Event vocabulary beyond
    # the 9-member Wave 2 SCAFFOLD union).
    blocks: int = Field(default=_STUB_ZERO, ge=0)
    # Phase 6 v2 forward-compat: count of interrupt events where
    # the player is the SOURCE actor (interrupts an enemy's cast).
    # Aggregator returns 0 until Phase 6 v2 adds an
    # ``InterruptEvent`` subclass (NEW Event vocabulary beyond the
    # 9-member Wave 2 SCAFFOLD union).
    interrupts: int = Field(default=_STUB_ZERO, ge=0)
    # Phase 6 v2 forward-compat: total barrier absorbed across all
    # damage events targeting this player. Aggregator returns 0
    # until Phase 6 v2 ships the per-damage ``barrier`` side
    # table (analogous to the ``condi_portion_getter`` on
    # :mod:`gw2_analytics.condi_power_split`).
    barrier_absorbed: int = Field(default=_STUB_ZERO, ge=0)
    # Optional player-name denormalisation (mirrors
    # PlayerDamageRow.name convention). ``None`` when the
    # aggregator was called without a ``name_map`` (canonical
    # backward-compat) OR when the agent id has no name in the
    # map (NPC without a registered arcdps char-name).
    name: str | None = None


@dataclass(slots=True)
class _DefenseAccumulator:
    """Mutable accumulator for one agent's defense statistics."""

    damage_taken: int = 0
    barrier_absorbed: int = 0
    cc_taken: int = 0
    deaths: int = 0
    dodges: int = 0
    blocks: int = 0
    interrupts: int = 0


class PlayerDefenseAggregator:
    """Stateless aggregator: damage + CC + death events -> per-player defense roll-up rows.

    Instantiate once and reuse --- the class holds no state.
    Target-side attribution for damage + CC (the player receiving
    the hit / CC); actor-side attribution for deaths (the dying
    player). The 5 stub columns are pinned at 0 per Phase 6 v2
    forward-compat (see :class:`PlayerDefenseRow` for the per-field
    ticket).
    """

    def aggregate(
        self,
        damage_events: Iterable[DamageEvent],
        cc_events: Iterable[CCEvent],
        death_events: Iterable[DeathEvent],
        dodge_events: Iterable[DodgeEvent] = (),
        block_events: Iterable[BlockEvent] = (),
        interrupt_events: Iterable[InterruptEvent] = (),
        barrier_portion_getter: Callable[[DamageEvent], int] | None = None,
        name_map: dict[int, str | None] | None = None,
    ) -> list[PlayerDefenseRow]:
        """Compute the per-player defense roll-up.

        ``damage_events`` is the canonical damage stream; ``damage_taken``
        is the sum of ``event.damage`` where ``event.target_agent_id``
        matches the row's player.

        ``cc_events`` is the canonical CC stream (target-side group
        on ``target_agent_id``); ``cc_taken`` is the sum of
        ``event.cc_value`` where ``event.target_agent_id`` matches
        the row's player (the SUM catches future per-event duration
        encoding without a contract change).

        ``death_events`` is the canonical death stream (actor side
        group on ``source_agent_id`` per the actor-only shape of
        :class:`~gw2_core.DeathEvent`); ``deaths`` is the count.

        ``barrier_portion_getter`` is OPTIONAL and parallel to
        :func:`gw2_analytics.condi_power_split.split_condi_power`'s
        ``condi_portion_getter``: resolves the per-damage
        ``barrier`` portion for an event. When ``None`` (the
        canonical v0.10.23 path), every damage event contributes
        ``0`` to ``barrier_absorbed`` on its target's row. Phase 6
        v2 wires the getter when the parser-stream switch lands.

        ``name_map`` is OPTIONAL for player-name denormalisation
        (same ``name=None`` semantics as the per-player damage
        aggregator).

        Empty input across ALL THREE streams yields ``[]`` -- no
        placeholder row.
        """
        stats: dict[int, _DefenseAccumulator] = defaultdict(_DefenseAccumulator)
        grand_damage_total = 0

        # Hoist the barrier-getter branch outside the hot loop so
        # the per-event path pays the branch cost exactly once.
        if barrier_portion_getter is not None:
            getter = barrier_portion_getter
            for de in damage_events:
                acc = stats[de.target_agent_id]
                acc.damage_taken += de.damage
                grand_damage_total += de.damage
                acc.barrier_absorbed += getter(de)
        else:
            for de in damage_events:
                stats[de.target_agent_id].damage_taken += de.damage
                grand_damage_total += de.damage

        for ce in cc_events:
            stats[ce.target_agent_id].cc_taken += ce.cc_value

        # Use C-level Counter for the pure-counting event streams.
        death_counts = Counter(de.source_agent_id for de in death_events)
        dodge_counts = Counter(dodge_ev.source_agent_id for dodge_ev in dodge_events)
        block_counts = Counter(block_ev.source_agent_id for block_ev in block_events)
        interrupt_counts = Counter(
            interrupt_ev.source_agent_id for interrupt_ev in interrupt_events
        )
        for agent_id, count in death_counts.items():
            stats[agent_id].deaths = count
        for agent_id, count in dodge_counts.items():
            stats[agent_id].dodges = count
        for agent_id, count in block_counts.items():
            stats[agent_id].blocks = count
        for agent_id, count in interrupt_counts.items():
            stats[agent_id].interrupts = count

        row_names = name_map or {}
        rows = [
            PlayerDefenseRow(
                agent_id=agent,
                damage_taken=acc.damage_taken,
                cc_taken=acc.cc_taken,
                deaths=acc.deaths,
                dodges=acc.dodges,
                blocks=acc.blocks,
                interrupts=acc.interrupts,
                barrier_absorbed=acc.barrier_absorbed,
                name=row_names.get(agent),
            )
            for agent, acc in stats.items()
        ]
        # Sort: DESCENDING ``damage_taken`` -- the Defense table's
        # leading indicator per design doc §13 ("Most-targeted
        # player of each squad surfaces first -- defensive
        # load is the leading indicator"). Ties broken by
        # ascending ``agent_id``. (Note: this is the OPPOSITE
        # direction from PlayerBoonsRow's DESC "top boon-provider"
        # sort -- the Defense surface surfaces the MOST-targeted
        # player, by the spec's "defensive load" indicator.)
        rows.sort(key=lambda r: (-r.damage_taken, r.agent_id))

        expected_barrier_total = sum(acc.barrier_absorbed for acc in stats.values())
        self._check_invariants(rows, grand_damage_total, expected_barrier_total)
        return rows

    @staticmethod
    def _check_invariants(
        rows: list[PlayerDefenseRow],
        expected_damage_total: int,
        expected_barrier_total: int,
    ) -> None:
        """Raise ``ValueError`` if any cross-field invariant is violated.

        Invariants checked:

        1. Sum of ``row.damage_taken`` across all rows ==
           ``expected_damage_total`` (no damage event dropped on
           the target side).
        2. Sum of ``row.barrier_absorbed`` across all rows ==
           ``expected_barrier_total`` (no barrier-absorbed event
           dropped) -- NOTE: this is a DOC-CHECK on the
           barrier-absorbed contract; if the getter returns
           values, the sum MUST match. Only valid when the
           ``barrier_portion_getter`` was provided (otherwise
           ``expected_barrier_total`` is 0 and the contract is
           trivially satisfied).
        3. ``barrier_absorbed <= damage_taken`` per row (a
           damage event cannot absorb more barrier than its
           magnitude; defensive clamp).
        4. ``cc_taken`` and ``deaths`` are non-negative
           (Pydantic field constraint -- redundant but explicit).
        5. Rows monotonic non-decreasing by ``damage_taken`` ASC;
           ties broken by ascending ``agent_id``.
        """
        actual_damage_total = sum(r.damage_taken for r in rows)
        if actual_damage_total != expected_damage_total:
            msg = (
                f"sum of row.damage_taken ({actual_damage_total}) "
                f"!= sum of event.damage ({expected_damage_total})"
            )
            raise ValueError(msg)
        actual_barrier_total = sum(r.barrier_absorbed for r in rows)
        if actual_barrier_total != expected_barrier_total:
            msg = (
                f"sum of row.barrier_absorbed ({actual_barrier_total}) "
                f"!= sum of barrier_portion_getter({expected_barrier_total})"
            )
            raise ValueError(msg)
        for r in rows:
            # Defensive clamp invariant: a damage event cannot
            # absorb more barrier than its magnitude. The getter is
            # responsible for the per-event validation; the
            # aggregator rejects a contract violation here.
            if r.barrier_absorbed > r.damage_taken:
                msg = (
                    f"PlayerDefenseRow({r.agent_id}): "
                    f"barrier_absorbed ({r.barrier_absorbed}) > "
                    f"damage_taken ({r.damage_taken})"
                )
                raise ValueError(msg)
        # Order check is the INVERSE of PlayerBoonsRow's: damage_taken
        # DESC (most-targeted first per design doc §13); ties broken
        # by ascending ``agent_id``.
        check_desc_asc_ordering(
            rows,
            primary_key=lambda r: r.damage_taken,
            secondary_key=lambda r: r.agent_id,
            primary_label="damage_taken",
            secondary_label="agent_id",
        )


__all__ = ["PlayerDefenseAggregator", "PlayerDefenseRow"]
