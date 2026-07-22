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
Combat readout Boons table is COUNTS + RATES only. ``remove``
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

.. admonition:: Phase 6 v2: strips-received target-side count (live since v0.12.1)
   :class: tip

   Wave 6 added the ``strips_received_in`` integer column +
   the pluggable ``buff_removal_events`` iterable to thread the
   parser-side buff-removal events through the aggregator
   with ZERO wire-shape mutation cost. Legacy (pre-v0.12.x)
   streams pass ``buff_removal_events=()`` (empty iterable)
   which surfaces ``strips_received_in=0``. v0.12.1+ closes
   over the parser's :class:`~gw2_core.BuffRemovalEvent`
   stream directly.

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
  Phase 6 v2 conservation contract, live since v0.12.1).
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
from dataclasses import dataclass, field
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
    # Phase 6 v2 (Wave 6, live since v0.12.1): target-side strip
    # count. The number of :class:`~gw2_core.BuffRemovalEvent` rows
    # where this player is the TARGET (i.e. the player was stripped
    # of a boon). Legacy (pre-v0.12.x) streams return 0 (the
    # canonical "no strip data" wire shape).
    strips_received_in: int = Field(
        default=0,
        ge=0,
        description=(
            "Phase 6 v2 (live since v0.12.1): count of BuffRemovalEvent "
            "rows where this player is the TARGET (strip target). "
            "Legacy (pre-v0.12.x) streams return 0."
        ),
    )
    # Optional player-name denormalisation (mirrors PlayerDamageRow.name
    # convention). ``None`` when the aggregator was called without a
    # ``name_map`` (canonical backward-compat) OR when the agent id has
    # no name in the map (NPC without a registered arcdps char-name).
    name: str | None = None


@dataclass(slots=True)
class _PlayerAccumulator:
    """Mutable accumulator for one player's boon statistics."""

    boons_out: int = 0
    boons_in: int = 0
    strips_received_in: int = 0
    fixed_boons: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    other_boons: dict[str, int] = field(default_factory=lambda: defaultdict(int))


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
        (legacy path) drives
        ``strips_received_in=0`` for every row. v0.12.1+ wires the
        parser-side buff-removal stream directly.

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
        metrics_by_player: dict[int, _PlayerAccumulator] = defaultdict(_PlayerAccumulator)

        # Hoist the name-map fallback outside the hot loop so the
        # per-event path pays the dict-allocation cost exactly once.
        safe_name_map = name_map or {}
        name_map_get = safe_name_map.get
        metrics_get = metrics_by_player.__getitem__
        known_column_get = KNOWN_BOON_ID_TO_COLUMN.get

        for e in events:
            # Pre-filter: count ``kind == "apply"`` only. The
            # ``remove_single`` / ``remove_all`` events are
            # state-maintenance for uptime arithmetic (see
            # ``gw2_analytics.buff_uptime``); the Combat readout
            # Boons counter is apply-counts only.
            if e.kind != "apply":
                continue
            source_id = e.source_agent_id
            target_id = e.target_agent_id
            source_metrics = metrics_get(source_id)
            source_metrics.boons_out += 1
            metrics_get(target_id).boons_in += 1
            # Use a single ``get`` lookup instead of ``in`` + ``[]``
            # to decide whether this skill_id maps to a fixed bucket.
            column = known_column_get(e.skill_id)
            if column is not None:
                source_metrics.fixed_boons[column] += 1
            else:
                # Key ``other_boons_out`` by HUMAN-READABLE name
                # (resolved via ``name_map`` if present, else the
                # ``"Unknown (<id>)"`` sentinel). The skill_id-based
                # sentinel is a stable string for round-trip tests.
                skill_id = e.skill_id
                resolved_name = name_map_get(skill_id)
                key = resolved_name if resolved_name is not None else f"Unknown ({skill_id})"
                source_metrics.other_boons[key] += 1

        # Phase 6 v2 (live since v0.12.1): target-side strip count
        # from the buff-removal stream. Pre-filter at the aggregator
        # boundary so NPC strips + world strips (target_agent_id
        # = 0 OR skill_id = 0) don't leak into the per-player
        # roll-up. Pydantic field constraint ``ge=0`` on
        # ``BuffRemovalEvent.target_agent_id`` admits ``0`` so the
        # legacy behaviour is "drop zero-id targets" (silently).
        # The v0.12.1+ path materialises every event with
        # ``target_agent_id > 0`` into the row.
        for bre in buff_removal_events:
            if bre.target_agent_id > 0:
                metrics_by_player[bre.target_agent_id].strips_received_in += 1

        # Derive the source/target apply totals from the accumulated
        # per-player metrics rather than tracking them inside the hot
        # loop. This saves two integer additions per input event.
        grand_total_out = sum(m.boons_out for m in metrics_by_player.values())
        grand_total_in = sum(m.boons_in for m in metrics_by_player.values())

        rate_factor = 1.0 / duration_s if duration_s > 0 else _DEFAULT_RATE
        # ``name_map.get(agent_id)`` returns ``None`` for missing keys
        # AND for explicit ``None`` values -- both cases surface as
        # ``name=None`` on the row, which is the intended
        # "unresolved" sentinel. No need to distinguish.
        row_names = safe_name_map
        # Phase 6 v2 row-builder patch (close-out, live since v0.12.1): UNITE
        # source + target keys so a pure-target agent (the player RECEIVING
        # a boon but never APPLYING one) surfaces a row. Pre-fix, the loop
        # iterated over ``total_out_by_player`` only, so a target-only
        # agent was silently dropped -- ``sum(row.boons_in) !=
        # grand_total_in`` would fire at the invariants check.
        rows = [
            PlayerBoonsRow(
                agent_id=player,
                boons_out=metrics.boons_out,
                boons_in=metrics.boons_in,
                boons_out_rate=metrics.boons_out * rate_factor,
                boons_in_rate=metrics.boons_in * rate_factor,
                stability_out=metrics.fixed_boons["stability_out"],
                alacrity_out=metrics.fixed_boons["alacrity_out"],
                resistance_out=metrics.fixed_boons["resistance_out"],
                aegis_out=metrics.fixed_boons["aegis_out"],
                superspeed_out=metrics.fixed_boons["superspeed_out"],
                stealth_out=metrics.fixed_boons["stealth_out"],
                other_boons_out=dict(metrics.other_boons),
                strips_received_in=metrics.strips_received_in,
                name=row_names.get(player),
            )
            for player, metrics in metrics_by_player.items()
        ]
        # Sort: highest boons_out first; ties broken by ascending agent_id.
        rows.sort(key=lambda r: (-r.boons_out, r.agent_id))

        return rows


__all__ = [
    "KNOWN_BOON_IDS",
    "KNOWN_BOON_ID_TO_COLUMN",
    "PlayerBoonsAggregator",
    "PlayerBoonsRow",
]
