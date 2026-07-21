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
from gw2_core import DamageEvent, HealingEvent, StunBreakEvent
from gw2analytics_api.routes.fights.aggregators import (
    aggregate_combat_readout,
    make_barrier_portion_getter,
    make_dps_split_getter,
)
from gw2analytics_api.routes.fights.mappers import AgentIdentity

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
    assert a_row["elite_spec"] != "UNKNOWN"  # format_elite_spec(Berserker=18) -> "ELITE(18)"
    assert a_row["is_commander"] is False
    assert a_row["roles"] == []
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
            elite_spec="ELITE(18)",
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
            elite_spec="ELITE(18)",
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
    assert a_readout.elite_spec == "ELITE(18)"
    assert a_readout.is_commander is False
    # The pre-followup coerce of None to "" would have triggered
    # ``assert a_readout.account_name == ""`` (the lossy sentinel);
    # the post-followup None preservation is what this test pins.


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
            elite_spec="ELITE(18)",
            is_player=True,
            is_commander=False,
        ),
        b: AgentIdentity(
            agent_id=b,
            name=f"Phase6v2 {b}",
            subgroup=0,
            account_name=f"synth.{b}",
            profession="PROF(1)",
            elite_spec="ELITE(27)",
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
