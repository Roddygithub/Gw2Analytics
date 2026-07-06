"""Stable contract for any EVTC-log parser implementation.

The API layer depends ONLY on this Protocol. Changing the underlying
implementation (Python stream reader today, Rust+PyO3 tomorrow) requires
zero changes elsewhere in the codebase.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Protocol, runtime_checkable

from gw2_core import Fight


@runtime_checkable
class EvtcParser(Protocol):
    """Read one .zevtc / .evtc file and yield domain combat entities.

    Implementations are expected to be **stateless** and **stream-friendly**.
    """

    def supported_versions(self) -> frozenset[str]:
        """EVTC version strings this parser can handle, e.g. {'EVTC20251123'}."""
        ...

    def parse(self, source: Path) -> Iterator[Fight]:
        """Yield every :class:`~gw2_core.Fight` contained in this source.

        Args:
            source: Path to a `.zevtc` archive (one uncompressed `.evtc` inside)
                or to a raw `.evtc` file on disk. Implementations decide
                whether to read by chunks or memory-map the file.
        """
        ...


__all__ = ["EvtcParser"]
