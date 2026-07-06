"""Exception classes for the EVTC parser layer.

These live in ``gw2_evtc_parser`` rather than ``gw2_core`` because they
describe *transport-level* problems with the input byte stream, not any
semantic problem with the domain model.
"""

from __future__ import annotations


class EvtcBaseError(Exception):
    """Base class for all errors raised by :mod:`gw2_evtc_parser`."""


class EvtcParseError(EvtcBaseError):
    """The byte stream violates the EVTC struct schema (truncated, malformed, version-mismatch)."""


class UnsupportedVersionError(EvtcBaseError):
    """The build version in the file header is outside ``EvtcParser.supported_versions()``."""


__all__ = ["EvtcBaseError", "EvtcParseError", "UnsupportedVersionError"]
