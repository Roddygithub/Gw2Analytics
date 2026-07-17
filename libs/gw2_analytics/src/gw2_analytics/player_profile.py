"""Cross-fight per-account roll-up -- the player-centric view of the dataset.

Phase 7 v2 of analytics (v0.7.0 release). Joins many parsed ``Fight``
records on the stable ``account_name`` key (the operational identity
across uploads) and emits one :class:`PlayerProfile` row per account
with the total damage / healing / buff-removal they produced, the
fights they attended, and their last-seen char-name + first-seen
profession/elite spec.

Conventions
===========

- **Deterministic ordering.** Rows sorted by
  ``(-total_damage, account_name)`` -- highest damage first; ties
  broken by ascending ``account_name`` (alphabetical, mirrors the
  :class:`~gw2_analytics.multi_fight.MultiFightAggregator` sort
  contract so the two aggregators' outputs are visually consistent).
- **First-seen profession / elite.** A player who switches class
  across fights stays anchored to whichever profession/elite they
  were using in the first fight they appeared in. This keeps
  downstream profession-filter queries stable even when a player
  switches specs.
- **Last-seen char name.** A player who renames across fights ends
  up with their LAST char-name here (the operational identity is
  the ``account_name``; the char name is best-effort).
- **Dedup on ``(account_name, fight_id)``.** The same account can
  appear in the same fight more than once if the route layer
  accumulates per-agent (rather than per-account) contributions;
  the dedup keeps ``fights_attended`` from double-counting.
- **No defaults invented.** An empty input yields ``[]``; we never
  synthesise a placeholder row.

Cross-field invariants (validated post-construction; violations raise
``ValueError``):

- ``fights_attended == len(attended_fight_ids)`` and
  ``attended_fight_ids`` strictly ascending.
- Rows monotonically non-increasing by ``total_damage``; ties broken
  by ascending ``account_name``.

Forward compat
==============

The aggregator signature is ``Iterable[FightContribution]`` -> ``list[PlayerProfile]``.
A future v0.8.0 backend that materialises a per-fight per-account
``fight_player_summaries`` table can swap the input shape to a query
result without changing the aggregator contract.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from gw2_core import EliteSpec, Profession

# DPS/HPS/BPS sentinel when ``duration_s == 0``: not relevant here
# (this aggregator is cross-fight, not per-fight), but the constant
# is exported for symmetry with :mod:`gw2_analytics.target_healing`
# in case a future per-fight rate sub-field is added.
_DEFAULT_RATE: Final[float] = 0.0


@dataclass(slots=True)
class _AccountState:
    """Mutable per-account state for the cross-fight roll-up."""

    profession: Profession
    elite: EliteSpec
    name: str = ""
    attended_fight_ids: set[str] = field(default_factory=set)
    total_damage: int = 0
    total_healing: int = 0
    total_buff_removal: int = 0


class FightContribution(BaseModel):
    """One account's per-fight contribution to the cross-fight roll-up.

    The route layer computes one of these per ``(fight, account)`` pair
    by walking the fight's events blob and accumulating magnitudes
    where ``event.source_agent_id`` maps to ``account_name`` via
    :class:`gw2_core.OrmFightAgent` (or, in the Python in-memory test
    path, the synthetic :class:`~gw2_core.Agent`).

    Carries the per-fight identity (char-name + profession + elite) so
    the aggregator can apply the first-seen / last-seen rules without
    needing a second pass against the agents table.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    fight_id: str = Field(..., min_length=1)
    account_name: str = Field(..., min_length=1, max_length=128)
    name: str = Field(default="", max_length=128)
    profession: Profession = Profession.UNKNOWN
    elite: EliteSpec = EliteSpec.UNKNOWN
    total_damage: int = Field(default=0, ge=0)
    total_healing: int = Field(default=0, ge=0)
    total_buff_removal: int = Field(default=0, ge=0)
    # v0.10.3 plan 083: the per-fight role detection (ported
    # from an upstream reference parser) lands as 2 optional fields --
    # ``detected_role`` and ``detected_tags``. Default ``None``
    # preserves the pre-v0.10.3 wire contract (callers that
    # don't run the heuristic still produce a valid contribution).
    # The fast-path (OrmFightPlayerSummary query) projects both
    # fields from the materialised table; the slow-path
    # (events-blob walk) invokes :func:`detect_role_lite`
    # on the per-account accumulator before emitting the
    # contribution. See ``libs/gw2_analytics/role_detection.py``
    # for the algorithm + the an upstream reference parser port rationale.
    detected_role: str | None = None
    detected_tags: list[str] | None = None
    # v0.10.5 plan 135: the condi/power split (additive, nullable for
    # back-compat with pre-v0.10.5 summary rows). Both columns default to
    # ``None`` so the pre-v0.10.5 wire contract holds (callers that don't
    # run the split still produce a valid contribution). The fast-path
    # projects both columns from the materialised
    # ``OrmFightPlayerSummary`` row; the slow-path computes them inline
    # during the events walk. The split is build-date-gated: pre-20240501
    # arcdps encodes the condi portion implicitly via the skill name
    # (KNOWN_CONDI_NAMES lookup); post-20240501 arcdps encodes it in the
    # raw cbtevent ``buff_dmg`` field, but the v0.10.5 parser-side
    # integration is deferred (see ``advisor-plans/006a``); new fights
    # stay NULL until that lands.
    # See ``libs/gw2_analytics/condi_power_split.py`` for the algorithm
    # + the arcdps-build-date threshold calibration note.
    power_damage: int | None = None
    condi_damage: int | None = None


class PlayerProfile(BaseModel):
    """One row of the cross-fight player roll-up.

    Stable cross-fight identity: the ``account_name`` is the primary
    key (the operational identity), the ``name`` is the last-seen
    char-name (the cosmetic identity).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_name: str = Field(..., min_length=1, max_length=128)
    name: str = Field(default="", max_length=128)
    profession: Profession = Profession.UNKNOWN
    elite: EliteSpec = EliteSpec.UNKNOWN
    fights_attended: int = Field(..., ge=1)
    total_damage: int = Field(..., ge=0)
    total_healing: int = Field(..., ge=0)
    total_buff_removal: int = Field(..., ge=0)
    attended_fight_ids: list[str] = Field(default_factory=list)


class PlayerProfileAggregator:
    """Stateless aggregator: per-fight contributions -> per-account profiles.

    Instantiate once and reuse -- the class holds no state.

    The aggregator is fed one :class:`FightContribution` per
    ``(fight_id, account_name)`` pair. The same ``(account_name, fight_id)``
    pair appearing twice is silently de-duplicated (the second
    occurrence's per-fight totals are added to the first); the dedup
    keeps ``fights_attended`` and ``attended_fight_ids`` from
    double-counting when the route layer materialises the
    contributions.
    """

    def aggregate(
        self,
        contributions: Iterable[FightContribution],
    ) -> list[PlayerProfile]:
        """Compute the cross-fight player profile roll-up.

        Iterating ``contributions`` once ensures the caller can pass
        a generator / filtered iterator without materialisation --
        this matches the apps/api upload-pipeline pattern where
        per-fight contributions come off a streaming Postgres query.
        """
        # Per-account state. Each account's first-seen profession/elite
        # is anchored to whichever pair appeared first; last-seen name
        # follows whichever contribution was most recent.
        state_by_account: dict[str, _AccountState] = {}

        for c in contributions:
            acct = c.account_name
            # v0.9.6 plan 023: a single account can emit multiple
            # ``FightContribution`` records for the same fight (one per
            # character -- a class swap / squad move / reconnect emits a
            # new agent under the same ``account_name``). We ACCUMULATE
            # the per-character magnitudes; the ``attended_fight_ids``
            # set handles the dedup automatically (set semantics
            # collapse the duplicates). The pre-plan-023
            # ``if key in seen_pairs: continue`` early-skip silently
            # dropped the second character's contribution; the fix
            # moves the per-magnitude accumulation OUTSIDE the
            # dedup check.
            state = state_by_account.get(acct)
            if state is None:
                state = _AccountState(
                    profession=c.profession,
                    elite=c.elite,
                )
                state_by_account[acct] = state
            # Last-seen char-name: every contribution overwrites.
            state.name = c.name
            state.attended_fight_ids.add(c.fight_id)
            state.total_damage += c.total_damage
            state.total_healing += c.total_healing
            state.total_buff_removal += c.total_buff_removal

        profiles = sorted(
            [
                PlayerProfile(
                    account_name=acct,
                    name=state.name,
                    profession=state.profession,
                    elite=state.elite,
                    fights_attended=len(state.attended_fight_ids),
                    total_damage=state.total_damage,
                    total_healing=state.total_healing,
                    total_buff_removal=state.total_buff_removal,
                    attended_fight_ids=sorted(state.attended_fight_ids),
                )
                for acct, state in state_by_account.items()
            ],
            key=lambda p: (-p.total_damage, p.account_name),
        )

        self._check_invariants(profiles)
        return profiles

    @staticmethod
    def _check_invariants(profiles: list[PlayerProfile]) -> None:
        """Raise ``ValueError`` if any cross-field invariant is violated."""
        for p in profiles:
            if p.fights_attended != len(p.attended_fight_ids):
                msg = (
                    f"PlayerProfile({p.account_name!r}).fights_attended "
                    f"({p.fights_attended}) != len(attended_fight_ids) "
                    f"({len(p.attended_fight_ids)})"
                )
                raise ValueError(msg)
            for prev_id, curr_id in pairwise(p.attended_fight_ids):
                if prev_id >= curr_id:
                    msg = (
                        f"PlayerProfile({p.account_name!r}).attended_fight_ids "
                        f"not strictly ascending: {p.attended_fight_ids!r}"
                    )
                    raise ValueError(msg)
        # Cross-row ordering contract: descending total_damage with
        # ascending account_name tie-break. ``pairwise`` is the
        # canonical adjacent-pair idiom (ruff RUF007).
        for prev, curr in pairwise(profiles):
            if prev.total_damage < curr.total_damage:
                msg = (
                    f"profiles not ordered by (total_damage DESC, "
                    f"account_name ASC): {prev!r} then {curr!r}"
                )
                raise ValueError(msg)
            if prev.total_damage == curr.total_damage and prev.account_name >= curr.account_name:
                msg = f"tie on total_damage not broken by account_name ASC: {prev!r} then {curr!r}"
                raise ValueError(msg)


__all__ = ["FightContribution", "PlayerProfile", "PlayerProfileAggregator"]
