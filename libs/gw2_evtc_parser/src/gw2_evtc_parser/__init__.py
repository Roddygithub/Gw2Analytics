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

__version__ = "0.2.0"

__all__ = [
    "EvtcBaseError",
    "EvtcParseError",
    "EvtcParser",
    "PythonEvtcParser",
    "UnsupportedVersionError",
    "__version__",
    "read_zevtc_archive",
    "read_zevtc_bytes",
]
