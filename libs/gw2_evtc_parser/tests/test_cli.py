from __future__ import annotations

import argparse
import json
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest

import gw2_evtc_parser.__main__ as cli
from gw2_core import (
    Agent,
    BlockEvent,
    CombatOutcomeEvent,
    DamageEvent,
    DownEvent,
    EvtcHeader,
    Fight,
    HealthUpdateEvent,
)
from gw2_evtc_parser.__main__ import _build_parser, _compare_ei_metadata
from gw2_evtc_parser.exceptions import EvtcParseError


def test_compare_ei_metadata_reports_exact_differences() -> None:
    fight = Fight(
        id="golden",
        success=True,
        ei_encounter_id=459_520,
        agents=[
            Agent(
                id=1,
                name="Player",
                is_player=True,
                account_name=":Player.1234",
                subgroup="1",
                instance_id=10,
                team_id=20,
            ),
            Agent(id=2, name="Target", instance_id=20),
            Agent(id=3, name="Other target", instance_id=30),
        ],
        header=EvtcHeader(
            build_version="20250925",
            encounter_id=1,
            agent_count=13,
            gw2_build=188_004,
            map_id=96,
            arc_revision=162_433,
            duration_ms=11_789,
        ),
    )
    expected = {
        "arcVersion": "EVTC20250925",
        "triggerID": 1,
        "gW2Build": 188_004,
        "mapID": 96,
        "arcRevision": 162_433,
        "durationMS": 12_000,
        "success": True,
        "eiEncounterID": 459_520,
        "players": [
            {
                "account": "Player.1234",
                "name": "Player",
                "group": 1,
                "instanceID": 10,
                "teamID": 20,
                "dpsAll": [{"damage": 100, "condiDamage": 30, "powerDamage": 70}],
                "defenses": [
                    {
                        "damageTaken": 50,
                        "damageTakenCount": 1,
                        "conditionDamageTaken": 0,
                        "powerDamageTaken": 50,
                        "blockedCount": 1,
                        "evadedCount": 0,
                        "downCount": 0,
                        "deadCount": 0,
                    }
                ],
                "statsTargets": [
                    [{"totalDmg": 100, "downContribution": 100, "downed": 1}],
                    [{"totalDmg": 0, "downContribution": 0, "downed": 0}],
                ],
            }
        ],
        "targets": [{"instanceID": 20}, {"instanceID": 30}],
    }

    result = _compare_ei_metadata(
        fight,
        expected,
        [
            DamageEvent(
                time_ms=150,
                source_agent_id=1,
                target_agent_id=2,
                skill_id=723,
                damage=100,
                buff_dmg=30,
            ),
            DamageEvent(
                time_ms=2,
                source_agent_id=2,
                target_agent_id=1,
                skill_id=4,
                damage=50,
            ),
            BlockEvent(
                time_ms=3,
                source_agent_id=1,
                target_agent_id=0,
                skill_id=0,
            ),
            HealthUpdateEvent(
                time_ms=100,
                source_agent_id=2,
                target_agent_id=0,
                skill_id=0,
                health_percent=89,
            ),
            DownEvent(
                time_ms=200,
                source_agent_id=2,
                target_agent_id=0,
                skill_id=0,
            ),
            CombatOutcomeEvent(
                time_ms=200,
                source_agent_id=1,
                target_agent_id=2,
                skill_id=723,
                outcome="downed",
            ),
        ],
    )

    assert result["matches"] is False
    assert result["differences"] == {"durationMS": {"expected": 12_000, "actual": 11_789}}


def test_compare_ei_command_is_registered() -> None:
    args = _build_parser().parse_args(["compare-ei", "fight.zevtc", "ei.json"])

    assert args.cmd == "compare-ei"


# --------------------------------------------------------------------------
# Command handlers. These run against a stub parser so the CLI's own behaviour
# -- dispatch, output format, exit codes, error mapping -- is what is under
# test, not the parser.
# --------------------------------------------------------------------------

_MINIMAL_EVTC = b"EVTC" + b"20240925" + b"\x00" * 40


def _fight() -> Fight:
    return Fight(
        id="cli-fight",
        success=True,
        agents=[
            Agent(
                id=1,
                name="Player",
                is_player=True,
                account_name=":Player.1234",
                instance_id=10,
            ),
            Agent(id=2, name="Target", instance_id=20),
        ],
        header=EvtcHeader(
            build_version="20240925",
            encounter_id=1,
            agent_count=2,
            gw2_build=188_004,
            map_id=96,
            arc_revision=162_433,
            duration_ms=1_000,
        ),
    )


class _StubParser:
    def __init__(self, fights: list[Fight] | None = None, error: Exception | None = None) -> None:
        self._fights = fights or []
        self._error = error

    def parse(self, _raw: bytes) -> Iterator[Fight]:
        if self._error is not None:
            raise self._error
        return iter(self._fights)

    def parse_events(self, _raw: bytes) -> Iterator[object]:
        return iter(())


@pytest.fixture
def payload(tmp_path: Path) -> Path:
    path = tmp_path / "fight.evtc"
    path.write_bytes(_MINIMAL_EVTC)
    return path


def test_dump_agents_prints_a_human_table(
    monkeypatch: pytest.MonkeyPatch, payload: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "PythonEvtcParser", lambda: _StubParser([_fight()]))

    rc = cli.cmd_dump_agents(argparse.Namespace(file=payload, json=False))

    captured = capsys.readouterr()
    assert rc == 0
    assert "build=20240925" in captured.err
    assert "Player" in captured.out


def test_dump_agents_emits_one_json_object_per_agent(
    monkeypatch: pytest.MonkeyPatch, payload: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "PythonEvtcParser", lambda: _StubParser([_fight()]))

    rc = cli.cmd_dump_agents(argparse.Namespace(file=payload, json=True))

    rows = [json.loads(line) for line in capsys.readouterr().out.strip().splitlines()]
    assert rc == 0
    assert [row["name"] for row in rows] == ["Player", "Target"]
    assert rows[0]["is_player"] is True


def test_dump_agents_maps_a_parse_error_to_exit_2(
    monkeypatch: pytest.MonkeyPatch, payload: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        cli, "PythonEvtcParser", lambda: _StubParser(error=EvtcParseError("bad magic"))
    )

    rc = cli.cmd_dump_agents(argparse.Namespace(file=payload, json=False))

    assert rc == 2
    assert "ERROR: bad magic" in capsys.readouterr().err


def test_dump_agents_maps_an_empty_parse_to_exit_1(
    monkeypatch: pytest.MonkeyPatch, payload: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "PythonEvtcParser", lambda: _StubParser([]))

    rc = cli.cmd_dump_agents(argparse.Namespace(file=payload, json=False))

    assert rc == 1
    assert "parser yielded no fights" in capsys.readouterr().err


def test_load_payload_reads_a_plain_evtc(tmp_path: Path) -> None:
    path = tmp_path / "fight.evtc"
    path.write_bytes(_MINIMAL_EVTC)

    assert cli._load_payload(path) == _MINIMAL_EVTC


def test_load_payload_unwraps_a_zevtc_archive(tmp_path: Path) -> None:
    path = tmp_path / "fight.zevtc"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("fight.evtc", _MINIMAL_EVTC)

    assert cli._load_payload(path) == _MINIMAL_EVTC


def test_inspect_zip_lists_entries(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "fight.zevtc"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("fight.evtc", _MINIMAL_EVTC)

    rc = cli.cmd_inspect_zip(argparse.Namespace(file=path))

    out = capsys.readouterr().out
    assert rc == 0
    assert "1 entries" in out
    assert "fight.evtc" in out
    assert "head: b'EVTC" in out


def test_inspect_zip_rejects_a_non_archive(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "fight.zevtc"
    path.write_bytes(b"definitely not a zip")

    rc = cli.cmd_inspect_zip(argparse.Namespace(file=path))

    assert rc == 2
    assert "ERROR:" in capsys.readouterr().err


def test_compare_ei_reports_a_mismatch_as_exit_1(
    monkeypatch: pytest.MonkeyPatch,
    payload: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "PythonEvtcParser", lambda: _StubParser([_fight()]))
    expected = tmp_path / "ei.json"
    expected.write_text(json.dumps({"durationMS": 999}))

    rc = cli.cmd_compare_ei(argparse.Namespace(file=payload, expected=expected))

    assert rc == 1
    assert json.loads(capsys.readouterr().out)["matches"] is False


def test_compare_ei_rejects_unparseable_expected_json(
    monkeypatch: pytest.MonkeyPatch,
    payload: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "PythonEvtcParser", lambda: _StubParser([_fight()]))
    expected = tmp_path / "ei.json"
    expected.write_text("{not json")

    rc = cli.cmd_compare_ei(argparse.Namespace(file=payload, expected=expected))

    assert rc == 2
    assert "ERROR:" in capsys.readouterr().err


def test_compare_ei_rejects_a_non_object_payload(
    monkeypatch: pytest.MonkeyPatch,
    payload: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "PythonEvtcParser", lambda: _StubParser([_fight()]))
    expected = tmp_path / "ei.json"
    expected.write_text("[1, 2, 3]")

    rc = cli.cmd_compare_ei(argparse.Namespace(file=payload, expected=expected))

    assert rc == 2
    assert "must be an object" in capsys.readouterr().err


def test_main_dispatches_dump_agents(
    monkeypatch: pytest.MonkeyPatch, payload: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "PythonEvtcParser", lambda: _StubParser([_fight()]))

    assert cli.main(["dump-agents", str(payload), "--json"]) == 0
    capsys.readouterr()


def test_main_dispatches_inspect_zip(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "fight.zevtc"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("fight.evtc", _MINIMAL_EVTC)

    assert cli.main(["inspect-zip", str(path)]) == 0
    capsys.readouterr()


def test_main_dispatches_compare_ei(
    monkeypatch: pytest.MonkeyPatch,
    payload: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "PythonEvtcParser", lambda: _StubParser([_fight()]))
    expected = tmp_path / "ei.json"
    expected.write_text(json.dumps({"durationMS": 999}))

    assert cli.main(["compare-ei", str(payload), str(expected)]) == 1
    capsys.readouterr()
