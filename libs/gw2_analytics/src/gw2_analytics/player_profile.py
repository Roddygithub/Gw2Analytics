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
from itertools import pairwise
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from gw2_core import EliteSpec, Profession

# DPS/HPS/BPS sentinel when ``duration_s == 0``: not relevant here
# (this aggregator is cross-fight, not per-fight), but the constant
# is exported for symmetry with :mod:`gw2_analytics.target_healing`
# in case a future per-fight rate sub-field is added.
_DEFAULT_RATE: Final[float] = 0.0


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
        first_seen_profession: dict[str, Profession] = {}
        first_seen_elite: dict[str, EliteSpec] = {}
        last_seen_name: dict[str, str] = {}
        seen_pairs: set[tuple[str, str]] = set()
        attended_fight_ids: dict[str, set[str]] = {}
        total_damage: dict[str, int] = {}
        total_healing: dict[str, int] = {}
        total_buff_removal: dict[str, int] = {}

        for c in contributions:
            acct = c.account_name
            # First-seen anchor: ``setdefault`` is the canonical
            # "insert if absent, do not overwrite" idiom. The first
            # contribution to land for an account wins.
            first_seen_profession.setdefault(acct, c.profession)
            first_seen_elite.setdefault(acct, c.elite)
            # Last-seen char-name: every contribution overwrites.
            last_seen_name[acct] = c.name
            # Dedup on (account_name, fight_id): the same account
            # appearing twice in the same fight (route layer bug,
            # manual table fixup) silently folds to a single
            # contribution. ``seen_pairs.add(...)`` returns None if
            # the pair was already present; the subsequent accumulation
            # steps are skipped in that case so ``fights_attended``
            # stays at the actual count of distinct fights.
            key = (acct, c.fight_id)
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            attended_fight_ids.setdefault(acct, set()).add(c.fight_id)
            total_damage[acct] = total_damage.get(acct, 0) + c.total_damage
            total_healing[acct] = total_healing.get(acct, 0) + c.total_healing
            total_buff_removal[acct] = total_buff_removal.get(acct, 0) + c.total_buff_removal

        profiles = sorted(
            [
                PlayerProfile(
                    account_name=acct,
                    name=last_seen_name.get(acct, ""),
                    profession=first_seen_profession[acct],
                    elite=first_seen_elite[acct],
                    fights_attended=len(attended_fight_ids[acct]),
                    total_damage=total_damage.get(acct, 0),
                    total_healing=total_healing.get(acct, 0),
                    total_buff_removal=total_buff_removal.get(acct, 0),
                    attended_fight_ids=sorted(attended_fight_ids[acct]),
                )
                for acct in attended_fight_ids
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
            if sorted(p.attended_fight_ids) != p.attended_fight_ids:
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
