"""Contract tests for :class:`EvtcParser`.

If a class claims to implement the Protocol but raises ``TypeError`` on
``isinstance(parser, EvtcParser)``, the contract is broken and the
up-casting to the Protocol — used by the FastAPI layer — will fail at
runtime.
"""

from __future__ import annotations

from collections.abc import Iterator
from io import BytesIO
from typing import BinaryIO

import pytest

from gw2_core import EvtcHeader, Fight, GameType
from gw2_evtc_parser import EvtcParser

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _GoodFakeParser:
    """Conforming implementation — used to verify Protocol acceptance."""

    @staticmethod
    def supported_versions() -> frozenset[str]:
        return frozenset({"TEST"})

    @staticmethod
    def parse(source: BinaryIO | bytes) -> Iterator[Fight]:
        yield Fight(
            id="deadbeef" * 8,
            game_type=GameType.WVW,
            header=EvtcHeader(
                build_version="00000000",
                encounter_id=1,
                agent_count=0,
                skill_count=0,
            ),
        )


class _BadFakeParser:
    """Non-conforming — missing the ``parse`` method required by the Protocol."""

    @staticmethod
    def supported_versions() -> list[str]:
        return ["TEST"]  # also wrong return type, but @runtime_checkable ignores it

    # NOTE: intentionally no `parse` method — Protocol isinstance fails.


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_protocol_accepts_conforming_parser() -> None:
    parser = _GoodFakeParser()
    assert isinstance(parser, EvtcParser)
    fights = list(parser.parse(b""))
    assert len(fights) == 1
    assert fights[0].header is not None
    assert fights[0].header.encounter_id == 1


def test_protocol_rejects_non_conforming_parser() -> None:
    bad = _BadFakeParser()
    assert not isinstance(bad, EvtcParser)


def test_protocol_supports_binary_io_input() -> None:
    parser = _GoodFakeParser()
    fights = list(parser.parse(BytesIO(b"")))
    assert len(fights) == 1


@pytest.mark.parametrize(
    "src",
    [b"", BytesIO(b"")],
    ids=["bytes", "binaryio"],
)
def test_protocol_accepts_empty_payload(src: BinaryIO | bytes) -> None:
    """Even a zero-byte payload should be enough to be accepted at type level."""
    list(_GoodFakeParser().parse(src))
