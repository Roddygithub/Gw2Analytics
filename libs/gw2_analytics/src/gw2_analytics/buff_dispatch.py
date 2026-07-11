"""3-way buff-remove dispatch (v0.10.5 plan 137).

arcdps 2023+ encodes buff apply / remove SINGLE / remove ALL via
the same ``is_statechange == 0`` + ``ev.buff != 0`` channel,
distinguished by the ``is_buffremove`` byte:

- ``0`` = apply
- ``1`` = single-stack remove
- ``2`` = full-stack remove

This module exposes a typed enum + decoder so callers don't need to
remember the magic bytes. The 3-way dispatch is the calibration-2025-12
fix: ``REMOVE_ALL`` on untracked buffs (condi cleanses) MUST be
accounted as +1, NOT by a weighted value derived from the event.
"""

from __future__ import annotations

from enum import Enum


class BuffChangeKind(Enum):
    """The three possible buff-change kinds on arcdps 2023+ event records."""

    APPLY = "apply"
    REMOVE_SINGLE = "remove_single"
    REMOVE_ALL = "remove_all"


def decode_buff_change(is_buffremove_byte: int) -> BuffChangeKind:
    """Decode the arcdps ``is_buffremove`` byte to a typed kind.

    Parameters
    ----------
    is_buffremove_byte:
        The raw byte value from the arcdps event record.

    Returns
    -------
    :class:`BuffChangeKind`
        ``APPLY`` for ``0``, ``REMOVE_SINGLE`` for ``1``,
        ``REMOVE_ALL`` for ``2``.

    Raises
    ------
    ValueError
        If ``is_buffremove_byte`` is negative.

    Notes
    -----
    Unknown positive bytes fall back to ``REMOVE_SINGLE`` to match
    the upstream "unknown byte" fallback. This keeps the decoder
    forward-compatible if arcdps ever adds a new remove variant.
    """
    if is_buffremove_byte < 0:
        raise ValueError(
            f"is_buffremove byte must be non-negative: {is_buffremove_byte}"
        )
    if is_buffremove_byte == 0:
        return BuffChangeKind.APPLY
    if is_buffremove_byte == 1:
        return BuffChangeKind.REMOVE_SINGLE
    if is_buffremove_byte == 2:
        return BuffChangeKind.REMOVE_ALL
    # Unknown byte: fallback to REMOVE_SINGLE (matches upstream
    # calibration note for "unknown byte").
    return BuffChangeKind.REMOVE_SINGLE


__all__ = [
    "BuffChangeKind",
    "decode_buff_change",
]
