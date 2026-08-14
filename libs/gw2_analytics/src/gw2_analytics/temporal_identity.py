"""Temporal identity resolution for CAP-4 (Story 3).

Provides time-parameterized queries for agent ownership and identity,
handling character swaps, instance ID recycling, and master/pet/minion
relationships.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from gw2_evtc_parser import OwnershipInterval

if TYPE_CHECKING:
    from gw2_core import Agent as CoreAgent


@dataclass(frozen=True, slots=True)
class AgentIdentity:
    """Resolved identity of an agent at a specific time."""

    agent_id: int
    account: str | None
    name: str
    profession: str
    elite: str
    is_player: bool
    instance_id: int
    owner_agent_id: int | None
    owner_account: str | None
    slice_index: int | None = None


@dataclass(slots=True)
class TemporalIdentityResolver:
    """Time-parameterized resolver for agent ownership and identity.

    Built from:
    - ``ownership_intervals``: output of ``scan_ownership_intervals()``
    - ``agent_awareness``: output of ``scan_agent_awareness()`` (fight-relative first/last aware)
    - ``agents``: parsed agent table from the fight
    """

    ownership_intervals: list[OwnershipInterval]
    agent_awareness: dict[int, tuple[int, int]]
    agents: list[CoreAgent]

    # Private indices (not passed to constructor)
    _by_agent: dict[int, list[OwnershipInterval]] = field(
        default_factory=lambda: defaultdict(list), init=False
    )
    _agent_by_id: dict[int, CoreAgent] = field(default_factory=dict, init=False)
    _account_slices: dict[str, list[tuple[int, int]]] = field(
        default_factory=lambda: defaultdict(list), init=False
    )
    _instance_history: dict[int, list[tuple[int, int, int]]] = field(
        default_factory=lambda: defaultdict(list), init=False
    )
    _awareness_by_instance: dict[int, list[tuple[int, int, int]]] = field(
        default_factory=lambda: defaultdict(list), init=False
    )

    def __post_init__(self) -> None:
        # Index intervals by agent_id for fast lookup
        for iv in self.ownership_intervals:
            self._by_agent[iv.agent_id].append(iv)

        # Agent lookup by id
        self._agent_by_id = {a.id: a for a in self.agents}

        # Account -> list of (agent_id, slice_index) for player slices
        for idx, agent in enumerate(self.agents):
            if agent.account_name:
                self._account_slices[agent.account_name.lstrip(":")].append((agent.id, idx))

        # Instance -> list of (agent_id, start_ms, end_ms) for recycling
        # detection (from ownership intervals)
        for iv in self.ownership_intervals:
            if iv.instance_id:
                self._instance_history[iv.instance_id].append((iv.agent_id, iv.start_ms, iv.end_ms))

        # Instance -> list of (agent_id, first_aware, last_aware) for recycling
        # detection (from awareness)
        self._awareness_by_instance: dict[int, list[tuple[int, int, int]]] = defaultdict(list)
        for aid, (first, last) in self.agent_awareness.items():
            agent = self._agent_by_id.get(aid)
            if agent and agent.instance_id:
                self._awareness_by_instance[agent.instance_id].append((aid, first, last))

    # --- Core ownership queries ---

    def owner_at(self, agent_id: int, time_ms: int) -> int | None:
        """Return owning agent_id at given fight-relative timestamp, or None."""
        for iv in self._by_agent.get(agent_id, ()):
            if iv.start_ms <= time_ms < iv.end_ms:
                return iv.owner_agent_id
        return None

    def owned_agents_at(self, owner_agent_id: int, time_ms: int) -> list[int]:
        """All agent_ids owned by master at time_ms."""
        result: list[int] = []
        for agent_id, intervals in self._by_agent.items():
            for iv in intervals:
                if iv.start_ms <= time_ms < iv.end_ms and iv.owner_agent_id == owner_agent_id:
                    result.append(agent_id)
                    break
        return result

    def ownership_interval_at(self, agent_id: int, time_ms: int) -> OwnershipInterval | None:
        """Return the full ownership interval covering time_ms, or None."""
        for iv in self._by_agent.get(agent_id, ()):
            if iv.start_ms <= time_ms < iv.end_ms:
                return iv
        return None

    # --- Identity resolution ---

    def agent_identity_at(self, agent_id: int, time_ms: int) -> AgentIdentity | None:
        """Resolve full identity of agent at time_ms."""
        agent = self._agent_by_id.get(agent_id)
        if agent is None:
            return None

        iv = self.ownership_interval_at(agent_id, time_ms)
        owner_id = iv.owner_agent_id if iv else None
        owner_agent = self._agent_by_id.get(owner_id) if owner_id else None
        owner_account = (
            owner_agent.account_name.lstrip(":")
            if owner_agent and owner_agent.account_name
            else None
        )

        # Determine slice index for split accounts
        slice_index = None
        if agent.account_name:
            account = agent.account_name.lstrip(":")
            for idx, (aid, _sidx) in enumerate(self._account_slices.get(account, [])):
                if aid == agent_id:
                    slice_index = idx
                    break

        return AgentIdentity(
            agent_id=agent_id,
            account=agent.account_name.lstrip(":") if agent.account_name else None,
            name=agent.name,
            profession=str(agent.profession),
            elite=str(agent.elite),
            is_player=agent.is_player,
            instance_id=agent.instance_id,
            owner_agent_id=owner_id,
            owner_account=owner_account,
            slice_index=slice_index,
        )

    def slice_owner_account(self, owner_agent_id: int, slice_lo: int, slice_hi: int) -> str | None:
        """Account name for the owner during a player slice.

        Uses the slice midpoint to resolve ownership (consistent with
        EI's firstAware/lastAware windowing).
        """
        mid = (slice_lo + slice_hi) // 2
        owner = self.owner_at(owner_agent_id, mid)
        if owner is None:
            return None
        owner_agent = self._agent_by_id.get(owner)
        return (
            owner_agent.account_name.lstrip(":")
            if owner_agent and owner_agent.account_name
            else None
        )

    # --- Instance recycling helpers ---

    def instance_recycle_count(self, instance_id: int) -> int:
        """How many distinct agents have used this instance_id."""
        return len(self._instance_history.get(instance_id, ()))

    def instance_agents(self, instance_id: int) -> list[tuple[int, int, int]]:
        """All (agent_id, start_ms, end_ms) for this instance_id
        chronological."""
        return self._instance_history.get(instance_id, [])

    def awareness_by_instance(self, instance_id: int) -> list[tuple[int, int, int]]:
        """All (agent_id, first_aware_ms, last_aware_ms) for
        this instance_id from awareness spans."""
        return self._awareness_by_instance.get(instance_id, [])

    # --- Awareness bounds ---

    def awareness_span(self, agent_id: int) -> tuple[int, int] | None:
        """Return (first_aware_ms, last_aware_ms) fight-relative, or None."""
        return self.agent_awareness.get(agent_id)

    def is_present_at(self, agent_id: int, time_ms: int) -> bool:
        """Whether the log mentions this agent at time_ms (via awareness)."""
        span = self.agent_awareness.get(agent_id)
        if span is None:
            return False
        return span[0] <= time_ms <= span[1]

    def active_duration_for_slice(
        self, alias_id: int, slice_lo: int, slice_hi: int, fight_duration_ms: int
    ) -> int | None:
        """Return active duration for buff simulation within a slice.

        For agents that are part of an instance-recycled group within the slice
        (multiple agents with same instance_id whose awareness spans overlap the slice),
        return the slice duration so buff uptime is computed over the full slice window.
        Otherwise, fall back to awareness-based bound.
        """
        agent = self._agent_by_id.get(alias_id)
        if not agent or not agent.instance_id:
            return None
        # Check if this instance_id has multiple agents whose awareness overlaps the slice
        count = 0
        for other_id, (first, last) in self.agent_awareness.items():
            other_agent = self._agent_by_id.get(other_id)
            if (
                other_agent
                and other_agent.instance_id == agent.instance_id
                and not (last < slice_lo or first > slice_hi)
            ):
                count += 1
                if count > 1:
                    # Instance recycling detected within slice: use slice duration
                    return slice_hi - slice_lo
        # No instance recycling: fall back to awareness bound
        span = self.agent_awareness.get(alias_id)
        if span is None or fight_duration_ms - span[1] <= 1000:
            return None
        return span[1] + 10


def build_resolver(
    ownership_intervals: list[OwnershipInterval],
    agent_awareness: dict[int, tuple[int, int]],
    agents: list[CoreAgent],
) -> TemporalIdentityResolver:
    """Factory for constructing a TemporalIdentityResolver."""
    return TemporalIdentityResolver(
        ownership_intervals=ownership_intervals,
        agent_awareness=agent_awareness,
        agents=agents,
    )
