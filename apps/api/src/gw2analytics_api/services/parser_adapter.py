"""The single product-owned boundary to the EVTC/ZEvtc parser.

Product code (services, workers, routes) must go through this module instead
of importing the ``gw2_evtc_parser`` package directly. The adapter owns the
concrete parser implementation, archive unpacking, error type and the parser
provenance recorded on each upload, so the parser can later be swapped for the
Elite Insights process without touching product service composition.

See ``docs/architecture/parser-boundary.md`` for the migration contract.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from gw2_core import Event, Fight
from gw2_evtc_parser import EvtcParseError, PythonEvtcParser, read_zevtc_bytes
from gw2_evtc_parser import __version__ as _PARSER_VERSION  # noqa: N812

__all__ = [
    "EvtcParseError",
    "ParserProvenance",
    "parse_archive",
    "parse_events",
    "provenance",
]


@dataclass(frozen=True)
class ParserProvenance:
    """Identity of the parser implementation that produced a parse."""

    name: str
    version: str


#: Provenance stamped onto ``Upload.parser_version`` for every parse.
provenance = ParserProvenance(name="gw2_evtc_parser", version=_PARSER_VERSION)

# Module-level singleton: the parser is stateless and safe to reuse.
_parser = PythonEvtcParser()


def parse_archive(raw_bytes: bytes) -> tuple[bytes, Iterator[Fight]]:
    """Unpack a ``.zevtc`` upload and return ``(evtc_bytes, fight iterator)``."""
    evtc_bytes = read_zevtc_bytes(raw_bytes)
    return evtc_bytes, _parser.parse(evtc_bytes)


def parse_events(evtc_bytes: bytes) -> Iterator[Event]:
    """Yield normalized events for an already-unpacked EVTC byte stream."""
    return _parser.parse_events(evtc_bytes)
