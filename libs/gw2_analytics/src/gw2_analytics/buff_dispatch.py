"""4-way buff-remove dispatch (v0.10.6+ Phase 9 step 4 realignment).

arcdps 2025+ encodes buff apply / remove ALL / remove SINGLE / remove MANUAL
via the ``is_statechange == 0`` + ``ev.buff != 0`` channel, distinguished by
the ``is_buffremove`` byte. The mapping is the arcdps.h ``cbtbuffremove``
enum, verified against TWO independent sources for auditability:

1. **arcdps's own ``evtc/README.txt``** --
   `https://www.deltaconnected.com/arcdps/evtc/README.txt`
   (the canonical upstream spec maintained by the arcdps developer).
2. **The community-port ``arcdps_datastructures.h``** at
   `<GW2-ArcDPS-Mechanics-Log>/src/arcdps_datastructures.h`
   (a community mirror of the C struct definitions used for
   the parser test fixtures; cross-checked against the
   arcdps.com README to confirm the four ``cbtbuffremove``
   enum values agree).

Reported values from both sources:

- ``0`` = CBTB_NONE (NOT a removal event — in the buff-emit predicate
  context, this is the "buff applied" sentinel)
- ``1`` = CBTB_ALL (all stacks removed — full condi-cleanse)
- ``2`` = CBTB_SINGLE (single stack removed — strip)
- ``3`` = CBTB_MANUAL (single stack auto-removed on all-stack or out-of-combat)

**v0.10.6+ Phase 9 history**:

- Plan 137 (v0.10.5 cycle) shipped a 3-way pre-fix dispatch with the WRONG
  mapping: ``1=SINGLE, 2=ALL`` (the bytes were SWAPPED vs arcdps.h). Plan
  137 was authored from a non-arcdps source (a public GW2 community
  reference implementation's docstring heuristics) and was not verified
  against the actual ``cbtbuffremove`` enum at planning time.
- Phase 9 step 1 (``5fefdae``) shipped the ``BoonApplyEvent.kind: Literal``
  discriminator with the project's (incorrect) mapping.
- Phase 9 step 2 (commit ``328833d``) exposed the ``is_buffremove`` byte
  via the parser's struct rename, enabling this realignment.
- Phase 9 step 4 (this commit) realigns the dispatch to the verified
  arcdps.h enum: ``1=ALL, 2=SINGLE, 3=MANUAL→REMOVE_SINGLE``.

**Calibration caveat**: this realignment is verified against the arcdps.h
ENUM constants (the data structure has a documented mapping). The
downstream loop (the parser's EMIT predicate — which combo of
``is_statechange`` / ``is_nondamage`` / ``value`` / ``buff_dmg`` /
``is_buffremove`` triggers a ``BoonApplyEvent`` emission) is calibrated
against REAL arcdps dumps in a separate maintainer run (no real dump was
available in CI at realignment time). The semantic mapping of the byte
value to the ``BuffChangeKind`` enum is independent of the emit predicate
and stands on the verified arcdps.h enum alone.

This module exposes a typed enum + decoder so callers don't need to
remember the magic bytes. The 4-byte-1-collapse dispatch surface
(4 arcdps byte values → 3 BuffChangeKind enum values; the CBTB_MANUAL=3
sentinel collapses onto REMOVE_SINGLE per arcdps's "use for in/out
volume" guidance) makes the implicit realignment explicit:
``REMOVE_ALL`` on untracked buffs (condi cleanses) MUST be accounted as
+N-stacks-via-arith, NOT by a weighted value derived from the event.
"""

from __future__ import annotations

from enum import Enum


class BuffChangeKind(Enum):
    """The four possible buff-change kinds on arcdps 2025+ event records.

    Maps the arcdps.h ``cbtbuffremove`` enum to the project's
    ``BoonApplyEvent.kind`` discriminator literal. The mapping is:

    * ``APPLY``         <- ``is_buffremove == 0`` (CBTB_NONE in buff-emit context)
    * ``REMOVE_ALL``    <- ``is_buffremove == 1`` (CBTB_ALL)
    * ``REMOVE_SINGLE`` <- ``is_buffremove == 2`` (CBTB_SINGLE)
                         OR ``is_buffremove == 3`` (CBTB_MANUAL; auto-removed
                         on all-stack or out-of-combat; semantically a
                         single-stack change for in/out volume calculations
                         per arcdps.h docstring: "ignore for strip/cleanse
                         calc, use for in/out volume").
    """

    APPLY = "apply"
    REMOVE_SINGLE = "remove_single"
    REMOVE_ALL = "remove_all"


def decode_buff_change(is_buffremove_byte: int) -> BuffChangeKind:
    """Decode the arcdps ``is_buffremove`` byte to a typed kind.

    Parameters
    ----------
    is_buffremove_byte:
        The raw byte value from the arcdps cbtevent record (offset 52 in
        the canonical struct layout; see ``libs/gw2_evtc_parser.parser``
        for the struct byte-alignment caveat).

    Returns
    -------
    :class:`BuffChangeKind`
        ``APPLY`` for ``0`` (CBTB_NONE -- not a removal event, but the
        project's buff-emit predicate interprets this as "the event is an
        apply"),
        ``REMOVE_ALL`` for ``1`` (CBTB_ALL),
        ``REMOVE_SINGLE`` for ``2`` (CBTB_SINGLE) and ``3`` (CBTB_MANUAL).

    Raises
    ------
    ValueError
        If ``is_buffremove_byte`` is negative (the struct ``b`` format is
        signed; negative is structurally invalid).

    Notes
    -----
    Unknown positive bytes (``>= 4``) fall back to ``REMOVE_SINGLE`` to
    match the project's pre-existing "unknown byte" fallback (forward-
    compat: arcdps could add a new variant in the future and the decoder
    would still produce a sensible default rather than crash).
    """
    if is_buffremove_byte < 0:
        raise ValueError(
            f"is_buffremove byte must be non-negative: {is_buffremove_byte}"
        )
    if is_buffremove_byte == 0:
        return BuffChangeKind.APPLY
    if is_buffremove_byte == 1:
        return BuffChangeKind.REMOVE_ALL
    if is_buffremove_byte == 2:
        return BuffChangeKind.REMOVE_SINGLE
    if is_buffremove_byte == 3:
        # CBTB_MANUAL collapses to REMOVE_SINGLE because arcdps
        # explicitly recommends the collapse for in/out volume
        # calculations ("ignore for strip/cleanse calc, use for
        # in/out volume" per arcdps h docstring).
        return BuffChangeKind.REMOVE_SINGLE
    # Unknown byte: REMOVE_SINGLE (forward-compat fallback).
    return BuffChangeKind.REMOVE_SINGLE


__all__ = [
    "BuffChangeKind",
    "decode_buff_change",
]
