"""Hermetic tests for :mod:`gw2_analytics.buff_dispatch` (v0.10.6+ Phase 9 step 4 realignment).

The 6 plan-137 spec tests updated for the arcdps.h-verified cbtbuffremove enum:
byte 0 = CBTB_NONE (project's APPLY in the buff-emit context), byte 1 = CBTB_ALL,
byte 2 = CBTB_SINGLE, byte 3 = CBTB_MANUAL (collapsed to REMOVE_SINGLE per
arcdps docstring "use for in/out volume").
"""

from __future__ import annotations

import pytest

from gw2_analytics.buff_dispatch import BuffChangeKind, decode_buff_change


def test_decode_buff_change_zero_means_apply() -> None:
    """Contract: ``is_buffremove == 0`` (CBTB_NONE) → APPLY.

    CBTB_NONE is arcdps's "not used - not this kind of event" sentinel.
    In the project's buff-emit predicate (Phase 9 step 2-EMIT, deferred),
    byte ``0`` is the signal that the cbtevent is an apply context (the
    parser's emit branch will surface a ``BoonApplyEvent(kind="apply")``).
    The project convention locks ``0 → APPLY``.
    """
    assert decode_buff_change(0) == BuffChangeKind.APPLY


def test_decode_buff_change_one_means_remove_all() -> None:
    """Contract: ``is_buffremove == 1`` (CBTB_ALL) → REMOVE_ALL.

    Footnote: pre-realignment (plan 137 v0.10.5) mapped ``1 → REMOVE_SINGLE``
    (the SWAP from arcdps.h). The corrected mapping per the arcdps.h
    ``cbtbuffremove`` enum is ``1 → REMOVE_ALL`` (all-stack remove:
    condi-cleanse case).
    """
    assert decode_buff_change(1) == BuffChangeKind.REMOVE_ALL


def test_decode_buff_change_two_means_remove_single() -> None:
    """Contract: ``is_buffremove == 2`` (CBTB_SINGLE) → REMOVE_SINGLE.

    Footnote: pre-realignment mapped ``2 → REMOVE_ALL`` (the SWAP). The
    fix: arcdps's ``cbtbuffremove`` maps ``2 → CBTB_SINGLE`` (strip-of-1-
    stack case). The corrected mapping is ``2 → REMOVE_SINGLE``.
    """
    assert decode_buff_change(2) == BuffChangeKind.REMOVE_SINGLE


def test_decode_buff_change_three_means_remove_single_cbtb_manual() -> None:
    """Contract: ``is_buffremove == 3`` (CBTB_MANUAL) → REMOVE_SINGLE.

    arcdps.h ``cbtbuffremove`` enum extends to 4 values: 0=NONE, 1=ALL,
    2=SINGLE, 3=MANUAL. CBTB_MANUAL is the "single stack auto-removed on
    all-stack or out-of-combat" sentinel; arcdps docstring: "use for
    in/out volume". The project's semantic frame collapses CBTB_MANUAL
    onto REMOVE_SINGLE (single-stack change for the buff-uptime calendar)
    rather than adding a 4th ``BuffChangeKind`` enum value (the
    ``BoonApplyEvent.kind`` Literal is frozen at 3 values for backward-
    compat).
    """
    assert decode_buff_change(3) == BuffChangeKind.REMOVE_SINGLE


def test_decode_buff_change_unknown_byte_falls_back_to_remove_single() -> None:
    """Contract: unknown positive byte (>= 4) → REMOVE_SINGLE.

    Forward-compat fallback: arcdps could add a new cbtbuffremove variant
    in a future version. The decoder keeps returning REMOVE_SINGLE rather
    than crashing. Matches the project's pre-existing forward-compat
    behaviour (no change vs the pre-realignment version).
    """
    assert decode_buff_change(99) == BuffChangeKind.REMOVE_SINGLE


def test_decode_buff_change_rejects_negative_byte() -> None:
    """Contract: ``is_buffremove_byte < 0`` raises ``ValueError``.

    The struct ``b`` format is signed; a negative byte is structurally
    invalid input (would indicate a signed-int32 overflow during parser
    hop). The raise surfaces the input-rail failure at the decoder
    boundary rather than letting it silently round-trip through the
    emit pipeline.
    """
    with pytest.raises(ValueError):
        decode_buff_change(-1)
