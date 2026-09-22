"""Tests for TemporalIdentityResolver (CAP-4 / Story 3)."""

from __future__ import annotations

import struct

from gw2_analytics.temporal_identity import (
    OwnershipInterval,
    build_resolver,
)
from gw2_core import (
    Agent,
    EliteSpec,
    Profession,
)
from gw2_evtc_parser import PythonEvtcParser, scan_agent_awareness, scan_ownership_intervals


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


def test_resolver_distinguishes_temporal_owner_from_final_master() -> None:
    agents = [
        _agent(1, "Root", instance_id=10),
        _agent(2, "Middle", is_player=False, instance_id=20),
        _agent(3, "Leaf", is_player=False, instance_id=30),
    ]
    intervals = [
        OwnershipInterval(
            agent_id=3,
            owner_agent_id=None,
            instance_id=30,
            species_id=1,
            start_ms=0,
            end_ms=100,
            is_player=False,
        ),
        OwnershipInterval(
            agent_id=3,
            owner_agent_id=2,
            instance_id=30,
            species_id=1,
            start_ms=100,
            end_ms=1000,
            is_player=False,
            final_master_agent_id=1,
            master_evidence="resolved",
        ),
    ]
    resolver = build_resolver(intervals, {1: (0, 1000), 2: (0, 1000), 3: (0, 1000)}, agents)

    assert resolver.owner_at(3, 50) is None
    # EI's final-master projection may use the later link for the early spawn;
    # owner_at remains strictly timestamp-bounded.
    assert resolver.final_master_at(3, 50) == 1
    assert resolver.owner_at(3, 500) == 2
    assert resolver.final_master_at(3, 500) == 1


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


# ---------------------------------------------------------------------------
# End-to-end: real EVTC2025 struct packing → scanner → resolver
# ---------------------------------------------------------------------------


def _evtc_2025_byte_layout_log(
    agents: list[tuple[int, int, int, str, str | None, bool]],
    events: list[bytes],
) -> bytes:
    """Build a minimal EVTC2025 log with the REAL wire layouts.

    Agent tuples are ``(id, profession_id, elite_id, name, account, is_player)``.
    Event bytes are pre-packed 64-byte ``<QQQiiIIHHHH16B`` cbtevent records
    with master instids at the true byte positions (44-45/46-47).
    """
    header = struct.pack(
        "<4s8sBHBI",
        b"EVTC",
        b"20250925",
        0,
        0,
        0,
        len(agents),
    )
    blob = bytearray(header)
    for agent_id, prof, elite, name, account, _is_player in agents:
        raw = name.encode("utf-8") + b"\x00"
        if account is not None:
            raw += account.encode("utf-8") + b"\x00\x00"
        name_buf = raw + b"\x00" * (68 - len(raw))
        blob += struct.pack("<QII6H68s", agent_id, prof, elite, 0, 0, 0, 0, 0, 0, name_buf)
    blob += b"".join(events)
    return bytes(blob)


def _evtc_2025_event(
    time_ms: int,
    src_agent: int,
    dst_agent: int,
    *,
    is_statechange: int = 0,
    iff: int = 1,
    src_inst: int = 0,
    dst_inst: int = 0,
    src_master_instid: int = 0,
) -> bytes:
    flags = bytearray(16)
    flags[0] = iff
    flags[8] = is_statechange
    return struct.pack(
        "<QQQiiIIHHHH16B",
        time_ms,
        src_agent,
        dst_agent,
        0,
        0,
        0,
        42,
        src_inst,
        dst_inst,
        src_master_instid,
        0,
        *flags,
    )


def test_resolver_owner_at_across_master_change_end_to_end() -> None:
    """owner_at flips master at the transition, from REAL EVTC2025 bytes.

    The full pipeline — EVTC2025 struct packing (master instids at the
    true tuple positions 9/10) → ``scan_ownership_intervals`` →
    ``build_resolver`` — must return owner A before the transition and
    owner B after it. Under the pre-repair implementation (indices 14/15,
    empty ``instance_to_agent``) every ``owner_at`` query returned None.
    """
    blob = _evtc_2025_byte_layout_log(
        [
            (1, Profession.NECROMANCER.value, EliteSpec.HARBINGER.value,
             "Master A", ":A.1111", True),
            (2, 0, 0, "Spirit Weapon", None, False),
            (3, Profession.RANGER.value, EliteSpec.DRUID.value,
             "Master B", ":B.2222", True),
        ],
        [
            # Spawn owned by master A at fight-relative 0.
            _evtc_2025_event(
                42_500,
                2,
                1,
                is_statechange=6,
                src_inst=11,
                dst_inst=10,
                src_master_instid=10,
            ),
            # Master change at fight-relative 2_500.
            _evtc_2025_event(
                45_000,
                2,
                3,
                src_inst=11,
                dst_inst=20,
                src_master_instid=20,
            ),
            # Log ends at 12_000 fight-relative.
            _evtc_2025_event(54_500, 2, 1, src_inst=11),
        ],
    )

    intervals = scan_ownership_intervals(blob)
    fight = next(PythonEvtcParser().parse(blob))
    resolver = build_resolver(intervals, scan_agent_awareness(blob), fight.agents)

    # Owner A before the transition, owner B after it.
    assert resolver.owner_at(2, 1_000) == 1
    assert resolver.owner_at(2, 3_000) == 3
    # Identity carries the owner's account through the resolver.
    ident_before = resolver.agent_identity_at(2, 1_000)
    ident_after = resolver.agent_identity_at(2, 3_000)
    assert ident_before is not None and ident_after is not None
    assert ident_before.owner_agent_id == 1
    assert ident_before.owner_account == "A.1111"
    assert ident_after.owner_agent_id == 3
    assert ident_after.owner_account == "B.2222"
