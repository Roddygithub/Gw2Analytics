"""Hermetic tests for :mod:`gw2_analytics.buff_dispatch` (v0.10.5 plan 137).

The 2 plan-spec tests (3-way dispatch + unknown-byte fallback).
"""

from __future__ import annotations

import pytest

from gw2_analytics.buff_dispatch import BuffChangeKind, decode_buff_change


def test_decode_buff_change_three_way_dispatch() -> None:
    """Plan 137 spec test 4: 0/1/2 map to APPLY/REMOVE_SINGLE/REMOVE_ALL."""
    assert decode_buff_change(0) == BuffChangeKind.APPLY
    assert decode_buff_change(1) == BuffChangeKind.REMOVE_SINGLE
    assert decode_buff_change(2) == BuffChangeKind.REMOVE_ALL


def test_decode_buff_change_unknown_byte_falls_back_to_remove_single() -> None:
    """Plan 137 spec test 5: unknown positive byte falls back to REMOVE_SINGLE."""
    assert decode_buff_change(99) == BuffChangeKind.REMOVE_SINGLE


def test_decode_buff_change_rejects_negative_byte() -> None:
    """Negative byte is invalid and raises ValueError."""
    with pytest.raises(ValueError):
        decode_buff_change(-1)
