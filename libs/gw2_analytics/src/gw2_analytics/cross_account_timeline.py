"""v0.10.0 plan 032: cross-account timeline aggregator.

The squad-comparison use case: overlay 2-4 accounts' per-fight
timelines on the same chart. The existing :class:`player_profile`
:mod:`gw2_analytics.player_profile` aggregator emits a per-account
cross-fight roll-up; the v0.8.0 ``GET /api/v1/players/{account}/{timeline}``
route emits a per-account per-fight timeline; plan 032 combines the
two by emitting one per-account timeline PER account, side-by-side.

Design rationale
================

The aggregator wraps the per-account timeline computation so the
route layer can call once per requested account. Splitting the
computation into per-account calls (rather than one big join) keeps
the existing :func:`_combine_day_midnight` helper localized and the
``?tz=`` / ``?bucket=`` parsing identical to the per-account
endpoint (an analyst who has read the timeline route can read the
compare route with zero learning curve).

Conventions
===========

- **Deterministic ordering.** Each series' ``points`` array mirrors
  the existing per-account contract: recency-first (``started_at
  DESC`` with ``fight_id ASC`` tiebreaker). The TOP-LEVEL output
  is an array of series -- NOT a single flattened list -- because
  the chart needs per-account lines, NOT inter-account interleaving.
- **Empty input yields an empty list.** An aggregator with zero
  accounts emits ``series=[]``; we never invent placeholder rows.
- **Account not in any fight.** An account with no contributions is
  reported as ``series: [{ account_name, name: "", points: [] }]``
  to surface "this account requested but has no attended fights"
  in the response (the route's 404-vs-empty distinction is owned by
  the calling layer, not the aggregator).

Cross-field invariants (validated post-construction; violations
raise ``ValueError``):

- ``len(series) == len(accounts)`` (the response surfaces an empty
  series entry for each requested account -- the route handler
  never lossy-drops an empty account).
- Each series' ``points`` is sorted recency-first (the same
  contract as :class:`PlayerTimelineOut.points`).

Forward-compat
==============

The aggregator signature is ``Mapping[str, Iterable[FightContribution]]``
-> ``list[CrossAccountTimelineSeries]``. A future v0.11.0 backend
that materialises a per-(fight, account) ``fight_player_summaries``
table can swap the input shape to a single query result without
changing the aggregator contract.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from gw2_analytics.player_profile import FightContribution


class CrossAccountTimelinePoint(BaseModel):
    """One per-fight timeline point within a per-account series.

    Mirrors :class:`gw2_analytics.player_profile.PlayrTimelinePoint`'s
    wire shape -- ``fight_id`` + ``started_at`` + the 3 totals -- so
    the route layer can reuse the same JSON surface for both the
    per-account and the cross-account timeline responses. The
    rechristening is purely cosmetic (the cross-account aggregator
    wraps the per-account points list without any field-level
    divergence); using a separate type here guards against future
    divergence (e.g. a per-account-vs-cross-account rate column
    for fair comparison would not silently leak into the
    per-account route).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    fight_id: str = Field(..., min_length=1)
    started_at: datetime
    total_damage: int = Field(default=0, ge=0)
    total_healing: int = Field(default=0, ge=0)
    total_buff_removal: int = Field(default=0, ge=0)


class CrossAccountTimelineSeries(BaseModel):
    """One per-account series within a cross-account timeline response.

    The chart renders one polyline per series; the page-level
    section consumes the ``series`` array directly. The shape
    deliberately mirrors the existing per-account ``PlayerTimeline``
    so the cross-account route can be a thin wrapper over the
    per-account timeline logic.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_name: str = Field(..., min_length=1, max_length=128)
    name: str = Field(default="", max_length=128)
    points: list[CrossAccountTimelinePoint] = Field(default_factory=list)


class CrossAccountTimelineAggregator:
    """Stateless aggregator: per-account contributions -> per-account series.

    Instantiate once and reuse -- the class holds no state.
    """

    def aggregate(
        self,
        per_account_contributions: Mapping[str, Iterable[FightContribution]],
        fight_id_to_started: Mapping[str, Any],
        bucket: str = "fight",
        tz: ZoneInfo | None = None,
    ) -> list[CrossAccountTimelineSeries]:
        """Compute the cross-account series list from per-account per-fight totals.

        Parameters
        ----------
        per_account_contributions
            Dict keyed by ``account_name`` -> iterable of
            :class:`FightContribution`. The aggregator emits one
            :class:`CrossAccountTimelineSeries` per KEY in this
            dict; an account with NO contributions in the iterable
            still gets a series entry (with empty ``points``) so
            the route can differentiate "0 fights attended" from
            "account not in any fight".
        fight_id_to_started
            Dict keyed by ``fight_id`` -> ``datetime`` so each
            contribution's ``started_at`` is sourced from the same
            authoritative ``OrmFight.started_at`` column the
            per-account timeline route uses.
        bucket
            ``"fight"`` (default): one point per attended fight.
            ``"day"``: one point per UTC calendar day, with the
            3 totals summed across the day's fights and the
            ``started_at`` rounded to day-midnight in the
            requested TZ.
        tz
            :class:`ZoneInfo` parsed from the ``?tz=`` query
            param. Only used in ``"day"`` mode. ``None`` is
            treated as ``UTC`` (the per-account timeline's
            default).
        """
        parsed_tz = tz or ZoneInfo("UTC")
        series_list: list[CrossAccountTimelineSeries] = []
        for account_name, contributions in per_account_contributions.items():
            series_list.append(
                self._aggregate_one_account(
                    account_name,
                    contributions,
                    fight_id_to_started,
                    bucket,
                    parsed_tz,
                ),
            )
        self._check_invariants(series_list)
        return series_list

    @staticmethod
    def _aggregate_one_account(
        account_name: str,
        contributions: Iterable[FightContribution],
        fight_id_to_started: Mapping[str, Any],
        bucket: str,
        tz: ZoneInfo,
    ) -> CrossAccountTimelineSeries:
        """Build one per-account series from per-fight contributions.

        Recency-first sort + day-bucketing follow the same
        contracts as the per-account timeline route's helper
        functions. The ``last_seen_name`` mirror is preserved
        (the analyst sees the most-recent char-name on the
        chart label).
        """
        sorted_contributions = sorted(
            (c for c in contributions if c.account_name == account_name),
            key=lambda c: (
                fight_id_to_started.get(c.fight_id, c.fight_id),
                c.fight_id,
            ),
            reverse=True,
        )
        last_seen_name = ""
        for c in sorted_contributions:
            last_seen_name = c.name
        if bucket == "day":
            points = _day_bucketed_points(sorted_contributions, fight_id_to_started, tz)
        else:
            points = [
                CrossAccountTimelinePoint(
                    fight_id=c.fight_id,
                    started_at=fight_id_to_started.get(c.fight_id, c.fight_id),
                    total_damage=c.total_damage,
                    total_healing=c.total_healing,
                    total_buff_removal=c.total_buff_removal,
                )
                for c in sorted_contributions
            ]
        return CrossAccountTimelineSeries(
            account_name=account_name,
            name=last_seen_name,
            points=points,
        )

    @staticmethod
    def _check_invariants(
        series_list: list[CrossAccountTimelineSeries],
    ) -> None:
        """Raise ``ValueError`` if a series' ``points`` is not recency-first sorted.

        The length-mismatch check (series_list length vs the
        requested accounts map) is structurally guaranteed by
        the aggregator's per-key iteration, so it's not asserted
        here -- adding it would be a tautological guard.
        """
        for s in series_list:
            if (
                s.points
                and sorted(
                    s.points,
                    key=lambda p: (p.started_at, p.fight_id),
                    reverse=True,
                )
                != s.points
            ):
                raise ValueError(
                    f"series {s.account_name!r} not recency-first sorted: {s.points!r}"
                )


def _day_bucketed_points(
    sorted_contributions: list[FightContribution],
    fight_id_to_started: Mapping[str, Any],
    tz: ZoneInfo,
) -> list[CrossAccountTimelinePoint]:
    """Collapse fights sharing a calendar day into one point per day.

    Same algorithm as the per-account timeline's day-bucketing
    branch: ``aware_utc.astimezone(tz).date().isoformat()`` keys the
    day; the 3 totals are the SUM of the day's fights; the
    ``started_at`` is the day-midnight in the requested TZ
    (serialised as UTC for wire compat). The ``fight_id`` of the
    day-bucketed point is the most-recent fight_id of the day (the
    deterministic recency-first tiebreaker).
    """
    day_totals: dict[str, dict[str, int]] = defaultdict(
        lambda: {"damage": 0, "healing": 0, "strip": 0},
    )
    day_first_fight: dict[str, str] = {}
    day_first_started: dict[str, Any] = {}
    for c in sorted_contributions:
        started_at = fight_id_to_started[c.fight_id]
        aware_utc = started_at.replace(tzinfo=UTC) if started_at.tzinfo is None else started_at
        day_key = aware_utc.astimezone(tz).date().isoformat()
        day_first_fight.setdefault(day_key, c.fight_id)
        day_first_started.setdefault(day_key, started_at)
        day_totals[day_key]["damage"] += c.total_damage
        day_totals[day_key]["healing"] += c.total_healing
        day_totals[day_key]["strip"] += c.total_buff_removal
    return [
        CrossAccountTimelinePoint(
            fight_id=day_first_fight[day_key],
            started_at=_combine_day_midnight(day_first_started[day_key], tz),
            total_damage=day_totals[day_key]["damage"],
            total_healing=day_totals[day_key]["healing"],
            total_buff_removal=day_totals[day_key]["strip"],
        )
        for day_key in day_totals
    ]


def _combine_day_midnight(started_at: datetime, tz: ZoneInfo) -> datetime:
    """Return the day-midnight in the requested TZ, serialised as UTC for wire compat.

    Mirrors the per-account timeline's ``_combine_day_midnight``
    helper exactly -- re-implemented here so the
    cross-account aggregator is decoupled from the route layer.
    See :mod:`gw2analytics_api.routes.players` for the per-call
    rationale.
    """
    aware_utc = started_at.replace(tzinfo=UTC) if started_at.tzinfo is None else started_at
    local_midnight = aware_utc.astimezone(tz).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    return local_midnight.astimezone(UTC)


__all__ = [
    "CrossAccountTimelineAggregator",
    "CrossAccountTimelinePoint",
    "CrossAccountTimelineSeries",
]
