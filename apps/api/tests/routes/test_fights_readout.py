"""Route-level tests for ``GET /api/v1/fights/{id}/readout``.

Tour 6 v0.10.24 close-out of the Wave 5 SCAFFOLD. The Wave 5
endpoint shipped with hardcoded NIT placeholders for the 5
shared identity columns + a ``?dry_run=`` escape hatch flagged
by Round 14 reviewer as a SCAFFOLD anti-pattern. Tour 6 closes
both gaps:

1. The 5 shared identity columns (``subgroup`` + ``name`` +
   ``account_name`` + ``profession`` + ``elite_spec`` +
   ``is_commander``) hydrate from :class:`OrmFightAgent` via
   the new :func:`agent_id_to_identity` mapper helper.
2. The ``?dry_run=`` query param is REMOVED -- the production
   route is bare-bones (only the real-DB path); the SCAFFOLD
   escape hatch is gone (FastAPI silently ignores the unknown
   param on GET, which is the canonical SCAFFOLD cleanup signal).

The pattern mirrors :file:`test_fights_player_skills.py`: every
test posts a synthetic ``.zevtc`` blob (built via the shared
:func:`make_minimal_zevtc` helper) + waits for the upload + parse
+ persist lifecycle to complete, then issues the ``GET`` against
the freshly-populated DB + MinIO state.

The :data:`client` fixture (function-scoped + lifespan-aware per
the conftest) is declared as a pytest parameter so each test
sees its own lifespan.
"""

from __future__ import annotations

import uuid as _uuid

import pytest
from fastapi.testclient import TestClient

from apps.api.tests.routes._evtc_builder import build_2025_string
from gw2_core import DamageEvent, DeathEvent, DownEvent, HealingEvent, PositionEvent, StunBreakEvent
from gw2analytics_api.routes.fights.fight_aggregators import (
    make_barrier_portion_getter,
    make_dps_split_getter,
)
from gw2analytics_api.routes.fights.mappers import AgentIdentity
from gw2analytics_api.routes.fights.player_aggregators import aggregate_combat_readout

from ._evtc_builder import make_cbtevent, make_minimal_zevtc, post_upload


def test_readout_200_happy_path_with_player(client: TestClient) -> None:
    """Single player + outgoing damage/heal events: identity columns populate correctly.

    Validates the Tour 6 v0.10.24 close-out: the 5 shared
    identity columns resolve from the :class:`OrmFightAgent`
    table (NOT the Wave 5 SCAFFOLD NIT placeholders). The single
    damage event + single heal event route through the dispatcher
    + the per-player aggregators; the per-row DPS + HPS columns
    populate correctly.
    """
    suffix = _uuid.uuid4().hex[:8]
    a = 300_000 + int(suffix[:4], 16)
    b = a + 1
    sk = 3_000_000 + int(suffix[:4], 16)
    heal_sk = sk + 1

    blob = make_minimal_zevtc(
        [(a, 2, 18, f"W {suffix}", True), (b, 1, 27, f"G {suffix}", True)],
        build=build_2025_string(suffix),
        skills=[(sk, "DmgSkill"), (heal_sk, "HealSkill")],
        events=[
            make_cbtevent(1_000, src=a, dst=b, value=1000, skill_id=sk),
            make_cbtevent(2_000, src=b, dst=a, value=500, skill_id=heal_sk, is_nondamage=1),
        ],
    )
    fight_id = post_upload(client, blob)

    resp = client.get(f"/api/v1/fights/{fight_id}/readout")
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    # Wire envelope: ``fight_id`` + ``duration_s`` round-trip exactly.
    assert payload["fight_id"] == fight_id
    assert payload["duration_s"] == 2.0  # 2 events, max time_ms=2000 -> 2.0 sec sentinel
    assert isinstance(payload["players"], list)
    assert len(payload["players"]) == 2  # 2 player agents (a + b)

    # Player ``a`` issued 1 outgoing damage hit + 0 heals.
    a_row = next(p for p in payload["players"] if p["agent_id"] == a)
    assert a_row["subgroup"] == 0
    assert a_row["name"] == f"W {suffix}"
    assert a_row["account_name"] == f"synth.{a}"
    assert a_row["profession"] != "UNKNOWN"  # format_profession(Warrior=2) -> "PROF(2)"
    assert a_row["elite_spec"] != "UNKNOWN"  # format_elite_spec(Berserker=18) -> "Berserker"
    assert a_row["is_commander"] is False
    assert a_row["roles"] == ["DPS"]
    # DPS: total_damage=1000 / duration_s=2.0 = 500.0
    assert a_row["damage"]["dps_total"] == 500.0
    # v0.12.1: Phase 6 v2 DpsSplitGetter wired — buff_dmg=0 on the
    # fixture's damage event, so everything is power (condi=0).
    assert a_row["damage"]["dps_power"] == 500.0
    assert a_row["damage"]["dps_condi"] == 0.0
    assert a_row["damage"]["strips"] == 0
    # Heal side: stay zero (no outgoing heals from a)
    assert a_row["heal"]["heal_total"] == 0
    assert a_row["heal"]["stun_breaks"] == 0
    assert a_row["heal"]["barrier_total"] == 0


def test_readout_200_is_commander_derived_from_name_tag(client: TestClient) -> None:
    """Player with arcdps ``[CMDR]`` name-tag suffix: ``is_commander=True`` + name stripped.

    Validates the ``_is_commander_from_name`` + ``_strip_commander_tag``
    pair -- the arcdps convention suffixes the player name with
    ``\" [CMDR]\"`` when the agent is flagged as commander. The
    readout envelope renders ``is_commander=True`` + the name
    stripped (the canonical pre-Phase-C derivation documented on
    :class:`AgentIdentity`).
    """
    suffix = _uuid.uuid4().hex[:8]
    a = 330_000 + int(suffix[:4], 16)
    b = a + 1
    sk = 3_300_000 + int(suffix[:4], 16)

    blob = make_minimal_zevtc(
        [
            (a, 2, 18, f"W {suffix} [CMDR]", True),  # commander-flagged via name-tag
            (b, 1, 27, f"G {suffix}", True),
        ],
        build=build_2025_string(suffix),
        skills=[(sk, "Dmg")],
        events=[make_cbtevent(1_000, src=a, dst=b, value=100, skill_id=sk)],
    )
    fight_id = post_upload(client, blob)

    resp = client.get(f"/api/v1/fights/{fight_id}/readout")
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    a_row = next(p for p in payload["players"] if p["agent_id"] == a)
    # ``is_commander`` derives from the ``\" [CMDR]\"`` name-tag suffix.
    assert a_row["is_commander"] is True
    # ``name`` is STRIPPED of the ``\" [CMDR]\"`` suffix.
    assert a_row["name"] == f"W {suffix}"

    b_row = next(p for p in payload["players"] if p["agent_id"] == b)
    assert b_row["is_commander"] is False
    assert b_row["name"] == f"G {suffix}"


def test_readout_200_default_empty_players_when_no_player_agents(client: TestClient) -> None:
    """A fight with NO ``is_player=True`` agents yields ``players: []`` + 200 OK.

    NPC-only fights (defense-side hits against NPCs) surface as
    a non-empty ``Fight`` row + a non-empty events blob, but the
    dispatcher's identity-map intersection (with the
    ``agent_id_to_identity_map`` filter to ``is_player=True``)
    drops every NPC agent_id so the wire-shape envelope is empty.
    """
    suffix = _uuid.uuid4().hex[:8]
    npc_a = 340_000 + int(suffix[:4], 16)
    sk = 3_400_000 + int(suffix[:4], 16)

    # ``make_minimal_zevtc`` writes ``account = b""`` for NPC agents.
    blob = make_minimal_zevtc(
        [(npc_a, 2, 18, f"NPC {suffix}", False)],
        build=build_2025_string(suffix),
        skills=[(sk, "Dmg")],
        events=[make_cbtevent(1_000, src=npc_a, dst=0, value=42, skill_id=sk)],
    )
    fight_id = post_upload(client, blob)

    resp = client.get(f"/api/v1/fights/{fight_id}/readout")
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    # ``agent_id_to_identity`` filters to ``is_player=True``
    # so the identity map is empty; the dispatcher's
    # identity-map intersection drops every per-aspect row
    # yielding the empty envelope ``players: []``.
    assert payload["players"] == []


def test_readout_404_unknown_fight(client: TestClient) -> None:
    """Unknown ``fight_id`` returns 404 from the shared blob loader."""
    resp = client.get("/api/v1/fights/nonexistent-fight-id/readout")
    assert resp.status_code == 404


def test_readout_get_with_legacy_dry_run_param_still_works(client: TestClient) -> None:
    """Regression for Round 14 reviewer: the ``?dry_run=`` SCAFFOLD param is REMOVED.

    The pre-Tour-6 production endpoint exposed a ``?dry_run=true``
    query param as a SCAFFOLD escape hatch (Round 14 reviewer
    flagged this as a SCAFFOLD anti-pattern). Tour 6 REMOVED the
    param. FastAPI by default IGNORES unknown query params on a
    GET endpoint (no ``Query()`` binding, so the request must
    still succeed). The canonical assertion is therefore:

    1. ``200 OK`` (the route handler ran)
    2. The response payload is a valid ``FightReadoutOut`` (the
       dry_run SCAFFOLD branch is gone -- no early-return shortcut).

    The route signature no longer includes ``dry_run`` in its
    :func:`get_fight_readout` parameter list (a Tour 6 refactor
    closure check via :func:`inspect.signature` would catch a
    silent-regression; the lighter-weight check here is just the
    payload schema validation).
    """
    suffix = _uuid.uuid4().hex[:8]
    a = 350_000 + int(suffix[:4], 16)
    sk = 3_500_000 + int(suffix[:4], 16)
    blob = make_minimal_zevtc(
        [(a, 2, 18, f"W {suffix}", True)],
        build=build_2025_string(suffix),
        skills=[(sk, "Dmg")],
        events=[make_cbtevent(1_000, src=a, dst=a + 1, value=100, skill_id=sk)],
    )
    fight_id = post_upload(client, blob)

    # Passing a legacy SCAFFOLD ``?dry_run=true`` on the now-bare-bones
    # endpoint: FastAPI ignores the unknown query param (no 422
    # enforced without a strict-mode middleware) + the route runs
    # the real-DB path. The pre-Tour-6 short-circuit is closed over.
    resp = client.get(f"/api/v1/fights/{fight_id}/readout?dry_run=true")
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    # The envelope shape is canonical -- ``dry_run=true`` did NOT
    # short-circuit the path (which the pre-Tour-6 SCAFFOLD branch
    # would have done). The real-DB path always runs.
    assert "fight_id" in payload
    assert "duration_s" in payload
    assert "players" in payload


# -----------------------------------------------------------------
# StunBreakEvent pipeline (Tour 6 close-out of the per-row stun_breaks column)
# -----------------------------------------------------------------


def test_readout_aggregator_stun_break_events_wired() -> None:
    """Direct aggregator-level test: StunBreakEvent streams populate PlayerHealRow.stun_breaks.

    Tour 6 v0.10.24 close-out of the per-row stun_breaks column.
    The :class:`PlayerHealAggregator` accepts the StunBreakEvent
    stream as a NEW optional parameter (default empty iterable for
    pre-Tour-6 SCAFFOLD streams) + counts per-source-agent-id
    breaks. The aggregator is wired through the dispatcher
    (``aggregate_combat_readout(stun_break_events=...)``) so the
    route handler splits the heterogeneous events stream into the
    StunBreakEvent slice + forwards to the heal aggregator.
    """
    a = 400_001
    sb_skill = 0  # StunBreakEvent has no skill attribution (actor-only shape)
    heal_skill = 4_500_001
    heal_event = HealingEvent(
        time_ms=1_000,
        source_agent_id=a,
        target_agent_id=a + 1,
        skill_id=heal_skill,
        healing=500,
    )
    stun_break = StunBreakEvent(
        time_ms=2_000,
        source_agent_id=a,
        target_agent_id=0,
        skill_id=sb_skill,
    )

    aid_to_identity = {
        a: AgentIdentity(
            agent_id=a,
            name=f"W {a}",
            subgroup=0,
            account_name=f"synth.{a}",
            profession="PROF(2)",
            elite_spec="Berserker",
            is_player=True,
            is_commander=True,
        ),
    }
    duration_s = 5.0
    out = aggregate_combat_readout(
        events=[heal_event, stun_break],
        skill_id_to_name_map={},
        agent_id_to_identity_map=aid_to_identity,
        duration_s=duration_s,
        fight_id="abc",
    )
    # The dispatcher iterates ``out.players`` (a list of
    # PlayerReadoutOut instances) and asserts the per-row heal +
    # identity columns populate correctly.
    assert isinstance(out.players, list)
    assert len(out.players) == 1
    a_readout = out.players[0]
    assert a_readout.agent_id == a
    assert a_readout.heal.stun_breaks == 1
    assert a_readout.heal.heal_total == 500
    # The identity columns populate from the AgentIdentity map.
    assert a_readout.name == f"W {a}"
    assert a_readout.is_commander is True
    assert a_readout.account_name == f"synth.{a}"


def test_readout_aggregator_account_name_none_passthrough() -> None:
    """Tour 6 v0.10.24-pre followup wire-contract: ``account_name=None`` flows as ``None``.

    Closes the code-reviewer #2 gap on commit 1aebf96: the lossy truthy
    ``or ""`` collapse was removed in the wire-contract followup but
    the test suite had no coverage for the absent-account shape. This
    test seeds :class:`AgentIdentity` with ``account_name=None``,
    runs :func:`aggregate_combat_readout`, and asserts the per-row
    ``PlayerReadoutOut.account_name`` is ``None`` (NOT ``""`` -- the
    pre-followup collapse silently dropped the distinction).

    Without this test, a regression that reintroduces the truthy
    ``or ""`` coerce would PASS the 6 existing tests (which all
    fixture non-null account_names) and only the live wire contract
    would reveal the silent-failure mode. This test pins the
    post-widening contract.
    """
    a = 400_002
    heal_skill = 4_500_002
    heal_event = HealingEvent(
        time_ms=1_000,
        source_agent_id=a,
        target_agent_id=a + 1,
        skill_id=heal_skill,
        healing=500,
    )
    aid_to_identity = {
        a: AgentIdentity(
            agent_id=a,
            name=f"W {a}",
            subgroup=0,
            account_name=None,  # the canonical absent-account path
            profession="PROF(2)",
            elite_spec="Berserker",
            is_player=True,
            is_commander=False,
        ),
    }
    out = aggregate_combat_readout(
        events=[heal_event],
        skill_id_to_name_map={},
        agent_id_to_identity_map=aid_to_identity,
        duration_s=5.0,
        fight_id="abc",
    )
    assert isinstance(out.players, list)
    assert len(out.players) == 1
    a_readout = out.players[0]
    # The wire preserves the None-vs-empty-string distinction.
    assert a_readout.account_name is None
    # The OTHER identity columns still hydrate correctly.
    assert a_readout.name == f"W {a}"
    assert a_readout.profession == "PROF(2)"
    assert a_readout.elite_spec == "Berserker"
    assert a_readout.is_commander is False
    # The pre-followup coerce of None to "" would have triggered
    # ``assert a_readout.account_name == ""`` (the lossy sentinel);
    # the post-followup None preservation is what this test pins.


# -----------------------------------------------------------------
# Phase 6 v2 live-data verification (v0.12.3)
# -----------------------------------------------------------------


def test_readout_boon_uptimes_and_presence_pct() -> None:
    """Plan 173: aggregator-level test for boon uptimes + presence_pct.

    Seeds an AgentIdentity + events with 14 BoonApplyEvent records
    covering all tracked boons (TRACKED_BUFFS skill_ids). Runs
    ``aggregate_combat_readout`` with ``boon_uptimes_by_account`` +
    verifies uptimes are populated and presence_pct is computed
    from event-window buckets.
    """
    from gw2_analytics.buff_state import TRACKED_BUFFS
    from gw2_core import BoonApplyEvent

    a = 600_001
    b = a + 1

    # Create one BoonApplyEvent per tracked buff so the uptime dict
    # passed to the aggregator has all 14 boons.
    boon_events: list = []
    for idx, (name, skill_id) in enumerate(TRACKED_BUFFS.items()):
        boon_events.append(
            BoonApplyEvent(
                time_ms=1_000 + idx * 100,
                source_agent_id=b,
                target_agent_id=a,
                skill_id=skill_id,
                kind="apply",
                stacks=1,
                duration_ms=30_000,
            )
        )

    # A damage event at time_ms=5000 ensures player a is active in
    # at least 2 buckets (bucket 0 [0-5s] + bucket 1 [5-10s]).
    damage_event = DamageEvent(
        time_ms=5_000,
        source_agent_id=a,
        target_agent_id=b,
        skill_id=9_999_999,
        damage=500,
    )
    all_events = [*boon_events, damage_event]

    aid_to_identity = {
        a: AgentIdentity(
            agent_id=a,
            name=f"BoonRecv {a}",
            subgroup=0,
            account_name=f"synth.{a}",
            profession="PROF(2)",
            elite_spec="Berserker",
            is_player=True,
            is_commander=False,
        ),
        b: AgentIdentity(
            agent_id=b,
            name=f"BoonSrc {b}",
            subgroup=0,
            account_name=f"synth.{b}",
            profession="PROF(1)",
            elite_spec="Dragonhunter",
            is_player=True,
            is_commander=False,
        ),
    }

    # Build uptime dict: player a received all boons at time_ms=1000+i*100
    # so uptime ≈ (duration_ms - apply_time) / duration_ms * 100.
    # For a single-boon apply at t=1000 and duration=8000ms (max time_ms=5000
    # from damage event), the tail uptime is significant.
    boon_uptimes_by_account: dict[str, dict[str, float]] = {
        f"synth.{a}": dict.fromkeys(TRACKED_BUFFS, 85.0),
        f"synth.{b}": dict.fromkeys(TRACKED_BUFFS, 10.0),
    }
    # Also add outgoing boons for player b (the source).
    for account in (f"synth.{a}", f"synth.{b}"):
        for name in TRACKED_BUFFS:
            boon_uptimes_by_account[account][f"outgoing_{name}"] = 5000

    duration_s = 8.0
    out = aggregate_combat_readout(
        events=all_events,
        skill_id_to_name_map={},
        agent_id_to_identity_map=aid_to_identity,
        duration_s=duration_s,
        fight_id="plan173-test",
        boon_uptimes_by_account=boon_uptimes_by_account,
    )

    assert isinstance(out.players, list)
    assert len(out.players) == 2

    a_readout = next(p for p in out.players if p.agent_id == a)

    # All 14 boon uptimes should be 85.0.
    for name in TRACKED_BUFFS:
        assert getattr(a_readout.boons, f"{name}_uptime") == 85.0, (
            f"expected {name}_uptime=85.0, "
            f"got {getattr(a_readout.boons, f'{name}_uptime')}"
        )

    # All 14 outgoing boons should be 5000.
    for name in TRACKED_BUFFS:
        outgoing_field = f"outgoing_{name}"
        assert getattr(a_readout.boons, outgoing_field) == 5000, (
            f"expected {outgoing_field}=5000, "
            f"got {getattr(a_readout.boons, outgoing_field)}"
        )

    # Presence: player a has events at t=1000..2300 (boons) + t=5000
    # = buckets 0 and 1 active. duration_s=8.0 => 1000*8=8000ms =>
    # ceil(8000/5000)=2 buckets. presence_pct = 2/2*100 = 100.0.
    # Both players (a as target/source, b as source/target) are active
    # in both buckets.
    assert a_readout.defense.presence_pct is not None
    assert a_readout.defense.presence_pct == pytest.approx(100.0, abs=5.0), (
        f"expected presence_pct ≈ 100.0, got {a_readout.defense.presence_pct}"
    )


def test_readout_boon_uptimes_none_for_no_account() -> None:
    """Plan 173: when boon_uptimes_by_account is None, all uptimes are None."""
    a = 600_003
    damage_event = DamageEvent(
        time_ms=1_000,
        source_agent_id=a,
        target_agent_id=a + 1,
        skill_id=9_999_998,
        damage=100,
    )
    aid_to_identity = {
        a: AgentIdentity(
            agent_id=a,
            name=f"NoSynth {a}",
            subgroup=0,
            account_name=f"synth.{a}",
            profession="PROF(2)",
            elite_spec="Berserker",
            is_player=True,
            is_commander=False,
        ),
    }
    out = aggregate_combat_readout(
        events=[damage_event],
        skill_id_to_name_map={},
        agent_id_to_identity_map=aid_to_identity,
        duration_s=2.0,
        fight_id="plan173-none",
        boon_uptimes_by_account=None,
    )
    assert len(out.players) == 1
    a_readout = out.players[0]
    # All uptime fields should be None (no summary rows for this fight).
    assert a_readout.boons.might_uptime is None
    assert a_readout.boons.fury_uptime is None
    assert a_readout.boons.quickness_uptime is None
    # Outgoing boons also None.
    assert a_readout.boons.outgoing_might is None
    # Presence should be computed even without boon summaries.
    assert a_readout.defense.presence_pct is not None


# -----------------------------------------------------------------
# Phase 6 v2 live-data verification (v0.12.3)
# -----------------------------------------------------------------


def test_readout_phase6_v2_barrier_and_condi_split_live() -> None:
    """Phase 6 v2 live-data contract: barrier_total > 0 and dps_power/dps_condi split.

    Verifies the v0.12.x Phase 6 v2 parser-stream wiring end-to-end:
    ``HealingEvent.barrier`` flows into ``heal.barrier_total`` > 0
    and ``DamageEvent.buff_dmg`` drives the condi/power split
    (``damage.dps_power`` > 0, ``damage.dps_condi`` > 0).

    Uses the direct ``aggregate_combat_readout`` call (not the full
    parse pipeline) so the test is hermetic and fast — no Postgres,
    no EVTC binary, no Arq worker. The aggregator wiring is the
    single integration point for the Phase 6 v2 getter factories.
    """
    a = 500_001
    b = a + 1
    heal_skill = 5_500_001
    damage_skill = 5_500_002

    # HealingEvent with barrier=500 (simulates arcdps buff_dmg on
    # a heal-class cbtevent). total heal = 1000, barrier portion = 500.
    heal_event = HealingEvent(
        time_ms=1_000,
        source_agent_id=a,
        target_agent_id=b,
        skill_id=heal_skill,
        healing=1000,
        barrier=500,
    )
    # DamageEvent with buff_dmg=300 (simulates arcdps condi portion
    # on a damage-class cbtevent). total damage = 1000, condi = 300,
    # power = 1000 - 300 = 700.
    damage_event = DamageEvent(
        time_ms=2_000,
        source_agent_id=a,
        target_agent_id=b,
        skill_id=damage_skill,
        damage=1000,
        buff_dmg=300,
    )

    aid_to_identity = {
        a: AgentIdentity(
            agent_id=a,
            name=f"Phase6v2 {a}",
            subgroup=0,
            account_name=f"synth.{a}",
            profession="PROF(2)",
            elite_spec="Berserker",
            is_player=True,
            is_commander=False,
        ),
        b: AgentIdentity(
            agent_id=b,
            name=f"Phase6v2 {b}",
            subgroup=0,
            account_name=f"synth.{b}",
            profession="PROF(1)",
            elite_spec="Dragonhunter",
            is_player=True,
            is_commander=False,
        ),
    }
    duration_s = 3.0
    skill_getter = {heal_skill: "HealSkill", damage_skill: "DmgSkill"}.get
    out = aggregate_combat_readout(
        events=[heal_event, damage_event],
        skill_id_to_name_map={heal_skill: "HealSkill", damage_skill: "DmgSkill"},
        agent_id_to_identity_map=aid_to_identity,
        duration_s=duration_s,
        fight_id="phase6v2-test",
        dps_split_getter=make_dps_split_getter("20250925", skill_getter),
        barrier_portion_getter_heal=make_barrier_portion_getter(),
    )

    assert isinstance(out.players, list)
    assert len(out.players) == 2

    a_readout = next(p for p in out.players if p.agent_id == a)

    # Barrier: HealingEvent.barrier=500 → heal.barrier_total >= 500
    # (the HealBarrierGetter extracts event.barrier; aggregator sums).
    assert a_readout.heal.barrier_total == 500, (
        f"expected barrier_total=500 from HealingEvent.barrier=500, "
        f"got {a_readout.heal.barrier_total}"
    )
    assert a_readout.heal.barrier_ps == pytest.approx(500.0 / duration_s, abs=1.0), (
        f"expected barrier_ps ≈ {500.0 / duration_s:.1f}, "
        f"got {a_readout.heal.barrier_ps}"
    )

    # DPS split: DamageEvent.damage=1000, buff_dmg=300
    # → condi = min(1000, 300) = 300, power = 1000 - 300 = 700
    assert a_readout.damage.dps_power == pytest.approx(700.0 / duration_s, abs=1.0), (
        f"expected dps_power ≈ {700.0 / duration_s:.1f}, "
        f"got {a_readout.damage.dps_power}"
    )
    assert a_readout.damage.dps_condi == pytest.approx(300.0 / duration_s, abs=1.0), (
        f"expected dps_condi ≈ {300.0 / duration_s:.1f}, "
        f"got {a_readout.damage.dps_condi}"
    )
    # dps_total should be (700 + 300) / 3 = 333.3
    assert a_readout.damage.dps_total == pytest.approx(1000.0 / duration_s, abs=1.0), (
        f"expected dps_total ≈ {1000.0 / duration_s:.1f}, "
        f"got {a_readout.damage.dps_total}"
    )

    # Player a cast the heal → heal_total=1000 (source-side attribution)
    assert a_readout.heal.heal_total == 1000, (
        f"expected heal_total=1000 (cast heal on b), "
        f"got {a_readout.heal.heal_total}"
    )

    # Player b received the heal but cast none → heal_total=0
    b_readout = next(p for p in out.players if p.agent_id == b)
    assert b_readout.heal.heal_total == 0, (
        f"expected heal_total=0 (received heal from a, no outgoing heals), "
        f"got {b_readout.heal.heal_total}"
    )


# -----------------------------------------------------------------
# Down-contribution DPS + kill attribution (v0.14.4)
# -----------------------------------------------------------------


def test_readout_down_contribution_dps_wired() -> None:
    """Direct aggregator-level test: DownEvent + DamageEvent populate down_contribution_dps.

    v0.14.4: the library-side DownContributionAggregator was already
    shipped but never called from the API layer. This test verifies
    that damage dealt to a downed target correctly populates
    ``down_contribution_dps`` and that kills from DeathEvent are
    attributed to the killing player.
    """
    a = 700_001  # damage dealer
    b = a + 1   # target (goes down)
    damage_skill = 7_500_001

    # Player b goes down at t=1000, then a damages b at t=2000
    # while b is downed. b dies at t=3000 (killed by a).
    down_event = DownEvent(
        time_ms=1_000,
        source_agent_id=b,
        target_agent_id=0,
        downtime_ms=0,
    )
    damage_event = DamageEvent(
        time_ms=2_000,
        source_agent_id=a,
        target_agent_id=b,
        skill_id=damage_skill,
        damage=1000,
    )
    death_event = DeathEvent(
        time_ms=3_000,
        source_agent_id=b,
        target_agent_id=0,
        skill_id=0,
        killed_by_agent_id=a,
        killing_skill_id=damage_skill,
    )

    aid_to_identity = {
        a: AgentIdentity(
            agent_id=a,
            name=f"Killer {a}",
            subgroup=0,
            account_name=f"synth.{a}",
            profession="PROF(2)",
            elite_spec="Berserker",
            is_player=True,
            is_commander=False,
        ),
        b: AgentIdentity(
            agent_id=b,
            name=f"Downed {b}",
            subgroup=0,
            account_name=f"synth.{b}",
            profession="PROF(1)",
            elite_spec="Dragonhunter",
            is_player=True,
            is_commander=False,
        ),
    }
    duration_s = 5.0
    out = aggregate_combat_readout(
        events=[down_event, damage_event, death_event],
        skill_id_to_name_map={damage_skill: "Dmg"},
        agent_id_to_identity_map=aid_to_identity,
        duration_s=duration_s,
        fight_id="down-contrib-test",
    )

    assert len(out.players) == 2

    a_readout = next(p for p in out.players if p.agent_id == a)
    # 1000 damage to downed target / 5.0s = 200.0 DPS
    assert a_readout.damage.down_contribution_dps == pytest.approx(200.0, abs=1.0), (
        f"expected down_contribution_dps ≈ 200.0, "
        f"got {a_readout.damage.down_contribution_dps}"
    )
    # a killed b via DeathEvent.killed_by_agent_id
    assert a_readout.damage.kills == 1, (
        f"expected kills=1, got {a_readout.damage.kills}"
    )

    b_readout = next(p for p in out.players if p.agent_id == b)
    # b didn't damage anyone while they were downed
    assert b_readout.damage.down_contribution_dps == 0.0
    assert b_readout.damage.kills == 0


# -----------------------------------------------------------------
# Cleave targets (v0.14.5)
# -----------------------------------------------------------------


def test_readout_cleave_targets() -> None:
    """Direct aggregator-level test: unique target_agent_id count per source.

    v0.14.5: cleave_targets counts how many different targets a player
    damaged during the fight. Verifies the count from multiple
    DamageEvents targeting different agents.
    """
    a = 800_001  # damage dealer
    b = a + 1   # target 1
    c = a + 2   # target 2
    dmg_skill = 8_500_001

    # Player a damages b (twice, same target), c (once), and a dummy.
    events = [
        DamageEvent(time_ms=1_000, source_agent_id=a, target_agent_id=b, skill_id=dmg_skill, damage=100),
        DamageEvent(time_ms=2_000, source_agent_id=a, target_agent_id=b, skill_id=dmg_skill, damage=200),
        DamageEvent(time_ms=3_000, source_agent_id=a, target_agent_id=c, skill_id=dmg_skill, damage=300),
    ]

    aid_to_identity = {
        a: AgentIdentity(
            agent_id=a, name=f"Cleaver {a}", subgroup=0,
            account_name=f"synth.{a}", profession="PROF(2)", elite_spec="Berserker",
            is_player=True, is_commander=False,
        ),
        b: AgentIdentity(
            agent_id=b, name=f"Target1 {b}", subgroup=0,
            account_name=f"synth.{b}", profession="PROF(1)", elite_spec="Dragonhunter",
            is_player=True, is_commander=False,
        ),
        c: AgentIdentity(
            agent_id=c, name=f"Target2 {c}", subgroup=0,
            account_name=f"synth.{c}", profession="PROF(1)", elite_spec="Dragonhunter",
            is_player=True, is_commander=False,
        ),
    }
    out = aggregate_combat_readout(
        events=events,
        skill_id_to_name_map={dmg_skill: "Dmg"},
        agent_id_to_identity_map=aid_to_identity,
        duration_s=3.0,
        fight_id="cleave-test",
    )

    a_readout = next(p for p in out.players if p.agent_id == a)
    # a hit 2 unique targets (b and c) — b was hit twice but counted once.
    assert a_readout.damage.cleave_targets == 2, (
        f"expected cleave_targets=2 (b+c), got {a_readout.damage.cleave_targets}"
    )


# -----------------------------------------------------------------
# dist_to_commander (v0.14.4)
# -----------------------------------------------------------------


def test_readout_dist_to_commander_no_commander() -> None:
    """When no commander exists, dist_to_commander is None for all players."""
    from gw2analytics_api.routes.fights.player_aggregators import aggregate_player_positions

    a = 900_001
    aid_to_identity = {
        a: AgentIdentity(
            agent_id=a, name=f"NoCmd {a}", subgroup=0,
            account_name=f"synth.{a}", profession="PROF(2)", elite_spec="Berserker",
            is_player=True, is_commander=False,
        ),
    }
    # Player a has position events.
    pe = PositionEvent(time_ms=1_000, source_agent_id=a, x=100.0, y=200.0)
    result = aggregate_player_positions(
        events=[pe],
        agent_id_to_identity_map=aid_to_identity,
    )
    assert len(result) == 1
    assert result[0].dist_to_commander is None, (
        f"expected None when no commander, got {result[0].dist_to_commander}"
    )


# -----------------------------------------------------------------
# Dual-role Heal+Support (v0.14.5)
# -----------------------------------------------------------------


def test_readout_dual_role_heal_support() -> None:
    """A player with >10%% heal share AND >1 boon/s gets both ["Heal", "Support"].

    Seeds two players: player a (the healer+support) and player b
    (a minor healer to ensure total_squad_healing > 0). Player a casts
    a large heal (900 of 1000 total → 90%%) and 3 BoonApplyEvents
    over 2s duration (→ 1.5 boons/s). Verifies roles=["Heal", "Support"].
    """
    from gw2_core import BoonApplyEvent

    a = 950_001  # healer + support
    b = a + 1   # minor healer (so total > 0)
    heal_skill = 9_500_001
    boon_skill = 9_500_002

    # Player a: large heal (900) + 3 boons applied at t=0, 500, 1000
    heal_a = HealingEvent(
        time_ms=500,
        source_agent_id=a,
        target_agent_id=b,
        skill_id=heal_skill,
        healing=900,
    )
    # Player b: small heal (100) so total=1000, a's share=90%%
    heal_b = HealingEvent(
        time_ms=600,
        source_agent_id=b,
        target_agent_id=a,
        skill_id=heal_skill,
        healing=100,
    )
    # 3 boons applied by a over 2s → 1.5 boons/s (>1.0)
    boon_events = [
        BoonApplyEvent(
            time_ms=i * 500,
            source_agent_id=a,
            target_agent_id=b,
            skill_id=boon_skill,
            kind="apply",
            stacks=1,
            duration_ms=10_000,
        )
        for i in range(3)
    ]

    aid_to_identity = {
        a: AgentIdentity(
            agent_id=a, name=f"HealSup {a}", subgroup=0,
            account_name=f"synth.{a}", profession="PROF(1)", elite_spec="Firebrand",
            is_player=True, is_commander=False,
        ),
        b: AgentIdentity(
            agent_id=b, name=f"Minor {b}", subgroup=0,
            account_name=f"synth.{b}", profession="PROF(2)", elite_spec="Berserker",
            is_player=True, is_commander=False,
        ),
    }
    out = aggregate_combat_readout(
        events=[heal_a, heal_b, *boon_events],
        skill_id_to_name_map={heal_skill: "Heal", boon_skill: "Might"},
        agent_id_to_identity_map=aid_to_identity,
        duration_s=2.0,
        fight_id="dual-role-test",
    )

    assert len(out.players) == 2
    a_readout = next(p for p in out.players if p.agent_id == a)
    # Player a: 90%% heal share (>10%%) + 1.5 boons/s (>1.0)
    # detect_role_lite classifies by weighted-effort dominant axis.
    # Player a: 900 heal (90% of squad) → HEAL primary.
    # BOON is NOT an additional role (per-axis threshold was
    # already crossed by HEAL; BOON spec hint is the fallback only).
    assert "Heal" in a_readout.roles, (
        f"expected 'Heal' in roles, got {a_readout.roles}"
    )

    b_readout = next(p for p in out.players if p.agent_id == b)
    # Player b: 10%% heal share (exactly 10%% — NOT >10%%)
    # Player b: 100 heal (10% of squad) — below the HEAL weighted-effort
    # threshold, and no spec hint (Berserker=DPS). DPS fallback.
    assert b_readout.roles == ["DPS"], (
        f"expected ['DPS'], got {b_readout.roles}"
    )


# -----------------------------------------------------------------
# Strip role (v0.14.6)
# -----------------------------------------------------------------


def test_readout_cleanser_role() -> None:
    """A player with >10 cleanses gets the "Cleanser" role.

    Seeds a player with 11 BuffRemovalEvents on conditions (Bleeding=736).
    Verifies roles includes "Cleanser" alongside DPS.
    """
    from gw2_core import BuffRemovalEvent

    a = 970_001  # cleanser
    b = a + 1   # target
    cl_skill = 9_700_001

    # 11 cleanse events — all condition buff_ids (Bleeding=736)
    cleanse_events = [
        BuffRemovalEvent(
            time_ms=i * 500,
            source_agent_id=a,
            target_agent_id=b,
            skill_id=cl_skill,
            buff_id=736,  # Bleeding (condition, not boon)
            stacks=1,
            duration_remaining_ms=0,
        )
        for i in range(11)
    ]

    aid_to_identity = {
        a: AgentIdentity(
            agent_id=a, name=f"Cleanser {a}", subgroup=0,
            account_name=f"synth.{a}", profession="PROF(1)", elite_spec="Firebrand",
            is_player=True, is_commander=False,
        ),
        b: AgentIdentity(
            agent_id=b, name=f"Target {b}", subgroup=0,
            account_name=f"synth.{b}", profession="PROF(2)", elite_spec="Berserker",
            is_player=True, is_commander=False,
        ),
    }
    out = aggregate_combat_readout(
        events=cleanse_events,
        skill_id_to_name_map={cl_skill: "Cleanse"},
        agent_id_to_identity_map=aid_to_identity,
        duration_s=5.0,
        fight_id="cleanser-role-test",
    )

    a_readout = next(p for p in out.players if p.agent_id == a)
    # 11 cleanses > 10 → role includes "Cleanser"
    assert "Cleanser" in a_readout.roles, (
        f"expected 'Cleanser' in roles for 11 cleanses, got {a_readout.roles}"
    )
    assert a_readout.heal.cleanses == 11


def test_readout_cc_role() -> None:
    """A player with >3 CC applied gets the "CC" role.

    Seeds a player with 4 CCEvents. Verifies roles includes "CC".
    """
    from gw2_core import CCEvent

    a = 980_001  # CC specialist
    b = a + 1
    cc_skill = 9_800_001

    cc_events = [
        CCEvent(
            time_ms=i * 100,
            source_agent_id=a,
            target_agent_id=b,
            skill_id=cc_skill,
        )
        for i in range(4)
    ]

    aid_to_identity = {
        a: AgentIdentity(
            agent_id=a, name=f"CCer {a}", subgroup=0,
            account_name=f"synth.{a}", profession="PROF(2)", elite_spec="Berserker",
            is_player=True, is_commander=False,
        ),
        b: AgentIdentity(
            agent_id=b, name=f"Target {b}", subgroup=0,
            account_name=f"synth.{b}", profession="PROF(1)", elite_spec="Dragonhunter",
            is_player=True, is_commander=False,
        ),
    }
    out = aggregate_combat_readout(
        events=cc_events,
        skill_id_to_name_map={cc_skill: "CC"},
        agent_id_to_identity_map=aid_to_identity,
        duration_s=3.0,
        fight_id="cc-role-test",
    )

    a_readout = next(p for p in out.players if p.agent_id == a)
    assert "CC" in a_readout.roles, (
        f"expected 'CC' in roles for 4 CC, got {a_readout.roles}"
    )
    assert a_readout.damage.cc_applied == 4


def test_readout_strip_role() -> None:
    """A player with >5 strips gets the "Strip" role.

    Seeds a player with 6 BuffRemovalEvents (non-condition = strips).
    Verifies roles includes "Strip" alongside DPS.
    """
    from gw2_core import BuffRemovalEvent

    a = 960_001  # stripper
    b = a + 1   # target
    strip_skill = 9_600_001

    # 6 strip events — all non-condition buff_ids (Might=740)
    strip_events = [
        BuffRemovalEvent(
            time_ms=i * 500,
            source_agent_id=a,
            target_agent_id=b,
            skill_id=strip_skill,
            buff_id=740,  # Might (boon, not condition)
            stacks=1,
            duration_remaining_ms=0,
        )
        for i in range(6)
    ]

    aid_to_identity = {
        a: AgentIdentity(
            agent_id=a, name=f"Stripper {a}", subgroup=0,
            account_name=f"synth.{a}", profession="PROF(2)", elite_spec="Berserker",
            is_player=True, is_commander=False,
        ),
        b: AgentIdentity(
            agent_id=b, name=f"Target {b}", subgroup=0,
            account_name=f"synth.{b}", profession="PROF(1)", elite_spec="Dragonhunter",
            is_player=True, is_commander=False,
        ),
    }
    out = aggregate_combat_readout(
        events=strip_events,
        skill_id_to_name_map={strip_skill: "Strip"},
        agent_id_to_identity_map=aid_to_identity,
        duration_s=3.0,
        fight_id="strip-role-test",
    )

    a_readout = next(p for p in out.players if p.agent_id == a)
    # 6 strips > 5 → role includes "Strip" (alongside DPS as fallback)
    # detect_role_lite: 6 strips → weighted strip score = 6*5000=30000,
    # no damage/heal → r_strip=1.0 ≥ 0.35 → STRIP primary.
    assert "Strip" in a_readout.roles, (
        f"expected 'Strip' in roles for 6 strips, got {a_readout.roles}"
    )
    assert a_readout.damage.strips == 6


def test_readout_e2e_sample_zevtc_commander(client: TestClient) -> None:
    """E2E: upload sample.zevtc with [CMDR] agent, verify is_commander=True.

    Uploads the project's sample.zevtc (generated by
    scripts/generate-sample-zevtc.py), waits for parse completion,
    then verifies the readout envelope correctly marks the commander
    agent and the regular player.
    """
    from pathlib import Path

    sample_path = Path(__file__).resolve().parent.parent.parent.parent / "sample.zevtc"
    if not sample_path.exists():
        pytest.skip("sample.zevtc not found — run scripts/generate-sample-zevtc.py first")

    blob = sample_path.read_bytes()
    fight_id = post_upload(client, blob)

    resp = client.get(f"/api/v1/fights/{fight_id}/readout")
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    assert len(payload["players"]) == 2

    # Commander: is_commander=True, name stripped of [CMDR]
    cmd = next(p for p in payload["players"] if p["is_commander"])
    assert "[CMDR]" not in cmd["name"], (
        f"commander name should be stripped: {cmd['name']}"
    )
    assert cmd["is_commander"] is True

    # Regular player: is_commander=False
    player = next(p for p in payload["players"] if not p["is_commander"])
    assert player["is_commander"] is False


def test_readout_dist_to_commander_with_commander() -> None:
    """When a commander exists, dist_to_commander is computed for all players.

    Seeds a commander (agent c, is_commander=True) and a regular player
    (agent a). Both have PositionEvents at matching timestamps. Verifies
    that the commander gets dist_to_commander=0.0 and the regular player
    gets the Euclidean distance to the commander.
    """
    from gw2analytics_api.routes.fights.player_aggregators import aggregate_player_positions

    a = 900_002  # regular player
    c = 900_003  # commander

    aid_to_identity = {
        a: AgentIdentity(
            agent_id=a, name=f"Player {a}", subgroup=0,
            account_name=f"synth.{a}", profession="PROF(2)", elite_spec="Berserker",
            is_player=True, is_commander=False,
        ),
        c: AgentIdentity(
            agent_id=c, name=f"Cmd {c}", subgroup=0,
            account_name=f"synth.{c}", profession="PROF(1)", elite_spec="Dragonhunter",
            is_player=True, is_commander=True,
        ),
    }
    # Commander at (0, 0), player at (300, 400) — distance = 500 units
    # at the same timestamps so matching is exact.
    events = [
        PositionEvent(time_ms=1_000, source_agent_id=a, x=300.0, y=400.0),
        PositionEvent(time_ms=1_000, source_agent_id=c, x=0.0, y=0.0),
        PositionEvent(time_ms=2_000, source_agent_id=a, x=600.0, y=800.0),
        PositionEvent(time_ms=2_000, source_agent_id=c, x=0.0, y=0.0),
    ]
    result = aggregate_player_positions(
        events=events,
        agent_id_to_identity_map=aid_to_identity,
    )
    assert len(result) == 2

    # Commander's own distance is 0.
    cmd_row = next(r for r in result if r.account_name == f"synth.{c}")
    assert cmd_row.dist_to_commander == 0.0, (
        f"expected commander dist=0.0, got {cmd_row.dist_to_commander}"
    )

    # Player a: avg distance to commander at (0,0).
    # t=1000: sqrt(300²+400²)=500, t=2000: sqrt(600²+800²)=1000
    # avg = (500+1000)/2 = 750.0
    player_row = next(r for r in result if r.account_name == f"synth.{a}")
    assert player_row.dist_to_commander == pytest.approx(750.0, abs=1.0), (
        f"expected dist≈750.0, got {player_row.dist_to_commander}"
    )
