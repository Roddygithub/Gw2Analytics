"""Stable contract for any EVTC-log parser implementation.

The API layer depends ONLY on this Protocol. Changing the underlying
implementation (Python stream reader today, Rust+PyO3 tomorrow) requires
zero changes elsewhere in the codebase.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import BinaryIO, Protocol, runtime_checkable

from gw2_core import Fight


@runtime_checkable
class EvtcParser(Protocol):
    """Read one EVTC binary stream and yield domain combat entities.

    Implementations are expected to be **stateless** and **stream-friendly**.

    Note:
        ``source`` is the **raw EVTC binary** (not the ``.zevtc`` zip wrap):
        the caller is responsible for unpacking the archive when relevant
        so that this Protocol stays transport-agnostic and future Rust
        bindings do not need to reimplement zip support.
    """

    def supported_versions(self) -> frozenset[str]:
        """EVTC build-version strings (arcdps build date, yyyymmdd) that this parser can handle."""
        ...

    def parse(self, source: BinaryIO | bytes) -> Iterator[Fight]:
        """Yield every :class:`~gw2_core.Fight` contained in this raw EVTC stream.

        Args:
            source: Either raw EVTC bytes, or any seekable/readable
                binary IO object exposing :py:meth:`read`.
        """
        ...


__all__ = ["EvtcParser"]
