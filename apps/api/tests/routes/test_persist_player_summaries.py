"""Pure unit tests for :func:`_persist_player_summaries` from services.py."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from unittest.mock import patch

import pytest
from sqlalchemy import select

from gw2_core import BoonApplyEvent, BuffRemovalEvent, DamageEvent, HealingEvent
from gw2analytics_api.database import get_sessionmaker
from gw2analytics_api.models import (
    OrmFight,
    OrmFightAgent,
    OrmFightPlayerSummary,
    OrmFightSkill,
    Upload,
)
from gw2analytics_api.services import _persist_player_summaries
from gw2analytics_api.services.player_summaries import _compute_account_roles

_D = 100_000  # base source agent id


def _seed_and_call(
    events: Sequence[DamageEvent | HealingEvent | BuffRemovalEvent],
    *,
    account_name_a: str = "synth.100",
    account_name_b: str | None = "synth.101",
    name_a: str = "PlayerA",
) -> str:
    """Seed a fight + 2 agents + call _persist_player_summaries. Returns fight_id."""
    fight_id = f"ps-test-{uuid.uuid4().hex[:8]}"
    upload_uuid = uuid.uuid4()
    # Derive a unique 64-char sha256 from the fight_id so parallel test
    # methods and re-runs do not collide on the Upload.sha256 unique
    # index (previously hardcoded to "a" * 64, which raised
    # UniqueViolation on the second test method that committed an Upload).
    # Using hashlib.sha256 (not uuid5) because the column is String(64)
    # and uuid5.hex is only 32 chars.
    sha256 = hashlib.sha256(fight_id.encode()).hexdigest()
    session = get_sessionmaker()()
    try:
        session.add(
            Upload(
                id=upload_uuid,
                status="completed",
                parser_version="0",
                sha256=sha256,
                original_filename="t.zevtc",
                size_bytes=0,
            )
        )
        session.flush()
        session.add(
            OrmFight(
                id=fight_id,
                upload_id=upload_uuid,
                agent_count=2,
                build_version="20250711",
                encounter_id=0,
                game_type=1,
                started_at="2026-07-11T12:00:00+00:00",
            )
        )
        session.add(
            OrmFightAgent(
                fight_id=fight_id,
                agent_id=_D,
                name=name_a,
                account_name=account_name_a,
                profession=2,
                elite_spec=18,
                is_player=True,
                subgroup="",
            )
        )
        if account_name_b:
            session.add(
                OrmFightAgent(
                    fight_id=fight_id,
                    agent_id=101,
                    name="PlayerB",
                    account_name=account_name_b,
                    profession=1,
                    elite_spec=27,
                    is_player=True,
                    subgroup="",
                )
            )
        session.add(
            OrmFightSkill(
                fight_id=fight_id,
                skill_id=200,
                name="TestSkill",
            )
        )
        session.flush()
        fight = session.get(OrmFight, fight_id)
        assert fight is not None
        _persist_player_summaries(session, fight, list(events))
        session.commit()
    finally:
        session.close()
    return fight_id


def _de(src: int = _D, dst: int = 101, skill: int = 200, dmg: int = 0) -> DamageEvent:
    return DamageEvent(
        time_ms=1_000,
        source_agent_id=src,
        target_agent_id=dst,
        skill_id=skill,
        damage=dmg,
    )


def _he(src: int = _D, dst: int = 101, skill: int = 200, heal: int = 0) -> HealingEvent:
    return HealingEvent(
        time_ms=1_000,
        source_agent_id=src,
        target_agent_id=dst,
        skill_id=skill,
        healing=heal,
    )


def _bf(src: int = _D, dst: int = 101, skill: int = 200, bf: int = 0) -> BuffRemovalEvent:
    return BuffRemovalEvent(
        time_ms=1_000,
        source_agent_id=src,
        target_agent_id=dst,
        skill_id=skill,
        buff_removal=bf,
    )


def _ba(
    src: int = _D,
    dst: int = 101,
    skill: int = 725,
    *,
    kind: str = "apply",
    stacks: int = 1,
    duration_ms: int = 0,
    time_ms: int = 1_000,
) -> BoonApplyEvent:
    return BoonApplyEvent(
        time_ms=time_ms,
        source_agent_id=src,
        target_agent_id=dst,
        skill_id=skill,
        kind=kind,
        stacks=stacks,
        duration_ms=duration_ms,
    )


def test_single_player_single_damage() -> None:
    """1 agent, 1 DamageEvent → 1 summary row with correct totals."""
    fight_id = _seed_and_call([_de(dmg=42)])
    session = get_sessionmaker()()
    try:
        rows = (
            session.execute(
                select(OrmFightPlayerSummary).where(OrmFightPlayerSummary.fight_id == fight_id)
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].total_damage == 42
        assert rows[0].total_healing == 0
        assert rows[0].total_buff_removal == 0
    finally:
        session.close()


def test_multiple_players() -> None:
    """2 agents with events → 2 summary rows."""
    fight_id = _seed_and_call(
        [
            _de(dmg=10),
            HealingEvent(
                time_ms=1_000,
                source_agent_id=101,
                target_agent_id=_D,
                skill_id=200,
                healing=20,
            ),
        ]
    )
    session = get_sessionmaker()()
    try:
        rows = (
            session.execute(
                select(OrmFightPlayerSummary).where(OrmFightPlayerSummary.fight_id == fight_id)
            )
            .scalars()
            .all()
        )
        assert len(rows) == 2
    finally:
        session.close()


def test_npc_only_fight() -> None:
    """0 player agents → 0 summary rows."""
    fight_id = _seed_and_call([_de(dmg=10)], account_name_a="", account_name_b=None)
    session = get_sessionmaker()()
    try:
        rows = (
            session.execute(
                select(OrmFightPlayerSummary).where(OrmFightPlayerSummary.fight_id == fight_id)
            )
            .scalars()
            .all()
        )
        assert len(rows) == 0
    finally:
        session.close()


def test_reparse_delete_insert() -> None:
    """Call twice → identical totals (no duplicate rows)."""
    events = [_de(dmg=10)]
    fight_id = _seed_and_call(events)
    session = get_sessionmaker()()
    try:
        fight = session.get(OrmFight, fight_id)
        assert fight is not None
        _persist_player_summaries(session, fight, list(events))
        session.commit()
        rows = (
            session.execute(
                select(OrmFightPlayerSummary).where(OrmFightPlayerSummary.fight_id == fight_id)
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].total_damage == 10
    finally:
        session.close()


def test_condi_power_split() -> None:
    """DamageEvent → power_damage set (TestSkill not in KNOWN_CONDI_NAMES)."""
    fight_id = _seed_and_call([_de(dmg=50)])
    session = get_sessionmaker()()
    try:
        rows = (
            session.execute(
                select(OrmFightPlayerSummary).where(OrmFightPlayerSummary.fight_id == fight_id)
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].power_damage == 50
        assert rows[0].condi_damage == 0
    finally:
        session.close()


def test_nul_sanitization() -> None:
    """Name is correctly sanitized (NUL bytes stripped by _sanitize_name)."""
    fight_id = _seed_and_call([_de(dmg=10)])
    session = get_sessionmaker()()
    try:
        rows = (
            session.execute(
                select(OrmFightPlayerSummary).where(OrmFightPlayerSummary.fight_id == fight_id)
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert "\x00" not in rows[0].name
    finally:
        session.close()


def test_empty_account_name_guard() -> None:
    """Player with empty account_name → 0 rows."""
    fight_id = _seed_and_call([_de(dmg=10)], account_name_a="")
    session = get_sessionmaker()()
    try:
        rows = (
            session.execute(
                select(OrmFightPlayerSummary).where(OrmFightPlayerSummary.fight_id == fight_id)
            )
            .scalars()
            .all()
        )
        assert len(rows) == 0
    finally:
        session.close()


def test_mixed_event_types() -> None:
    """Damage + Healing + BuffRemoval → all 3 magnitudes correct."""
    fight_id = _seed_and_call(
        [
            _de(dmg=30),
            _he(heal=20),
            _bf(bf=10),
        ]
    )
    session = get_sessionmaker()()
    try:
        rows = (
            session.execute(
                select(OrmFightPlayerSummary).where(OrmFightPlayerSummary.fight_id == fight_id)
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].total_damage == 30
        assert rows[0].total_healing == 20
        assert rows[0].total_buff_removal == 10
    finally:
        session.close()


def test_role_detection_invoked() -> None:
    """Verify detect_role_lite is called with correct args."""
    target = "gw2analytics_api.services.player_summaries.detect_role_lite"
    with patch(target, return_value=("DPS", [])) as mock:
        fight_id = _seed_and_call([_de(dmg=42)])
    mock.assert_called_once()
    kwargs = mock.call_args.kwargs
    assert kwargs["total_damage"] == 42
    session = get_sessionmaker()()
    try:
        rows = (
            session.execute(
                select(OrmFightPlayerSummary).where(OrmFightPlayerSummary.fight_id == fight_id)
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].detected_role == "DPS"
    finally:
        session.close()


def test_boon_strips_and_condition_cleanses_persisted() -> None:
    """BoonApplyEvent remove events are classified as boon strips or cleanses."""
    # Fury (tracked boon id 725) is stripped once; skill 99999 is an
    # intentionally untracked remove event used to exercise the heuristic
    # fallback that classifies non-tracked removes as condition cleanses.
    fight_id = _seed_and_call(
        [
            _ba(src=_D, dst=101, skill=725, time_ms=0, duration_ms=5_000),
            _ba(src=_D, dst=101, skill=725, kind="remove_all", time_ms=5_000, duration_ms=0),
            _ba(src=_D, dst=101, skill=99_999, kind="remove_all", time_ms=6_000, duration_ms=0),
            DamageEvent(
                time_ms=10_000,
                source_agent_id=_D,
                target_agent_id=101,
                skill_id=200,
                damage=1,
            ),
        ]
    )
    session = get_sessionmaker()()
    try:
        rows = (
            session.execute(
                select(OrmFightPlayerSummary).where(OrmFightPlayerSummary.fight_id == fight_id)
            )
            .scalars()
            .all()
        )
        assert len(rows) == 2
        by_account = {row.account_name: row for row in rows}
        source = by_account["synth.100"]
        assert source.boon_strips == 1
        assert source.condition_cleanses == 1
    finally:
        session.close()


def test_boon_uptime_and_outgoing_persisted() -> None:
    """BoonApplyEvent streams produce uptime + outgoing columns."""
    # Source _D applies fury (skill_id 725) to itself and to target 101
    # for 5s each. A late damage event pushes fight duration to 10s.
    # Source and target both have fury uptime > 0; only the source has
    # outgoing fury.
    fight_id = _seed_and_call(
        [
            _ba(src=_D, dst=_D, skill=725, time_ms=0, duration_ms=5_000),
            _ba(src=_D, dst=101, skill=725, time_ms=0, duration_ms=5_000),
            _ba(src=_D, dst=_D, skill=725, kind="remove_all", time_ms=5_000, duration_ms=0),
            _ba(src=_D, dst=101, skill=725, kind="remove_all", time_ms=5_000, duration_ms=0),
            DamageEvent(
                time_ms=10_000,
                source_agent_id=_D,
                target_agent_id=101,
                skill_id=200,
                damage=1,
            ),
        ]
    )
    session = get_sessionmaker()()
    try:
        rows = (
            session.execute(
                select(OrmFightPlayerSummary).where(OrmFightPlayerSummary.fight_id == fight_id)
            )
            .scalars()
            .all()
        )
        assert len(rows) == 2
        by_account = {row.account_name: row for row in rows}
        source = by_account["synth.100"]
        target = by_account["synth.101"]
        # Both players had fury for 5s out of a 10s fight.
        assert source.fury_uptime == pytest.approx(50.0)
        assert target.fury_uptime == pytest.approx(50.0)
        # Source applied fury to target once (5s). Self-buff doesn't count
        # as outgoing, and the target applied none.
        assert source.outgoing_fury == 5_000
        assert target.outgoing_fury is None
        # No other boons were applied → 0% uptime (tracker returns 0.0
        # for tracked boons that were never stacked).
        assert source.might_uptime == pytest.approx(0.0)
        assert target.might_uptime == pytest.approx(0.0)
    finally:
        session.close()


# ------------------------------------------------------------------ *
#  Unit tests for :func:`_compute_account_roles`
# ------------------------------------------------------------------ *


def test_compute_account_roles_defaults_to_dps() -> None:
    """No thresholds met → single \"DPS\" role."""
    result = _compute_account_roles(
        healing=0,
        total_squad_healing=1000,
        boons_out_rate=0.0,
        strips=0,
        cleanses=0,
        cc_applied=0,
    )
    assert result == ["DPS"]


def test_compute_account_roles_heal_threshold() -> None:
    """>10% of squad healing → Heal role."""
    result = _compute_account_roles(
        healing=200,  # 200 / 1000 = 20% > 10%
        total_squad_healing=1000,
        boons_out_rate=0.0,
        strips=0,
        cleanses=0,
        cc_applied=0,
    )
    assert "Heal" in result
    assert "DPS" not in result


def test_compute_account_roles_heal_below_threshold() -> None:
    """Exactly 10% of squad healing → NOT Heal (strict >)."""
    result = _compute_account_roles(
        healing=100,  # exactly 10%
        total_squad_healing=1000,
        boons_out_rate=0.0,
        strips=0,
        cleanses=0,
        cc_applied=0,
    )
    assert "Heal" not in result
    assert result == ["DPS"]


def test_compute_account_roles_support_threshold() -> None:
    """>1 boon/s → Support role."""
    result = _compute_account_roles(
        healing=0,
        total_squad_healing=1000,
        boons_out_rate=2.5,
        strips=0,
        cleanses=0,
        cc_applied=0,
    )
    assert "Support" in result
    assert "DPS" not in result


def test_compute_account_roles_support_exactly_one() -> None:
    """Exactly 1 boon/s → NOT Support (strict >)."""
    result = _compute_account_roles(
        healing=0,
        total_squad_healing=1000,
        boons_out_rate=1.0,
        strips=0,
        cleanses=0,
        cc_applied=0,
    )
    assert "Support" not in result
    assert result == ["DPS"]


def test_compute_account_roles_strip_threshold() -> None:
    """>5 strips → Strip role."""
    result = _compute_account_roles(
        healing=0,
        total_squad_healing=1000,
        boons_out_rate=0.0,
        strips=6,
        cleanses=0,
        cc_applied=0,
    )
    assert "Strip" in result


def test_compute_account_roles_strip_exactly_five() -> None:
    """Exactly 5 strips → NOT Strip (strict >)."""
    result = _compute_account_roles(
        healing=0,
        total_squad_healing=1000,
        boons_out_rate=0.0,
        strips=5,
        cleanses=0,
        cc_applied=0,
    )
    assert "Strip" not in result


def test_compute_account_roles_cleanser_threshold() -> None:
    """>10 cleanses → Cleanser role."""
    result = _compute_account_roles(
        healing=0,
        total_squad_healing=1000,
        boons_out_rate=0.0,
        strips=0,
        cleanses=11,
        cc_applied=0,
    )
    assert "Cleanser" in result


def test_compute_account_roles_cc_threshold() -> None:
    """>3 CC → CC role."""
    result = _compute_account_roles(
        healing=0,
        total_squad_healing=1000,
        boons_out_rate=0.0,
        strips=0,
        cleanses=0,
        cc_applied=4,
    )
    assert "CC" in result


def test_compute_account_roles_multiple_roles() -> None:
    """Multiple thresholds met → multiple roles, no DPS fallback."""
    result = _compute_account_roles(
        healing=200,  # Heal
        total_squad_healing=1000,
        boons_out_rate=2.0,  # Support
        strips=6,  # Strip
        cleanses=0,
        cc_applied=0,
    )
    assert result == ["Heal", "Support", "Strip"]


def test_compute_account_roles_zero_squad_healing() -> None:
    """total_squad_healing=0 → Heal role never assigned (avoids div/0)."""
    result = _compute_account_roles(
        healing=500,
        total_squad_healing=0,
        boons_out_rate=0.0,
        strips=0,
        cleanses=0,
        cc_applied=0,
    )
    assert "Heal" not in result
    assert result == ["DPS"]
