"""arcdps EVTC binary parser.

Every implementation conforms to :class:`EvtcParser` in :mod:`.interface`.
Re-exporting the Protocol here keeps downstream use simple.
"""

from __future__ import annotations

from gw2_evtc_parser.interface import EvtcParser

__version__ = "0.0.1"

__all__ = ["EvtcParser", "__version__"]
