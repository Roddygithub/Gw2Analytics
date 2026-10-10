"""The product reaches the EVTC parser only through the adapter boundary."""

from __future__ import annotations

from pathlib import Path

from gw2analytics_api.services import parser_adapter

SRC = Path(parser_adapter.__file__).resolve().parents[1]


def test_provenance_identifies_the_parser() -> None:
    assert parser_adapter.provenance.name == "gw2_evtc_parser"
    assert parser_adapter.provenance.version


def test_parse_archive_delegates_and_returns_unpacked_bytes(monkeypatch) -> None:
    class _FakeParser:
        def parse(self, evtc: bytes):
            yield f"fight:{evtc.decode()}"

    monkeypatch.setattr(parser_adapter, "_parser", _FakeParser())
    monkeypatch.setattr(parser_adapter, "read_zevtc_bytes", lambda raw: b"EVTC")

    evtc_bytes, fights = parser_adapter.parse_archive(b"raw-upload")

    assert evtc_bytes == b"EVTC"
    assert list(fights) == ["fight:EVTC"]


def test_only_the_adapter_constructs_the_concrete_parser() -> None:
    offenders = [
        path.relative_to(SRC).as_posix()
        for path in SRC.rglob("*.py")
        if path.name != "parser_adapter.py"
        and "PythonEvtcParser(" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], (
        f"construct the EVTC parser through services.parser_adapter, not directly: {offenders}"
    )
