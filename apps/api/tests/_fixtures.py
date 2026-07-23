"""Shared EVTC test fixtures: synthetic .zevtc builder helpers.

Delegates to ``routes._evtc_builder`` which supports both legacy
(pre-2025) and EVTC2025+ wire formats. Tests that import from
``_fixtures`` and from ``routes._evtc_builder`` now produce the
same binary output for the same build string.

The ``_make_cbtevent`` wrapper defaults ``is_evtc2025=False`` for
backward compatibility: legacy callers (``build="20240925"``)
should NOT emit 2025+ event records. Tests that want EVTC2025+
events should import ``make_cbtevent`` directly from
``routes._evtc_builder``.
"""

from __future__ import annotations

from routes._evtc_builder import (
    build_2025_string,  # noqa: F401
    make_minimal_zevtc,
)
from routes._evtc_builder import make_cbtevent as _evtc_make_cbtevent


def _make_cbtevent(
    time_ms: int,
    src: int,
    dst: int,
    value: int,
    skill_id: int,
    *,
    is_statechange: int = 0,
    is_nondamage: int = 0,
    buff_dmg: int = 0,
) -> bytes:
    """Pack a legacy-format cbtevent (``is_evtc2025=False``).

    Backward-compatible wrapper around :func:`routes._evtc_builder.make_cbtevent`.
    Tests that need EVTC2025+ event records should import ``make_cbtevent``
    directly from ``routes._evtc_builder``.
    """
    return _evtc_make_cbtevent(
        time_ms,
        src,
        dst,
        value,
        skill_id,
        is_statechange=is_statechange,
        is_nondamage=is_nondamage,
        buff_dmg=buff_dmg,
        is_evtc2025=False,
    )


# Underscore-prefixed aliases for callers (e.g. test_uploads_helpers)
# that import ``_make_minimal_zevtc`` directly.
_make_minimal_zevtc = make_minimal_zevtc

# Public alias for callers that import ``make_cbtevent`` from ``_fixtures``.
make_cbtevent = _make_cbtevent
