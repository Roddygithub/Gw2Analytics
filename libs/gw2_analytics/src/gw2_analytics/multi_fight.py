"""Multi-fight aggregations built on top of :mod:`gw2_core`.

Phase 3 depth. Aggregates an *iterable* of parsed :class:`~gw2_core.Fight`
records into a :class:`MultiFightAggregate` -- a denormalised view of
combatant attendance across fights, keyed by stable ``account_name``.

The single-fight sibling (:mod:`.aggregate`) remains the canonical
entry-point for per-fight metrics; this module is the **roll-up over
many fights**, designed for dashboards / cross-fight attendance queries
that need stable player identities, not per-fight denormalisation.

Conventions
===========

- **Deterministic ordering.** ``fight_ids`` sorted ascending;
  ``combatant_rollups`` sorted by ``account_name``. Two runs over the
  same input MUST yield byte-identical output.
- **Last-seen char name.** A player who renames across fights ends up
  with their LAST char-name here (the operational identity is the
  ``account_name``; the char name is best-effort).
- **First-seen profession / elite.** A player who switches class across
  fights stays anchored to whichever profession/elite they were using
  in the first fight they appeared in. This keeps downstream
  profession-filter queries stable even when a player switches specs.
- **Dedup policy.** Same ``Fight.id`` appearing twice is silently
  ignored (idempotency for the upload-then-reupload case) and a
  ``logging.warning`` is emitted via the standard logging module.
- **Empty-agents drop.** A ``Fight`` with ``len(fight.agents) == 0``
  is silently dropped (its ID does **not** appear in ``fight_ids``);
  this avoids attendance-percentage skew from terminal parser
  failures that emit a header but no agent block.

Cross-field invariants (validated post-construction; violations raise
``ValueError``):

- ``fight_ids`` strictly ascending.
- ``combatant_rollups`` strictly ordered by ``account_name``.
- For every ``CombatantRollup c``: ``c.player_attendance <= len(fight_ids)``.
- ``total_players == sum(c.player_attendance for c in combatant_rollups)``.

Forward-compat
==============

The module is intentionally narrow: ``MultiFightAggregate`` collates
fights through ``SingleFightAggregator`` (so the WvW empty-account
quirk filter, the deterministic ordering, and the strict cross-field
invariants are reused). Future siblings (``EventWindowAggregator``,
``TargetDpsAggregator``, etc.) drop into new files in
:mod:`gw2_analytics` without touching this surface.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import pairwise
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from gw2_analytics.aggregate import SingleFightAggregator
from gw2_core import EliteSpec, Fight, Profession

logger = logging.getLogger(__name__)
# Per the stdlib logging cookbook: add a NullHandler by default so
# ``logger.warning(...)`` calls don't fall through to the root
# logger in downstream apps that haven't configured logging yet.
logger.addHandler(logging.NullHandler())


@dataclass(slots=True)
class _AccountState:
    """Mutable per-account state for the multi-fight roll-up."""

    profession: Profession
    elite: EliteSpec
    name: str = ""
    attendance: int = 0


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class CombatantRollup(BaseModel):
    """Per-account attendance + identity roll-up across fights.

    Distinct from :class:`~gw2_analytics.aggregate.CombatantSummary` in
    two ways:

    1. The schema is keyed on ``account_name`` (one row per stable
       account, not one row per agent-record).
    2. ``name`` is the LAST char-name seen (final-state, not
       first-state) -- the operational identity is the account.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_name: str = Field(..., min_length=1, max_length=128)
    name: str = Field(default="", max_length=128)
    profession: Profession = Profession.UNKNOWN
    elite: EliteSpec = EliteSpec.UNKNOWN
    player_attendance: int = Field(..., ge=1)


class MultiFightAggregate(BaseModel):
    """Denormalised multi-fight roll-up.

    Constructed via :meth:`MultiFightAggregator.aggregate`. The
    invariants listed on :class:`MultiFightAggregator` are
    *post-construction* validated; Pydantic's per-field constraints
    only catch ``frozen=True``, ``extra="forbid"``, and ``min_length`` /
    ``ge`` / ``le`` violations.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    fight_ids: list[str] = Field(default_factory=list)
    total_agents: int = Field(..., ge=0)
    total_players: int = Field(..., ge=0)
    combatant_rollups: list[CombatantRollup] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------


class MultiFightAggregator:
    """Stateless aggregator: input ``Iterable[Fight]`` -> ``MultiFightAggregate``.

    Instantiate once and reuse across queries -- the class holds no state.

    The aggregator unconditionally delegates per-fight work to
    :class:`~gw2_analytics.aggregate.SingleFightAggregator` so the
    perfect-fight invariants (WvW empty-account quirk filter,
    cross-field ``player + npc == agent``, deterministic
    combatants/groups/catalog ordering) are inherited unchanged.
    """

    #: Inner aggregator reused across every per-fight pass. Stateless.
    _inner: Final[SingleFightAggregator] = SingleFightAggregator()

    def aggregate(self, fights: Iterable[Fight]) -> MultiFightAggregate:
        """Compute the multi-fight aggregate from an iterable of fights.

        Iterating ``fights`` once ensures the caller can pass a
        generator / filtered iterator without materialisation -- this
        matters for the apps/api upload-pipeline where fights come off
        a streaming pandas query.
        """
        seen_fight_ids: set[str] = set()
        accepted_fight_ids: list[str] = []
        total_agents = 0
        # Per-account rollup state.
        state_by_account: dict[str, _AccountState] = {}

        for fight in fights:
            if not fight.id:
                msg = "fight.id must be non-empty"
                raise ValueError(msg)
            if fight.id in seen_fight_ids:
                logger.warning(
                    "MultiFightAggregator: duplicate fight_id %r ignored",
                    fight.id,
                )
                continue

            # Empty-agents drop policy: silent exclusion from fight_ids.
            # IMPORTANT: do this BEFORE ``seen_fight_ids.add(...)`` so a
            # previously-dropped empty fight's id doesn't pollute the
            # dedup set -- a repair re-upload of the same id with real
            # agents must still be accepted below.
            if len(fight.agents) == 0:
                logger.debug(
                    "MultiFightAggregator: dropping empty-agents fight %r",
                    fight.id,
                )
                continue
            seen_fight_ids.add(fight.id)

            accepted_fight_ids.append(fight.id)
            total_agents += len(fight.agents)

            # Delegate to SingleFightAggregator to inherit the WvW
            # empty-account quirk filter + deterministic per-fight
            # ordering + cross-field invariants.
            per_fight = self._inner.aggregate(fight)
            # v0.9.6 plan 022: dedup per-fight before incrementing
            # attendance. A player who reconnects / swaps class /
            # moves squad within a single fight has multiple
            # combatants with the same account_name; we count
            # attendance ONCE per fight per account (the player is
            # either "in this fight" or "not in this fight", not
            # "in this fight N times"). The state is per-fight, so
            # re-initialise inside the outer loop.
            seen_accounts_this_fight: set[str] = set()
            for c in per_fight.combatants:
                acct = c.account_name
                if acct in seen_accounts_this_fight:
                    continue
                seen_accounts_this_fight.add(acct)
                state = state_by_account.get(acct)
                if state is None:
                    state = _AccountState(
                        profession=c.profession,
                        elite=c.elite,
                    )
                    state_by_account[acct] = state
                state.name = c.name
                state.attendance += 1

        combatant_rollups = sorted(
            [
                CombatantRollup(
                    account_name=acct,
                    name=state.name,
                    profession=state.profession,
                    elite=state.elite,
                    player_attendance=state.attendance,
                )
                for acct, state in state_by_account.items()
            ],
            key=lambda c: c.account_name,
        )

        aggregate = MultiFightAggregate(
            fight_ids=sorted(accepted_fight_ids),
            total_agents=total_agents,
            total_players=sum(state.attendance for state in state_by_account.values()),
            combatant_rollups=combatant_rollups,
        )

        self._check_invariants(aggregate)
        return aggregate

    @staticmethod
    def _check_invariants(agg: MultiFightAggregate) -> None:
        """Raise ``ValueError`` if any cross-field invariant is violated."""
        for prev_id, curr_id in pairwise(agg.fight_ids):
            if prev_id >= curr_id:
                msg = f"fight_ids not strictly ascending: {agg.fight_ids!r}"
                raise ValueError(msg)
        for prev, curr in pairwise(agg.combatant_rollups):
            if prev.account_name >= curr.account_name:
                msg = (
                    f"combatant_rollups not sorted by account_name: "
                    f"{prev.account_name!r} >= {curr.account_name!r}"
                )
                raise ValueError(msg)
        for c in agg.combatant_rollups:
            if c.player_attendance > len(agg.fight_ids):
                msg = (
                    f"CombatantRollup({c.account_name!r}).player_attendance "
                    f"({c.player_attendance}) > len(fight_ids) "
                    f"({len(agg.fight_ids)})"
                )
                raise ValueError(msg)
        expected_players = sum(c.player_attendance for c in agg.combatant_rollups)
        if agg.total_players != expected_players:
            msg = (
                f"total_players ({agg.total_players}) != "
                f"sum(player_attendance) ({expected_players})"
            )
            raise ValueError(msg)


__all__ = [
    "CombatantRollup",
    "MultiFightAggregate",
    "MultiFightAggregator",
]
