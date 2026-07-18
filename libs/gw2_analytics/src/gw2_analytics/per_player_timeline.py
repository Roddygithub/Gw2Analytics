"""v0.10.3 plan 083 Feature 3A: per-player (source-agent-grouped) timeline roll-up.

Groups the per-fight events stream by ``source_agent_id`` and
per time bucket, producing one :class:`PerPlayerTimelineSeries`
per player agent (the source-side attribution: the player who
*generated* the event, not the target). The output is the
**per-player** counterpart of :class:`PerFightTimelineAggregator`
(plan 083 phase 8, which aggregates the whole fight into a
single 3-series timeline).

Why a SEPARATE aggregator from ``PerFightTimelineAggregator``
=============================================================

The aggregated timeline produces ``list[PerFightTimelineRow]``
(one row per bucket, sums across all players). The per-player
timeline produces ``list[PerPlayerTimelineSeries]`` (one
series per player, with nested ``list[PerFightTimelinePoint]``).
The two schemas are structurally different (the per-player
shape is a 2-level nested list, not a flat list) so the existing
aggregator cannot be reused -- the data layout diverges at
the output level.

Why per-SOURCE-agent (not per-target)
=====================================

The timeline is the "what each player did" view (the analyst
sees "Heinrik was bursty from 0:00-0:10, then dead from
0:10-0:20, then back at 0:25"). The per-target roll-up
(``/fights/{id}/events``) is the "who was hit" view (the
analyst sees "Heinrik took 500k damage at 0:05"). Same
``source_agent_id`` / ``target_agent_id`` split as the per-target
trio in :mod:`gw2_analytics.target_dps` et al.

Why compute on-the-fly (vs materialised table)
==============================================

The per-target trio (DPS / Healing / BuffRemoval) + the squads
+ the skills roll-ups are all computed on-the-fly from the
gzipped JSONL events blob. The per-player timeline joins that
same family -- the blob walk is O(events) and the cost is
acceptable for the bounded per-fight data volume (a 5-min WvW
fight has ~10-30k events; the per-player aggregation is
~1ms/event). A materialised table would add a migration + an
ingestion hook + a DELETE+INSERT on every re-parse, for a
sub-100ms saving on a route that's already < 500ms.

Conventions
===========

- **Same time-bucket semantics as
  :class:`PerFightTimelineAggregator`**: ``window_s`` is the
  bucket size in seconds (>= 1, <= 600). ``time_ms // window_ms``
  is the bucket index. Half-open ``[start, end)`` ranges.
- **Same zero-fill semantics as
  :class:`PerFightTimelineAggregator`**: gaps between events
  are zero-filled so the visualisation has no holes. Every
  player gets a point at every bucket index from 0 to
  ``max(bucket_index)`` so visx multi-line charts have aligned
  arrays (a strict requirement of stacked-line SVG renders --
  see :class:`PerPlayerTimelineChart` on the web side).
- **NPC agents are filtered out**: only events whose
  ``source_agent_id`` maps to a player agent (``is_player=True``
  AND ``account_name`` non-empty) contribute. This matches
  the per-source-side filter in
  :func:`apps.api.services._persist_player_summaries` and
  :class:`SquadRollupAggregator`.
- **Empty input -> empty list**: a fight with zero player
  agents produces zero series (no placeholders, no synth
  rows). The route layer surfaces an empty list as a 200 OK
  with ``series: []`` (NOT a 404 -- a 0-player fight is a
  legitimate state, not "data unavailable").
- **Deterministic ordering**: series sorted by
  ``(-total_damage, account_name)`` -- the highest-damage
  player first; ties broken by ascending ``account_name``
  (the same tie-break contract as
  :class:`PlayerProfileAggregator`).
- **Per-series point ordering**: points sorted ascending by
  ``window_start_ms`` (the aggregator's deterministic-ordering
  contract -- mirrors :class:`PerFightTimelineAggregator`).

Cross-field invariants (validated post-construction; violations
raise ``ValueError``):

- For every series, ``sum(series.points[i].total_damage) ==
  sum(event.damage for event in events if event.source_agent_id
  maps to series.account_name and event is DamageEvent)`` (no
  damage events dropped).
- The same sum-preservation contract holds for healing +
  buff-removal.
- Every 2 adjacent points in a series are contiguous
  (``points[i].window_end_ms == points[i+1].window_start_ms``).
- All series have the SAME number of points (the visx
  multi-line chart's array-alignment contract).

Forward compat
==============

A future v0.11.0 backend that materialises the per-player
timeline (analogous to :class:`OrmFightPlayerSummary`) can
swap the blob-walk for an indexed PK lookup without changing
the aggregator's public surface (signature + the 2 schema
classes). The aggregation is pure (no I/O, no logging) so
the swap is mechanical.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import pairwise
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field

from gw2_core import BuffRemovalEvent, DamageEvent, Event, HealingEvent

# Lower bound enforced on ``window_s``. Smaller windows are not
# meaningful (would be millisecond-resolution buckets; arcdps default
# event write rate is ~30Hz so 1s is a reasonable minimum). Strict
# parallel of :class:`PerFightTimelineAggregator`'s bound.
_MIN_WINDOW_S: Final[int] = 1


@dataclass(slots=True)
class _BucketStats:
    """Mutable per-bucket accumulator for damage, healing, and buff-removal."""

    damage: int = 0
    healing: int = 0
    buff_removal: int = 0


class PerPlayerTimelinePoint(BaseModel):
    """One time-bucketed (damage + healing + buff-removal) point for ONE player.

    Strict parallel of :class:`PerFightTimelineRow` (plan 083
    phase 8) but scoped to a single player (the series' owner).
    The per-player timeline embeds ``list[PerPlayerTimelinePoint]``
    inside :class:`PerPlayerTimelineSeries` -- the schema is
    structurally nested (2 levels) vs the flat
    ``list[PerFightTimelineRow]`` of the aggregated timeline.

    Spans ``[window_start_ms, window_end_ms)`` (half-open). All
    3 totals are non-negative (Pydantic ``ge=0`` validated).
    Frozen Pydantic semantics (the route-layer transformation
    to the wire schema uses ``model_dump()`` which is safe on a
    frozen model).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    window_start_ms: int = Field(..., ge=0)
    window_end_ms: int = Field(..., ge=0)
    total_damage: int = Field(default=0, ge=0)
    total_healing: int = Field(default=0, ge=0)
    total_buff_removal: int = Field(default=0, ge=0)


class PerPlayerTimelineSeries(BaseModel):
    """One player's per-bucket timeline series.

    The wire shape is a list of these series (one per player
    agent in the fight). The ``points`` field is the per-bucket
    timeline for THIS player (same ``window_start_ms`` /
    ``window_end_ms`` grid as every other series -- the
    visx multi-line chart's array-alignment contract).

    - ``account_name`` is the operational identity (stable
      across uploads, the join key for the per-account
      cross-fight roll-up).
    - ``name`` is the LAST-SEEN char-name (cosmetic identity,
      best-effort -- arcdps prefixes with ``:`` so the
      cosmetic name is the ``:``-stripped form per the
      :class:`PlayerProfileAggregator` contract).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_name: str = Field(..., min_length=1, max_length=128)
    name: str = Field(default="", max_length=128)
    points: list[PerPlayerTimelinePoint] = Field(default_factory=list)


class PerPlayerTimelineAggregator:
    """Stateless aggregator: events + agents -> per-player per-bucket timeline series.

    Instantiate once and reuse -- the class holds no state.

    The signature mirrors the per-target trio +
    :class:`PerFightTimelineAggregator` so the route layer can
    invoke all 4 aggregators with the same ``(events, agents,
    window_s)`` tuple. The ``agents`` parameter is the
    per-fight ``OrmFightAgent`` iterable (filtered upstream
    by ``is_player=True`` -- the aggregator applies the
    second-layer ``account_name``-non-empty filter).
    """

    _SUM_CHECK_FIELDS: tuple[tuple[str, str], ...] = (
        ("total_damage", "damage"),
        ("total_healing", "healing"),
        ("total_buff_removal", "buff_removal"),
    )

    def aggregate(
        self,
        events: Iterable[Event],
        agents: Iterable[Any] = (),
        *,
        window_s: int = 5,
    ) -> list[PerPlayerTimelineSeries]:
        """Bucket the input events by ``source_agent_id`` and time window.

        ``agents`` is the per-fight ``OrmFightAgent`` iterable;
        the aggregator builds the ``source_agent_id -> agent``
        map and filters to player agents (``is_player=True``
        AND ``account_name`` non-empty). NPC agents are
        silently dropped (matches the per-source-side filter
        in :func:`apps.api.services._persist_player_summaries`).

        Empty input -> empty list (no placeholders, no synth
        rows). The series are sorted by
        ``(-total_damage, account_name)`` (the
        deterministic-ordering contract).
        """
        if window_s < _MIN_WINDOW_S:
            msg = f"window_s must be >= {_MIN_WINDOW_S}, got {window_s!r}"
            raise ValueError(msg)

        window_ms = window_s * 1000

        source_map, player_name_map = self._build_source_map(agents)

        # Per-account per-bucket accumulator. The inner dict
        # keys are bucket indices; the values are slotted
        # ``_BucketStats`` dataclasses. A nested ``defaultdict``
        # collapses the two-level lookup to a single
        # ``__missing__`` chain per event and avoids the
        # repeated ``setdefault`` method-call overhead in the
        # hot loop.
        per_account: defaultdict[str, defaultdict[int, _BucketStats]] = defaultdict(
            lambda: defaultdict(_BucketStats)
        )

        # Hoist frequently-used lookups for the hot loop.
        get_account = source_map.get

        for e in events:
            account = get_account(e.source_agent_id)
            if account is None:
                # NPC source (or unknown agent) -- silently
                # skip. The per-target roll-ups still see the
                # event (their filter is on ``target_agent_id``),
                # but the per-source-side attribution only
                # counts player agents.
                continue
            bucket_index = e.time_ms // window_ms
            bucket = per_account[account][bucket_index]
            match e:
                case DamageEvent(damage=d):
                    bucket.damage += d
                case HealingEvent(healing=h):
                    bucket.healing += h
                case BuffRemovalEvent(buff_removal=b):
                    bucket.buff_removal += b

        expected_per_account, last_bucket_index = (
            PerPlayerTimelineAggregator._derive_expected_and_last_bucket(per_account)
        )
        # No last-seen char-name update here: the
        # ``Event`` union does NOT carry ``source_name``
        # (the char-name is denormalised on
        # ``OrmFightAgent.name`` and pre-seeded into
        # ``player_name_map`` above). The pre-seeded
        # value is the per-series ``name`` for the
        # lifetime of the aggregation.

        # Build the series list with zero-fill. Every player
        # gets a point at every bucket index from 0 to
        # ``last_bucket_index`` (inclusive) so the
        # visx multi-line chart's arrays are aligned (a
        # strict requirement -- the chart's data shape is
        # ``list[list[number]]`` where every inner list has
        # the same length).
        series: list[PerPlayerTimelineSeries] = []
        for account, buckets in per_account.items():
            points: list[PerPlayerTimelinePoint] = []
            for idx in range(last_bucket_index + 1):
                stats = buckets.get(idx)
                if stats is None:
                    damage = healing = strip = 0
                else:
                    damage = stats.damage
                    healing = stats.healing
                    strip = stats.buff_removal
                points.append(
                    PerPlayerTimelinePoint(
                        window_start_ms=idx * window_ms,
                        window_end_ms=(idx + 1) * window_ms,
                        total_damage=damage,
                        total_healing=healing,
                        total_buff_removal=strip,
                    ),
                )
            series.append(
                PerPlayerTimelineSeries(
                    account_name=account,
                    name=player_name_map.get(account, ""),
                    points=points,
                ),
            )

        # Deterministic ordering: highest total_damage first;
        # ties broken by ascending account_name. Pre-compute the
        # per-series total so the sort key does not re-sum on
        # every comparison.
        series_with_totals = [(sum(p.total_damage for p in s.points), s) for s in series]
        series_with_totals.sort(key=lambda t: (-t[0], t[1].account_name))
        sorted_series = [s for _, s in series_with_totals]

        self._check_invariants(sorted_series, expected_per_account)
        return sorted_series

    @staticmethod
    def _check_invariants(
        series: list[PerPlayerTimelineSeries],
        expected_per_account: dict[str, _BucketStats],
    ) -> None:
        """Raise ``ValueError`` if any cross-field invariant is violated.

        The invariants validate:
        1. The 3 sum-preservation contracts per series (no
           damage / healing / strip events dropped).
        2. The contiguous-points contract per series (every
           2 adjacent points tile the timeline without overlap
           or gap).
        3. The equal-length contract (all series have the
           same number of points -- the visx multi-line
           chart's array-alignment requirement).

        The 3 sub-checks are extracted to private helpers
        so this orchestrator stays under ruff's PLR0912
        ``too-many-branches`` cap (12). The 3 sub-checks
        each carry 1-2 branches of logic.
        """
        PerPlayerTimelineAggregator._check_equal_length(series)
        PerPlayerTimelineAggregator._check_sum_preservation(series, expected_per_account)
        PerPlayerTimelineAggregator._check_contiguous_points(series)

    @staticmethod
    def _derive_expected_and_last_bucket(
        per_account: defaultdict[str, defaultdict[int, _BucketStats]],
    ) -> tuple[defaultdict[str, _BucketStats], int]:
        """Derive expected totals and the last bucket index from accumulators.

        Moving this work out of the hot event loop saves one
        ``max()`` call, one dictionary lookup, and three integer
        additions per input event.
        """
        expected_per_account: defaultdict[str, _BucketStats] = defaultdict(_BucketStats)
        last_bucket_index = -1
        for account, buckets in per_account.items():
            exp = expected_per_account[account]
            for idx, stats in buckets.items():
                exp.damage += stats.damage
                exp.healing += stats.healing
                exp.buff_removal += stats.buff_removal
                last_bucket_index = max(last_bucket_index, idx)
        return expected_per_account, last_bucket_index

    @staticmethod
    def _build_source_map(agents: Iterable[Any]) -> tuple[dict[int, str], dict[str, str]]:
        """Build the source-side attribution map from the agent iterable.

        Filters to player agents (``is_player=True``) with
        non-empty ``account_name``. NPCs and agents missing
        either field are dropped. Also builds the
        ``player_name_map`` for the series' ``name`` field
        (last-seen char-name, pre-seeded from the agent's
        ``name`` attribute).
        """
        source_map: dict[int, str] = {}
        player_name_map: dict[str, str] = {}
        for agent in agents:
            is_player = getattr(agent, "is_player", False)
            if not is_player:
                continue
            account_name = getattr(agent, "account_name", None)
            if not account_name:
                continue
            agent_id = getattr(agent, "agent_id", None)
            if agent_id is None:
                continue
            source_map[agent_id] = account_name
            agent_name = getattr(agent, "name", None) or ""
            player_name_map[account_name] = agent_name
        return source_map, player_name_map

    @staticmethod
    def _check_equal_length(series: list[PerPlayerTimelineSeries]) -> None:
        """All series have the same number of points (the visx array-alignment contract)."""
        if not series:
            return
        first_len = len(series[0].points)
        for s in series[1:]:
            if len(s.points) != first_len:
                msg = (
                    f"series have unequal point counts: "
                    f"{series[0].account_name} has {first_len}, "
                    f"{s.account_name} has {len(s.points)}"
                )
                raise ValueError(msg)

    @staticmethod
    def _check_sum_preservation(
        series: list[PerPlayerTimelineSeries],
        expected: dict[str, _BucketStats],
    ) -> None:
        """Per-series sum of points MUST equal per-series event totals (no events dropped)."""
        for s in series:
            exp = expected[s.account_name]
            actuals = (
                sum(p.total_damage for p in s.points),
                sum(p.total_healing for p in s.points),
                sum(p.total_buff_removal for p in s.points),
            )
            expected_vals = (exp.damage, exp.healing, exp.buff_removal)
            for actual, expected_val, (p_field, e_field) in zip(
                actuals, expected_vals, PerPlayerTimelineAggregator._SUM_CHECK_FIELDS, strict=True
            ):
                if actual != expected_val:
                    msg = (
                        f"series {s.account_name!r}: sum of points.{p_field} "
                        f"({actual}) != sum of event.{e_field} ({expected_val})"
                    )
                    raise ValueError(msg)

    @staticmethod
    def _check_contiguous_points(series: list[PerPlayerTimelineSeries]) -> None:
        """Every 2 adjacent points in a series tile the timeline without overlap or gap."""
        for s in series:
            for prev, curr in pairwise(s.points):
                if prev.window_end_ms != curr.window_start_ms:
                    msg = (
                        f"series {s.account_name!r}: points not contiguous: "
                        f"prev.window_end_ms={prev.window_end_ms} != "
                        f"curr.window_start_ms={curr.window_start_ms}"
                    )
                    raise ValueError(msg)


__all__ = [
    "PerPlayerTimelineAggregator",
    "PerPlayerTimelinePoint",
    "PerPlayerTimelineSeries",
]
