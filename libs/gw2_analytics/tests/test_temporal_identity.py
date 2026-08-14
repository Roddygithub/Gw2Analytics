"""Tests for TemporalIdentityResolver (CAP-4 / Story 3)."""

from __future__ import annotations

from gw2_analytics.temporal_identity import (
    OwnershipInterval,
    build_resolver,
)
from gw2_core import (
    Agent,
    EliteSpec,
    Profession,
)


def _agent(
    id: int,
    name: str,
    account: str | None = None,
    profession: Profession = Profession.GUARDIAN,
    elite: EliteSpec = EliteSpec.DRAGONHUNTER,
    instance_id: int = 0,
    is_player: bool = True,
    species_id: int | None = None,
) -> Agent:
    return Agent(
        id=id,
        name=name,
        profession=profession,
        elite=elite,
        is_player=is_player,
        account_name=account,
        instance_id=instance_id,
        species_id=species_id,
    )


def _interval(
    agent_id: int,
    owner_agent_id: int | None,
    instance_id: int,
    start_ms: int,
    end_ms: int,
    is_player: bool = False,
    species_id: int | None = None,
) -> OwnershipInterval:
    return OwnershipInterval(
        agent_id=agent_id,
        owner_agent_id=owner_agent_id,
        instance_id=instance_id,
        species_id=species_id,
        start_ms=start_ms,
        end_ms=end_ms,
        is_player=is_player,
    )


def test_resolver_owner_at() -> None:
    """owner_at returns the master for a minion during its ownership interval."""
    agents = [
        _agent(1, "Master", account=":Master.1234", instance_id=100),
        _agent(2, "Pet", is_player=False, instance_id=100, species_id=3827),
    ]
    intervals = [_interval(2, 1, 100, 0, 10000)]
    awareness = {1: (0, 10000), 2: (0, 10000)}

    resolver = build_resolver(intervals, awareness, agents)

    assert resolver.owner_at(2, 5000) == 1
    assert resolver.owner_at(2, 10001) is None  # after interval


def test_resolver_owned_agents_at() -> None:
    """owned_agents_at returns all minions owned by a master at a given time."""
    agents = [
        _agent(1, "Master", account=":Master.1234", instance_id=100),
        _agent(2, "Pet1", is_player=False, instance_id=100, species_id=3827),
        _agent(3, "Pet2", is_player=False, instance_id=100, species_id=4425),
    ]
    intervals = [
        _interval(2, 1, 100, 0, 10000),
        _interval(3, 1, 100, 2000, 8000),
    ]
    awareness = {1: (0, 10000), 2: (0, 10000), 3: (2000, 8000)}

    resolver = build_resolver(intervals, awareness, agents)

    # Early: only pet1
    assert set(resolver.owned_agents_at(1, 1000)) == {2}
    # Mid: both pets
    assert set(resolver.owned_agents_at(1, 5000)) == {2, 3}
    # Late: only pet1 (pet2 despawned)
    assert set(resolver.owned_agents_at(1, 9000)) == {2}


def test_resolver_agent_identity_at() -> None:
    """agent_identity_at resolves full identity including owner."""
    agents = [
        _agent(
            1,
            "Master",
            account=":Master.1234",
            instance_id=100,
            profession=Profession.GUARDIAN,
            elite=EliteSpec.DRAGONHUNTER,
        ),
        _agent(2, "Pet", is_player=False, instance_id=100, species_id=3827),
    ]
    intervals = [_interval(2, 1, 100, 0, 10000)]
    awareness = {1: (0, 10000), 2: (0, 10000)}

    resolver = build_resolver(intervals, awareness, agents)

    ident = resolver.agent_identity_at(2, 5000)
    assert ident is not None
    assert ident.agent_id == 2
    assert ident.owner_agent_id == 1
    assert ident.owner_account == "Master.1234"
    assert ident.instance_id == 100
    assert ident.is_player is False


def test_resolver_character_swap_same_account() -> None:
    """Split account with character swap: two agents, same instance_id, different names."""
    agents = [
        _agent(
            1,
            "First Character",
            account=":Player.1234",
            instance_id=100,
            profession=Profession.NECROMANCER,
            elite=EliteSpec.RITUALIST,
        ),
        _agent(
            2,
            "Second Character",
            account=":Player.1234",
            instance_id=100,
            profession=Profession.WARRIOR,
            elite=EliteSpec.SPELLBREAKER,
        ),
    ]
    intervals: list[OwnershipInterval] = []  # players don't have ownership intervals
    awareness = {1: (0, 5000), 2: (5000, 10000)}

    resolver = build_resolver(intervals, awareness, agents)

    # First slice: first character present
    ident1 = resolver.agent_identity_at(1, 2500)
    assert ident1 is not None
    assert ident1.name == "First Character"
    assert ident1.profession == str(Profession.NECROMANCER)
    assert ident1.slice_index == 0

    # Second slice: second character present
    ident2 = resolver.agent_identity_at(2, 7500)
    assert ident2 is not None
    assert ident2.name == "Second Character"
    assert ident2.profession == str(Profession.WARRIOR)
    assert ident2.slice_index == 1


def test_resolver_instance_id_recycle() -> None:
    """Instance ID reused for different agent at different times."""
    agents = [
        _agent(1, "Pet v1", is_player=False, instance_id=100, species_id=3827),
        _agent(2, "Pet v2", is_player=False, instance_id=100, species_id=3827),
        _agent(3, "Master", account=":Master.1234", instance_id=100),
    ]
    intervals = [
        _interval(1, 3, 100, 0, 5000),
        _interval(2, 3, 100, 5000, 10000),
    ]
    awareness = {1: (0, 5000), 2: (5000, 10000), 3: (0, 10000)}

    resolver = build_resolver(intervals, awareness, agents)

    # First interval: pet v1 owned by master
    assert resolver.owner_at(1, 2500) == 3
    assert resolver.instance_recycle_count(100) == 2

    # Recycled interval: pet v2 owned by same master
    assert resolver.owner_at(2, 7500) == 3

    # Instance history shows both agents
    history = resolver.instance_agents(100)
    assert history == [(1, 0, 5000), (2, 5000, 10000)]


def test_resolver_mid_slice_pet_despawn_respawn() -> None:
    """Pet despawns and respawns within a single player slice."""
    agents = [
        _agent(1, "Master", account=":Master.1234", instance_id=100),
        _agent(2, "Pet", is_player=False, instance_id=100, species_id=3827),
    ]
    # Two ownership intervals for same agent (despawn + respawn)
    intervals = [
        _interval(2, 1, 100, 0, 3000),
        _interval(2, 1, 100, 4000, 10000),
    ]
    awareness = {1: (0, 10000), 2: (0, 10000)}

    resolver = build_resolver(intervals, awareness, agents)

    # Slice midpoint at 5000: pet is owned (second interval)
    mid = 5000
    owned = resolver.owned_agents_at(1, mid)
    assert owned == [2]

    # Ownership interval at midpoint
    iv = resolver.ownership_interval_at(2, mid)
    assert iv is not None
    assert iv.start_ms == 4000
    assert iv.end_ms == 10000


def test_resolver_is_present_at() -> None:
    """is_present_at respects agent_awareness bounds."""
    agents = [_agent(1, "Player", account=":Player.1234", instance_id=100)]
    intervals: list[OwnershipInterval] = []
    awareness = {1: (1000, 9000)}  # joins late, leaves early

    resolver = build_resolver(intervals, awareness, agents)

    assert resolver.is_present_at(1, 0) is False
    assert resolver.is_present_at(1, 5000) is True
    assert resolver.is_present_at(1, 10000) is False


def test_resolver_slice_owner_account() -> None:
    """slice_owner_account returns owner's account during player slice."""
    agents = [
        _agent(1, "Master", account=":Master.1234", instance_id=100),
        _agent(2, "Pet", is_player=False, instance_id=100, species_id=3827),
    ]
    intervals = [_interval(2, 1, 100, 0, 10000)]
    awareness = {1: (0, 10000), 2: (0, 10000)}

    resolver = build_resolver(intervals, awareness, agents)

    # Slice covers the whole interval
    assert resolver.slice_owner_account(2, 0, 10000) == "Master.1234"

    # Slice outside ownership
    assert resolver.slice_owner_account(2, 10001, 20000) is None


def test_resolver_anonymous_enemy_player() -> None:
    """Anonymous enemy player (no account_name) resolved by instance_id."""
    agents = [
        _agent(1, "Non Squad Player", account="Non Squad Player 5", instance_id=100),
        _agent(2, "Enemy", account=None, instance_id=100, is_player=False, species_id=8111),
    ]
    intervals: list[OwnershipInterval] = []
    awareness = {1: (0, 10000), 2: (0, 10000)}

    resolver = build_resolver(intervals, awareness, agents)

    # Agent with no account_name but matching instance_id
    ident = resolver.agent_identity_at(2, 5000)
    assert ident is not None
    assert ident.account is None
    assert ident.instance_id == 100
    assert ident.is_player is False
