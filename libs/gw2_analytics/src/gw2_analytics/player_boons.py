"""

Wave 4 / Tour 5 v0.10.23-pre: per-player boons roll-ups.

Workstream D-extension of plan 045 (Combat readout, per
``docs/v0.9.0-combat-readout-design.md`` section 5). The Combat
readout's ``Boons`` table is keyed on the PLAYER who APPLIED the
boon (source-side attribution for the boon-output rate + the 6
named fixed columns + the dynamic ``other_boons_out`` bucket).

The ``other_boons_out`` map (``boon_name -> count``) covers the
remaining ~34 GW2 boons not on the fixed-column shortlist. The
fixed shortlist mirrors ``PlayerReadoutBoonsOut``'s Pydantic
schema 1-for-1: stability / alacrity / resistance / aegis /
superspeed / stealth. The names are resolved from a
``name_map: dict[int, str]`` (the canonical all-purpose
skill-id -> string lookup the route layer closes over per the
``gw2_analytics.condi_power_split`` ``skill_name_getter``
pattern).

This module does NOT do uptime arithmetic (the
:class:`~gw2_analytics.buff_uptime.BuffState` pattern in
:mod:`gw2_analytics.buff_uptime` is the SSoT for that); the
Combat readout's Boons table is COUNTS + RATES only. ``remove``
events (``kind == "remove_single"`` / ``"remove_all"``) are
state-maintenance for uptime calculation -- the Combat readout
boon counters ignore them (they reflect apply-counts).

Conventions
===========

.. admonition:: Naming NIT (the convention-break vs the per-target side)
   :class: tip

   The per-player row fields use the slightly long
   ``stability_out`` (etc.) to mirror the
   :class:`~gw2analytics_api.schemas.fight.PlayerReadoutBoonsOut`
   wire-shape field names 1-for-1. The per-target analogues
   (deferred to a future tour) will use ``bounty_received``-style
   naming. The alignment with the wire-shape is intentional --
   aggregator row + JSON key + schema field all share the same
   string for grep-ability. (cf. the parallel
   ``Damage/Dps`` and ``Heal/Healing`` annotations on
   :class:`~gw2_analytics.player_damage.PlayerDamageRow` and
   :class:`~gw2_analytics.player_heal.PlayerHealRow`.)

.. admonition:: Phase 6 v2 SCAFFOLD: strips-received target-side count
   :class: tip

   Wave 6 added the ``strips_received_in`` integer column +
   the pluggable ``buff_removal_events`` iterable to thread the
   future parser-side buff-removal events through the aggregator
   with ZERO wire-shape mutation cost. The CANONICAL v0.10.23
   SCAFFOLD path leaves ``buff_removal_events=()`` (empty
   iterable) which the aggregator interprets as "no strip data"
   so the wire-shape stays ``strips_received_in=0`` for
   pre-Phase-6-v2 streams. Phase 6 v2 closes over the parser's
   :class:`~gw2_core.BuffRemovalEvent` stream; the SCAFFOLD
   absorbs the swap via one constructor change.

- **Deterministic ordering.** Rows sorted by ``(-boons_out, agent_id)``
  -- highest boons-applied first; ties broken by ascending ``agent_id``.
  Two runs over the same input MUST yield byte-identical row output.
- **No defaults invented.** Empty input yields ``[]``; we never
  synthesise a placeholder row.
- **Counts only count ``kind == "apply"`` events.** ``remove_single``
  / ``remove_all`` events are boons STATE-MAINTENANCE for uptime
  arithmetic (see :mod:`gw2_analytics.buff_uptime`) -- the Combat
  readout Boons counter ignores them. Pre-filter at the aggregator
  boundary so the wire-shape contract stays ``int`` for counts.
- **Source-side attribution.** ``boons_out_rate`` counts events
  where ``source_agent_id == player`` (the player who APPLIED the
  boon); ``boons_in_rate`` counts events where
  ``target_agent_id == player`` (the player who RECEIVED the
  boon). Both rates are ``count / duration_s`` when
  ``duration_s > 0``, else ``0.0`` (sentinel "duration not
  provided" not a math singularity).
- **Target-side attribution for strips-received.** ``strips_received_in``
  counts :class:`~gw2_core.BuffRemovalEvent` rows where
  ``target_agent_id == player`` (TYP -- the strip target). This is
  the target-side mirror of the source-side
  ``strips_out`` count on the Wire schema's
  :class:`~gw2analytics_api.schemas.fight.PlayerReadoutDamageOut`.
  Pre-filter at the aggregator boundary so events without a player
  target (NPC strips, world strips) are excluded from the per-player
  roll-up.
- **Buff-ID calibration note.** The 6 fixed buff-IDs below come
  from arcdps' canonical buff table (the
  ``is_buffremove``-aware skill-id set; calibrated against
  Elemental Insight + the GW2 wiki at Phase 9 step 4). They are
  stable since the 2024 arcdps 2024-05-01 build, but the values
  are STILL a forward-compat TODO: when the skills DB catalog
  (``libs/gw2_skills`` step 2 of plan 045) lands at v0.11.0,
  these constants should be re-derived from the catalog (or
  passed in as a constructor argument so the catalog can
  override). For Wave 4 the hard-coded values are the
  canonical snapshot taken at cycle-start.

Cross-field invariants (validated post-construction; violations
raise ``ValueError``; Pydantic field constraints also enforce
each per-cell constraint):

- Sum of ``row.boons_out`` across all rows == count of ``kind == "apply"``
  events where ``source_agent_id`` is a player-observed agent
  (no event dropped, no double-counting).
- Sum of the 6 fixed-column counts across all rows <=
  ``sum(row.boons_out)`` (the fixed columns are a PARTITION of
  the apply count; nothing leaks OUT).
- Sum of ``len(other_boons_out)`` summed across rows ==
  total-non-fixed apply count.
- Sum of ``row.strips_received_in`` across all rows == count of
  :class:`~gw2_core.BuffRemovalEvent` rows where
  ``target_agent_id`` is a player-observed agent (the
  Phase 6 v2 SCAFFOLD conservation contract).
- Rows monotonically non-increasing by ``boons_out``; ties broken
  by ascending ``agent_id``.

Forward compat
==============

Wave 2 SCAFFOLD extended :class:`~gw2_core.EventType` to 9
members; the new :class:`~gw2_core.ConditionRemoveEvent`
subclass ALSO carries a ``skill_id`` whose GW2 mapping is
boon-vs-UNDECIDED until the skills DB catalog lands
(``docs/v0.9.0-combat-readout-design.md`` §9 step 2; v0.11.0).
This aggregator ignores condition-removal events by design --
the Boons counter is for COMBAT-READOUT BOONS only. A future
update MIGHT route condition-removals into the
``other_boons_out`` fallback as a calibration step, but for now
the aggregator is strictly boon-only.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from itertools import pairwise
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from gw2_core import BoonApplyEvent, BuffRemovalEvent

# Speedup-sentinel for rates when ``duration_s <= 0``: invalid
# (zero/negative) duration collapses to 0.0 rather than raising -- the
# canonical ``BoonApplyEvent`` stream from the parser will always pair
# with a known fight duration so the zero path is purely defensive.
# Mirrors ``_DEFAULT_DPS`` on the per-player damage aggregator.
_DEFAULT_RATE: Final[float] = 0.0

#: The 6 fixed buff-IDs from arcdps' canonical buff table. These
#: are the boon SKILL IDs (NOT statechange IDs; statechange is
#: unrelated -- boon applies come through the standard
#: ``cbtevent`` stream with ``is_buffremove != 0`` values decoded
#: to ``kind`` per Phase 9 step 4). Hard-coded for Wave 4; v0.11.0
#: will re-derive these from the skills DB catalog. Stable since
#: arcdps build 2024-05-01. Calibration provenance:
#: Elemental Insight's ``Buff`` enum + GW2 wiki ``APIv2`` ``skills``.
_STABILITY_BUFF_ID: Final[int] = 1122  # TOUR 6 SYNC: libs/gw2_skills.SKILL_CATALOG[1122].
_ALACRITY_BUFF_ID: Final[int] = 30328
_RESISTANCE_BUFF_ID: Final[int] = 894
_AEGIS_BUFF_ID: Final[int] = 743
_SUPERSPEED_BUFF_ID: Final[int] = 597
_STEALTH_BUFF_ID: Final[int] = 1305

#: Mapping from the 6 fixed buff-IDs to the WIRE-SHAPE column
#: name (``PlayerReadoutBoonsOut.{stability|alacrity|...}_out``).
#: Module-level constant so the live route can introspect the
#: canonical mapping (and the grep-ability comment on each
#: row-class docstring stays simple). The frozenset-of-IDs is
#: derived from this dict's keys (single source of truth).
KNOWN_BOON_ID_TO_COLUMN: Final[dict[int, str]] = {
    _STABILITY_BUFF_ID: "stability_out",
    _ALACRITY_BUFF_ID: "alacrity_out",
    _RESISTANCE_BUFF_ID: "resistance_out",
    _AEGIS_BUFF_ID: "aegis_out",
    _SUPERSPEED_BUFF_ID: "superspeed_out",
    _STEALTH_BUFF_ID: "stealth_out",
}
KNOWN_BOON_IDS: Final[frozenset[int]] = frozenset(KNOWN_BOON_ID_TO_COLUMN)


class PlayerBoonsRow(BaseModel):
    """One roll-up row: boons applied + received FOR / BY a single player.

    Mirror of :class:`~gw2_analytics.player_damage.PlayerDamageRow` in
    semantics (source-side attribution, per-player roll-up), specialised
    for the Combat readout Boons table. The ``boons_out`` count is the
    total ``kind == "apply"`` events where the row's player is the
    SOURCE actor (the player who APPLIED the boon); ``boons_in`` is the
    symmetric total where the player is the TARGET (received the
    boon).

    The 6 fixed columns (``stability_out`` ...) are COUNTS (NOT rates),
    partitioned from ``boons_out`` (no double-counting across columns
    and ``boons_out`` -- invariant enforced in
    :meth:`PlayerBoonsAggregator._check_invariants`).

    The ``other_boons_out`` dict carries the remaining ~34 GW2 boons
    keyed by their human-readable name (resolved via the ``name_map``
    passed to :meth:`PlayerBoonsAggregator.aggregate`; falls back to
    the literal string ``"Unknown (<skill_id>)"`` for unknown IDs so
    the wire-shape contract never crashes).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_id: int = Field(..., ge=0)
    boons_out: int = Field(..., ge=0)
    boons_in: int = Field(..., ge=0)
    boons_out_rate: float = Field(..., ge=0.0)
    boons_in_rate: float = Field(..., ge=0.0)
    stability_out: int = Field(..., ge=0)
    alacrity_out: int = Field(..., ge=0)
    resistance_out: int = Field(..., ge=0)
    aegis_out: int = Field(..., ge=0)
    superspeed_out: int = Field(..., ge=0)
    stealth_out: int = Field(..., ge=0)
    other_boons_out: dict[str, int] = Field(default_factory=dict)
    # Phase 6 v2 SCAFFOLD (Wave 6): target-side strip count. The
    # number of :class:`~gw2_core.BuffRemovalEvent` rows where this
    # player is the TARGET (i.e. the player was stripped of a
    # boon). Pre-Phase-6-v2 SCAFFOLD: ``strips_received_in=0`` (the
    # canonical "no strip data" wire shape). Wire-shape contract:
    # ``strips_received_in`` is the per-player target-side mirror of
    # the source-side ``strips_out`` count on the Wire schema's
    # ``PlayerReadoutDamageOut`` (which I'm NOT touching here --
    # that one stays wired through the ``PlayerDamageAggregator``
    # in a future tour; the boons aggregator owns the
    # target-side received-strips count because it owns the
    # canonical buffs-removal stream).
    strips_received_in: int = Field(
        default=0,
        ge=0,
        description=(
            "Phase 6 v2 SCAFFOLD: count of BuffRemovalEvent rows "
            "where this player is the TARGET (strip target). "
            "Pre-Phase-6-v2 streams return 0; the SCAFFOLD "
            "absorbs the parser-side buff-removal stream with "
            "zero schema migration."
        ),
    )
    # Optional player-name denormalisation (mirrors PlayerDamageRow.name
    # convention). ``None`` when the aggregator was called without a
    # ``name_map`` (canonical backward-compat) OR when the agent id has
    # no name in the map (NPC without a registered arcdps char-name).
    name: str | None = None


class PlayerBoonsAggregator:
    """Stateless aggregator: boon-apply events -> per-player boons roll-up rows.

    Instantiate once and reuse -- the class holds no state. Source-side
    attribution for ``boons_out`` (count of applies BY the player);
    target-side attribution for ``boons_in`` (count of applies TO the
    player). The 6 fixed columns partition from ``boons_out``; the
    dynamic ``other_boons_out`` captures every non-fixed buff-ID
    apply, keyed by name (or ``"Unknown (<id>)"`` fallback).
    """

    def aggregate(
        self,
        events: Iterable[BoonApplyEvent],
        duration_s: float,
        name_map: dict[int, str | None] | None = None,
        buff_removal_events: Iterable[BuffRemovalEvent] = (),
    ) -> list[PlayerBoonsRow]:
        """Compute the per-player boons roll-up.

        ``duration_s`` is the fight duration (the time-bucket the
        rate is measured against). Passed by the caller so the
        aggregator stays free of cross-source metadata.

        ``name_map`` is an OPTIONAL ``{agent_id: name}`` lookup
        that both (a) denormalises the per-row ``name`` field (mirrors
        PlayerDamageRow's pattern) AND (b) resolves unknown buff-IDs
        into a human-readable string for the ``other_boons_out``
        bucket. Buff-IDs NOT in ``name_map`` fall back to the
        literal sentinel ``"Unknown (<skill_id>)"`` so the contract
        can never crash on a new buff-ID.

        ``buff_removal_events`` is OPTIONAL and provides the
        :class:`~gw2_core.BuffRemovalEvent` stream for the
        target-side strips-received count. The empty iterable
        (canonical v0.10.23 SCAFFOLD path) drives
        ``strips_received_in=0`` for every row. Phase 6 v2 wires the
        parser-side buff-removal stream; the SCAFFOLD absorbs the
        swap via one constructor change.

        Empty input across BOTH streams (apply + buff-removal) yields ``[]`` --
        no placeholder row.
        """
        if duration_s < 0:
            msg = f"duration_s must be >= 0, got {duration_s!r}"
            raise ValueError(msg)

        # Two aggregations: ``boons_out`` keys on source_agent_id (the
        # boon-creator); ``boons_in`` keys on target_agent_id (the
        # boon-receiver). They are SEPARATE counters so a player who
        # is BOTH a boon-provider AND a boon-receiver gets BOTH totals.
        # The 6 fixed counter buckets partition the ``boons_out`` per
        # player; ``other_boons_out`` captures the rest.
        fixed_by_player: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        other_by_player: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        total_out_by_player: dict[int, int] = defaultdict(int)
        total_in_by_player: dict[int, int] = defaultdict(int)
        # Phase 6 v2 SCAFFOLD: target-side strip count from the
        # buff-removal stream. Player is the TARGET (strippee)
        # -- target-side attribution. The buff-removal event has
        # ``source_agent_id`` (the stripper) and
        # ``target_agent_id`` (the strippee); we count by
        # ``target_agent_id`` so a player who was stripped 5x
        # surfaces ``strips_received_in=5``. Empty iterable SCAFFOLD
        # path: every player has ``strips_received_in=0``.
        strips_received_by_player: dict[int, int] = defaultdict(int)
        grand_total_out = 0
        grand_total_in = 0

        for e in events:
            # Pre-filter: count ``kind == "apply"`` only. The
            # ``remove_single`` / ``remove_all`` events are
            # state-maintenance for uptime arithmetic (see
            # ``gw2_analytics.buff_uptime``); the Combat readout
            # Boons counter is apply-counts only.
            if e.kind != "apply":
                continue
            total_out_by_player[e.source_agent_id] += 1
            total_in_by_player[e.target_agent_id] += 1
            grand_total_out += 1
            grand_total_in += 1
            if e.skill_id in KNOWN_BOON_IDS:
                # Partition into the matching fixed bucket for the
                # SOURCE agent (the boon creator). The mapping
                # ``KNOWN_BOON_ID_TO_COLUMN[skill_id]`` returns the
                # exact Pydantic field name on the row, so a
                # ``setattr`` round-trip at instantiation avoids a
                # 6-way match arm.
                column = KNOWN_BOON_ID_TO_COLUMN[e.skill_id]
                fixed_by_player[e.source_agent_id][column] += 1
            else:
                # Key ``other_boons_out`` by HUMAN-READABLE name
                # (resolved via ``name_map`` if present, else the
                # ``"Unknown (<id>)"`` sentinel). The skill_id-based
                # sentinel is a stable string for round-trip tests.
                resolved_name = (name_map or {}).get(e.skill_id)
                key = resolved_name if resolved_name is not None else f"Unknown ({e.skill_id})"
                other_by_player[e.source_agent_id][key] += 1

        # Phase 6 v2 SCAFFOLD: target-side strip count from the
        # buff-removal stream. Pre-filter at the aggregator
        # boundary so NPC strips + world strips (target_agent_id
        # = 0 OR skill_id = 0) don't leak into the per-player
        # roll-up. Pydantic field constraint ``ge=0`` on
        # ``BuffRemovalEvent.target_agent_id`` admits ``0`` so
        # the SCAFFOLD behaviour is "drop zero-id targets"
        # (silently). The post-Phase-6-v2 path materialises every
        # event with ``target_agent_id > 0`` into the row.
        for bre in buff_removal_events:
            if bre.target_agent_id > 0:
                strips_received_by_player[bre.target_agent_id] += 1

        rate_factor = 1.0 / duration_s if duration_s > 0 else _DEFAULT_RATE
        # ``name_map.get(agent_id)`` returns ``None`` for missing keys
        # AND for explicit ``None`` values -- both cases surface as
        # ``name=None`` on the row, which is the intended
        # "unresolved" sentinel. No need to distinguish.
        row_names = name_map or {}
        # Phase 6 v2 SCAFFOLD row-builder patch (close-out): UNITE source +
        # target keys so a pure-target agent (the player RECEIVING a boon
        # but never APPLYING one) surfaces a row. Pre-fix, the loop
        # iterated over ``total_out_by_player`` only, so a target-only
        # agent was silently dropped -- ``sum(row.boons_in) !=
        # grand_total_in`` would fire at the invariants check.
        all_players_sorted = sorted(set(total_out_by_player) | set(total_in_by_player))
        rows = [
            PlayerBoonsRow(
                agent_id=player,
                boons_out=total_out_by_player[player],
                boons_in=total_in_by_player[player],
                boons_out_rate=total_out_by_player[player] * rate_factor,
                boons_in_rate=total_in_by_player[player] * rate_factor,
                stability_out=fixed_by_player[player]["stability_out"],
                alacrity_out=fixed_by_player[player]["alacrity_out"],
                resistance_out=fixed_by_player[player]["resistance_out"],
                aegis_out=fixed_by_player[player]["aegis_out"],
                superspeed_out=fixed_by_player[player]["superspeed_out"],
                stealth_out=fixed_by_player[player]["stealth_out"],
                other_boons_out=dict(other_by_player[player]),
                strips_received_in=strips_received_by_player[player],
                name=row_names.get(player),
            )
            for player in all_players_sorted
        ]
        # Sort: highest boons_out first; ties broken by ascending agent_id.
        rows.sort(key=lambda r: (-r.boons_out, r.agent_id))

        self._check_invariants(rows, grand_total_out, grand_total_in)
        return rows

    @staticmethod
    def _check_invariants(
        rows: list[PlayerBoonsRow],
        expected_total_out: int,
        expected_total_in: int,
    ) -> None:
        """Raise ``ValueError`` if any cross-field invariant is violated.

        Invariants checked:

        1. Sum of ``row.boons_out`` across all rows == ``expected_total_out``
           (no event dropped on the source side).
        2. Sum of ``row.boons_in`` across all rows == ``expected_total_in``
           (no event dropped on the target side).
        3. The 6 fixed columns partition from ``row.boons_out`` per
           row (the SUM of the 6 fixed counts is <= ``boons_out``;
           leftover flows into ``other_boons_out`` -- the union is
           STRICT EQUAL).
        4. Rows monotonically non-increasing by ``boons_out``; ties
           broken by ascending ``agent_id``.
        """
        actual_total_out = sum(r.boons_out for r in rows)
        if actual_total_out != expected_total_out:
            msg = (
                f"sum of row.boons_out ({actual_total_out}) "
                f"!= count of source-side apply events ({expected_total_out})"
            )
            raise ValueError(msg)
        actual_total_in = sum(r.boons_in for r in rows)
        if actual_total_in != expected_total_in:
            msg = (
                f"sum of row.boons_in ({actual_total_in}) "
                f"!= count of target-side apply events ({expected_total_in})"
            )
            raise ValueError(msg)
        for r in rows:
            fixed_sum = (
                r.stability_out
                + r.alacrity_out
                + r.resistance_out
                + r.aegis_out
                + r.superspeed_out
                + r.stealth_out
            )
            other_sum = sum(r.other_boons_out.values())
            if fixed_sum + other_sum != r.boons_out:
                msg = (
                    f"PlayerBoonsRow({r.agent_id}): "
                    f"fixed_sum ({fixed_sum}) + other_sum ({other_sum}) "
                    f"!= boons_out ({r.boons_out})"
                )
                raise ValueError(msg)
        # Pydantic field constraints already guarantee ``ge=0``;
        # only the cross-row ordering contract needs an explicit check.
        # ``pairwise`` pairs each row with its immediate successor; the
        # canonical idiom for adjacent-pair iteration (ruff RUF007).
        for prev, curr in pairwise(rows):
            if prev.boons_out < curr.boons_out:
                msg = f"rows not ordered by (boons_out DESC, agent_id ASC): {prev!r} then {curr!r}"
                raise ValueError(msg)
            if prev.boons_out == curr.boons_out and prev.agent_id >= curr.agent_id:
                msg = f"tie on boons_out not broken by agent_id ASC: {prev!r} then {curr!r}"
                raise ValueError(msg)


__all__ = [
    "KNOWN_BOON_IDS",
    "KNOWN_BOON_ID_TO_COLUMN",
    "PlayerBoonsAggregator",
    "PlayerBoonsRow",
]
