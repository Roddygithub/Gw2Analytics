"""v0.10.6+ Phase 9 step 2: hermetic struct-alignment tests.

The parser's ``_EVENT_STRUCT`` exposes byte offsets 52-53 as
``is_buffremove`` (the arcdps ``cbtbuffremove`` enum: ``0``=NONE,
``1``=ALL, ``2``=SINGLE, ``3``=MANUAL) + ``is_ninety``. The byte
positions are 1:1 with arcdps.h's ``cbtevent`` struct (the
upstream reference parsed in plan 026's verification).

Phase 9 step 3 (``accumulate_buff_events`` in
:mod:`gw2_analytics.buff_uptime`) consumes the ``is_buffremove``
byte to dispatch on the 3-way apply/single/all-remove kinds;
Phase 9 step 2 surfaces ``is_buffremove`` from the parser's struct
and these tests lock down the byte alignment so a future struct
tuple-reorder regression fires at the unit-test boundary BEFORE
it can corrupt downstream buff-uptime aggregation.

The emit branch that YIELDS ``BoonApplyEvent`` records is deferred
(see :file:`advisor-plans/026-phase-9-conditions.md` for the
deferred scope + the calibration risk for real arcdps dump
testing). When the emit branch lands, a new test file
``test_parser_emit_buff.py`` will exercise the predicate; the
tests here are STRUCT-only.

The tests use TUPLE DESTRUCTURING (not magic-index tuple access)
so a future struct length change raises ``ValueError: too many /
not enough values to unpack`` at the destructure step instead of
silently returning wrong byte values. The 22-arity strict
destructuring enforces an EXACT arity match (no over-counting, no
under-counting); the trailing ``*_tail`` collects 4 fields and the
``assert len(_tail) == 4`` documents the expected position of
slot 6 + 7 (= ``is_buffremove`` + ``is_ninety``) within the parser's
22-field unpack tuple.
"""

from __future__ import annotations

import struct

from gw2_evtc_parser.parser import (
    _CBTBUFREMOVE_KINDS,  # pinned by test_cbtbuffremove_kinds_tuple_shape_locked
    _EVENT_STRUCT,
    EVENT_SIZE,
)


def _pack_cbtevent_byte_at_offset(
    *,
    time_ms: int = 1_000,
    src_agent: int = 1,
    dst_agent: int = 2,
    value: int = 100,
    buff_dmg: int = 0,
    skill_id: int = 42,
    byte_52: int = 0,
    byte_53: int = 0,
) -> bytes:
    """Pack a synthetic 64-byte cbtevent with explicit bytes at offsets 52 + 53.

    Every other byte is 0. The struct format ``<QQQiiIIHHHbbbbbbbbIIbb``
    matches the parser's ``_EVENT_STRUCT`` 1:1.

    Byte-mapping arithmetic (forward ref: see also the comment in
    ``parser._EVENT_STRUCT``):

    * arcdps.h's cbtevent has 4 x uint16 (offsets 40-47) followed by
      12 x uint8 (offsets 48-59) followed by 4 x pad (60-63).
    * The parser's struct has 3 x uint16 (HHH, offsets 40-45)
      followed by 8 x uint8 (bbbbbbbb, offsets 46-53) followed by
      2 x uint32 (II, offsets 54-61) followed by 2 x uint8 (bb,
      offsets 62-63).

    Net effect: arcdps's 4th uint16 (``dst_master_instid``, offsets
    44-47) is read by the parser's struct as 4 separate single-byte
    slots (offsets 44, 45, 46, 47 -- the parser's 3rd uint16 reads
    arcdps byte 44 + 45 as uint16, then slots 0-1 of the
    ``bbbbbbbb`` region read arcdps bytes 46 + 47 individually).

    Therefore: parser slot INDEX N (in the ``bbbbbbbb`` region)
    reads arcdps byte ``(46 + N)``:

    * slot 0 (offset 46) -> arcdps byte 46
    * slot 6 (offset 52) -> arcdps byte 52 = ``is_buffremove``
    * slot 7 (offset 53) -> arcdps byte 53 = ``is_ninety``

    This offset coincidence means renaming parser slot 6 from ``_pad61``
    to ``is_buffremove`` is structurally a no-op (same byte, same
    struct, just a more descriptive name).

    Sign of bytes passed at offsets 52 + 53: arcdps uses SIGNED int8
    (``b`` format). Values in ``[-128, 127]`` are valid. The
    ``cbtbuffremove`` enum is ``[0, 1, 2, 3]`` (always non-negative);
    the boundary-cross test below uses the signed-byte limits to
    exercise the format's full range without exceeding the format
    width.
    """
    fmt = struct.Struct("<QQQiiIIHHHbbbbbbbbIIbb")
    return fmt.pack(
        time_ms,
        src_agent,
        dst_agent,
        value,
        buff_dmg,
        0,  # overstack_value
        skill_id,
        0,  # src_instid
        0,  # dst_instid
        0,  # translocated
        0,  # slot 0 of bbbbbbbb at offset 46
        0,  # slot 1 at offset 47
        0,  # slot 2 at offset 48
        0,  # slot 3 at offset 49
        0,  # slot 4 at offset 50
        0,  # slot 5 at offset 51
        byte_52,  # slot 6 at offset 52 = arcdps.h's is_buffremove
        byte_53,  # slot 7 at offset 53 = arcdps.h's is_ninety
        0,  # pad63 (uint32)
        0,  # pad64 (uint32)
        0,  # pad65
        0,  # pad66
    )


def _unpack_cbtevent(blob: bytes) -> tuple[int, int]:
    """Unpack a cbtevent and return ``(is_buffremove, is_ninety)``.

    Uses 22-arity tuple destructuring so a future struct length
    change (a new field added or removed) raises ``ValueError: too
    many / not enough values to unpack`` at this function instead
    of silently returning wrong byte values to the test assertions.
    The destructuring mirrors the parser's ``parse_events`` loop
    binding (the same local variable names: ``is_buffremove`` +
    ``is_ninety`` are the 2 byte slots we expose in Phase 9 step 2).

    The trailing ``*_tail`` collects the final 4 struct fields
    (``pad63``, ``pad64``, ``pad65``, ``pad66`` -- 2 uint32s + 2
    uint8s). The ``assert len(_tail) == 4`` documents the
    expected trailing-field count: a future struct shrinkage (a
    field removed from slot 18-21) raises the strict-arity
    ``ValueError``; a future struct EXPANSION (a field appended
    to slot 6 or 7, shifting the trailing region) raises the
    same ``ValueError``; a future struct expansion AFTER slot 7
    (extending the trailing region from 4 to 5+) makes the assert
    fire with a clear diagnostic. Both SHRINK and EXPAND paths
    are covered.
    """
    (
        _time_ms,
        _src_agent,
        _dst_agent,
        _value,
        _buff_dmg,
        _overstack_value,
        _skill_id,
        _src_instid,
        _dst_instid,
        _translocated,
        _is_cleanup,
        _is_nondamage,
        _is_statechange,
        _is_flanking,
        _is_shields,
        _is_offcycle,
        is_buffremove,  # slot 6 at offset 52 (arcdps.h's is_buffremove)
        is_ninety,  # slot 7 at offset 53 (arcdps.h's is_ninety)
        *_tail,  # 4 trailing fields: pad63 (u32) + pad64 (u32) + pad65 + pad66
    ) = _EVENT_STRUCT.unpack_from(blob, 0)
    assert len(_tail) == 4, (
        f"_EVENT_STRUCT layout changed: expected 4 trailing fields "
        f"(2 uint32s + 2 uint8 pads), got {len(_tail)}"
    )
    return is_buffremove, is_ninety


def test_event_struct_size_matches_arcdps_cbtevent_64_bytes() -> None:
    """The parser's ``_EVENT_STRUCT`` packs a 64-byte record (matches ``EVENT_SIZE``).

    Locks the struct literal's byte width so a future regression
    that drops a format character (e.g. ``III -> II``) flips a
    ``64`` to ``60`` and surfaces as a unit-test failure BEFORE
    the cbtevent aligner gets out of sync.
    """
    assert _EVENT_STRUCT.size == EVENT_SIZE == 64


def test_is_buffremove_byte_zero_reads_as_zero() -> None:
    """Synthetic cbtevent with ``is_buffremove == 0`` (arcdps CBTB_NONE) reads as 0.

    ``CBTB_NONE`` is the arcdps "not used - not this kind of event"
    sentinel. The parser unpacks it from the 6th single-byte slot
    (= byte 52 in arcdps.h) as a 0. Locks the byte order so a
    future sliding-window reorder of the ``bbbbbbbb`` block can
    be flagged at the unit-test boundary.
    """
    blob = _pack_cbtevent_byte_at_offset(byte_52=0)
    is_buffremove, is_ninety = _unpack_cbtevent(blob)
    assert is_buffremove == 0
    assert is_ninety == 0


def test_is_buffremove_byte_three_way_enum_values_round_trip() -> None:
    """Synthesize a 64-byte cbtevent with each of the 4 arcdps ``cbtbuffremove`` enum values.

    Verifies that bytes 52-53 hold the byte we wrote (the 4 arcdps
    sentinel values: 0=NONE, 1=ALL, 2=SINGLE, 3=MANUAL). A future
    struct byte-order regression slides one of the bytes into a
    different slot; this test fires at the unit-test boundary.
    """
    # arcdps h cbtbuffremove enum, in order
    expected_bytes = [
        (0, "CBTB_NONE"),
        (1, "CBTB_ALL"),
        (2, "CBTB_SINGLE"),
        (3, "CBTB_MANUAL"),
    ]
    for byte_value, arcdps_label in expected_bytes:
        blob = _pack_cbtevent_byte_at_offset(byte_52=byte_value)
        is_buffremove, _ = _unpack_cbtevent(blob)
        assert is_buffremove == byte_value, (
            f"is_buffremove byte mismatch: "
            f"wrote {byte_value} (arcdps {arcdps_label}) "
            f"at offset 52, read {is_buffremove}"
        )


def test_is_ninety_byte_round_trip() -> None:
    """The byte at offset 53 is exposed as ``is_ninety`` (the arcdps flag).

    arcdps writes 1 to ``is_ninety`` when the event was a 90%-
    threshold hit (e.g. Quickness expired at the 90% mark). The
    parser exposes it from slot 7 of the ``bbbbbbbb`` block. This
    test pins the offset so a future struct reorder doesn't
    mistake it for ``is_ninety``.
    """
    for byte_value in (0, 1, 2, 5):
        blob = _pack_cbtevent_byte_at_offset(byte_53=byte_value)
        _, is_ninety = _unpack_cbtevent(blob)
        assert is_ninety == byte_value, (
            f"is_ninety byte mismatch: wrote {byte_value} at offset 53, read {is_ninety}"
        )


def test_is_buffremove_and_is_ninety_dont_collide_with_neighbouring_slots() -> None:
    """Slot 6 (offset 52) and slot 7 (offset 53) are independent byte fields.

    A write at offset 52 should NOT bleed into the ``is_ninety``
    slot (offset 53). Locks the byte boundary so a future struct
    byte-order regression or padding change surfaces at the
    unit-test boundary. Values are clamped to the signed-byte
    range [-128, 127] (``b`` format width) -- arcdps only writes
    sentinel values 0-3 in practice, but the boundary exercise
    documents the format's full width.
    """
    # Write ``is_buffremove == 2`` AND ``is_ninety == 1`` and
    # verify both read back independently.
    blob = _pack_cbtevent_byte_at_offset(byte_52=2, byte_53=1)
    is_buffremove, is_ninety = _unpack_cbtevent(blob)
    assert is_buffremove == 2
    assert is_ninety == 1
    # And the inverse: signed-byte boundaries (127 + -128) instead of
    # 255 + 254 (which is out of the ``b`` format range and would
    # raise ``struct.error``).
    blob = _pack_cbtevent_byte_at_offset(byte_52=127, byte_53=-128)
    is_buffremove, is_ninety = _unpack_cbtevent(blob)
    assert is_buffremove == 127
    assert is_ninety == -128


def test_is_statechange_offset_48_empirical_lock() -> None:
    """Byte 48 of the cbtevent record reads as ``is_statechange`` (struct slot 12).

    The 2026-07-11 F1 calibration pilot confirmed this byte position is
    empirically correct for rev=1 arcdps logs (verified on 12 real
    WvW fixtures ranging 75 KB to ~12 MB; see
    ``advisor-plans/026-phase-9-conditions.md``). The existing
    ``parse_events`` reads tuple slot 12 (= byte offset 48) as
    ``is_statechange`` and applies the filter
    ``if is_statechange != 0: continue``. A struct byte-shift regression
    MUST fail this assertion at the unit-test boundary BEFORE the
    production filter silently misclassifies state-change records.
    """
    record = bytearray(64)  # all zeros
    record[48] = 1  # byte at offset 48 set to 1 (a known statechange value)
    unpacked = _EVENT_STRUCT.unpack_from(bytes(record), 0)
    assert unpacked[12] == 1, (
        f"is_statechange byte should be at offset 48 (struct slot 12). "
        f"Read {unpacked[12]} from slot 12 of the unpack tuple."
    )


def test_is_buffremove_offset_52_empirical_lock_F1() -> None:  # noqa: N802 -- F1 calibration suffix
    """Byte 52 of the cbtevent record reads as ``is_buffremove`` (struct slot 16).

    The 2026-07-11 F1 calibration pilot confirmed this byte position
    is empirically correct for rev=1 arcdps logs. The byte value
    corresponds to arcdps's ``cbtbuffremove`` enum (0=APPLY,
    1=REMOVE_ALL, 2=REMOVE_SINGLE, 3=REMOVE_SINGLE-CBTB_MANUAL-collapsed).
    ``buff_dispatch.decode_buff_change`` (commit ``529cb90``) converts
    this byte to the ``BoonApplyEvent.kind`` discriminator literal.
    """
    record = bytearray(64)
    record[52] = 2  # cbtbuffremove = REMOVE_SINGLE
    unpacked = _EVENT_STRUCT.unpack_from(bytes(record), 0)
    assert unpacked[16] == 2, (
        f"is_buffremove byte should be at offset 52 (struct slot 16). "
        f"Read {unpacked[16]} from slot 16 of the unpack tuple."
    )


def test_is_ninety_offset_53_empirical_lock_F1() -> None:  # noqa: N802 -- F1 calibration suffix
    """Byte 53 of the cbtevent record reads as ``is_ninety`` (struct slot 17).

    The 2026-07-11 F1 calibration pilot confirmed this byte position
    is empirically correct for rev=1 arcdps logs. arcdps writes 1 to
    ``is_ninety`` when the event was a 90%-threshold hit (e.g.
    Quickness expired at the 90% mark). Renamed from ``_pad61`` in
    v0.10.6 (commit ``328833d``).
    """
    record = bytearray(64)
    record[53] = 1  # is_ninety = 1
    unpacked = _EVENT_STRUCT.unpack_from(bytes(record), 0)
    assert unpacked[17] == 1, (
        f"is_ninety byte should be at offset 53 (struct slot 17). "
        f"Read {unpacked[17]} from slot 17 of the unpack tuple."
    )


def test_cbtbuffremove_kinds_tuple_shape_locked() -> None:
    """``_CBTBUFREMOVE_KINDS`` literal contents are pinned (3-tuple shape).

    The Phase 9 Step 2-EMIT-BRANCH predicate / tuple-length /
    indexing contract relies on this tuple having exactly 3
    entries in this exact order. A future maintainer adding,
    removing, or re-ordering entries silently widens the emit
    range (the per-yield ``assert`` only checks ``byte - 1``
    fits in ``len(_CBTBUFREMOVE_KINDS)``, which adapts to any
    length change).

    This module-level self-test pins the LITERAL contents (not
    just length). If a maintainer changes the literal string
    values (e.g. ``"remove_single"`` -> ``"manual_remove"``),
    fires at the test boundary BEFORE downstream buff-uptime
    consumers start emitting mismatched ``BoonApplyEvent.kind``
    discriminator literals.

    The expected shape:

        _CBTBUFREMOVE_KINDS = (
            "remove_all",      # byte 1: CBTB_ALL
            "remove_single",   # byte 2: CBTB_SINGLE
            "remove_single",   # byte 3: CBTB_MANUAL (collapsed per arcdps)
        )

    Indexed by ``is_buffremove - 1`` at the emit site in
    :meth:`PythonEvtcParser.parse_events`. Keep this test in
    sync with the constant's docstring.
    """
    # Tuple-equality owns both axes (literal content AND length);
    # a separate ``len()`` assert would be redundant -- Python
    # ``==`` on tuples compares both arity AND element-wise
    # contents, so a single assert covers both drift modes.
    expected = ("remove_all", "remove_single", "remove_single")
    assert expected == _CBTBUFREMOVE_KINDS, (
        f"_CBTBUFREMOVE_KINDS shape drifted: expected {expected!r} "
        f"(3 entries indexed by [byte-1] for the arcdps REMOVE "
        f"range {1, 2, 3}), got {_CBTBUFREMOVE_KINDS!r}. If you "
        f"intentionally added a 4th entry for a future arcdps "
        f"sentinel, update this test AND the predicate `in (1, "
        f"2, 3)` above the yield in parse_events so both stay "
        f"in sync."
    )
