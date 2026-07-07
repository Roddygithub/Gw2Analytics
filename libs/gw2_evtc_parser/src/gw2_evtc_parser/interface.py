"""Stable contract for any EVTC-log parser implementation.

The API layer depends ONLY on this Protocol. Changing the underlying
implementation (Python stream reader today, Rust+PyO3 tomorrow) requires
zero changes elsewhere in the codebase.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import BinaryIO, Protocol, runtime_checkable

from gw2_core import Event, Fight


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

    def parse_events(self, source: BinaryIO | bytes) -> Iterator[Event]:
        """Yield every ``DamageEvent`` + ``HealingEvent`` from the cbtevent block.

        Phase 7 v2 ships heterogeneous event-stream extraction. The
        ``is_statechange`` flag is the primary discriminator: records
        with ``is_statechange != 0`` are statechange / buff-apply /
        defiance-bar events and are NOT yielded here (Phase 8 candidate).

        For records with ``is_statechange == 0``, the ``is_nondamage``
        flag picks the event kind:

        - ``is_nondamage == 0``: direct damage. Yield a
          :class:`~gw2_core.DamageEvent` carrying the damage taken
          (clamped via ``max(0, value)``).
        - ``is_nondamage > 0``: outgoing-heal (arcdps Convention A
          + Elite Insights parity -- the ``value`` field carries the
          heal magnitude when the non-damage flag is set). Yield a
          :class:`~gw2_core.HealingEvent` carrying the heal amount
          (also clamped).

        ``Event`` is the Pydantic v2 discriminated union over
        ``DamageEvent`` + ``HealingEvent``; aggregators in
        :mod:`gw2_analytics` branch on ``isinstance`` so the
        heterogeneous stream is routed correctly without manual
        ``event_type`` decoding at the consumer layer.

        Truncation is lenient: trailing bytes < 64 yield no event
        and produce no exception. Callers should check the yielded
        count against the expected arcdps fight length.

        Args:
            source: Either raw EVTC bytes, or any seekable/readable
                binary IO object exposing :py:meth:`read`.
        """
        ...


__all__ = ["EvtcParser"]
