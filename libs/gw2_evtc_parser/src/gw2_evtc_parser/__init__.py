"""arcdps EVTC binary parser.

Every implementation conforms to :class:`EvtcParser` in :mod:`.interface`.
Re-exporting the Protocol and the concrete Python implementation here keeps
downstream use simple.
"""

from __future__ import annotations

from gw2_evtc_parser.exceptions import EvtcBaseError, EvtcParseError, UnsupportedVersionError
from gw2_evtc_parser.interface import EvtcParser
from gw2_evtc_parser.parser import (
    EVENT_SIZE,
    PythonEvtcParser,
    read_zevtc_archive,
    read_zevtc_bytes,
)
from gw2_evtc_parser.statechange_dispatch import (
    STATE_CHANGE_BARRIER_UPDATE,
    STATE_CHANGE_STUN_BREAK,
    STATECHANGE_MAP,
    dispatch_statechange,
)

__version__ = "0.5.0"

__all__ = [
    "STATECHANGE_MAP",
    "STATE_CHANGE_BARRIER_UPDATE",
    "STATE_CHANGE_STUN_BREAK",
    "EvtcBaseError",
    "EvtcParseError",
    "EvtcParser",
    "PythonEvtcParser",
    "UnsupportedVersionError",
    "__version__",
    "dispatch_statechange",
    "read_zevtc_archive",
    "read_zevtc_bytes",
]
