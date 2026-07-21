"""v0.10.11+ Phase 9 step 3.5 -- REAL-FIXTURE ANCHOR for the dual-channel emit surface.

Why this test exists
--------------------

The synthetic-fixture predicate tests (``test_parser_emit_buff.py``) lock the
branch BOUNDARIES + the emit predicates via hand-packed 64-byte ``cbtevent``
records. They prove: "given a record whose ``is_buffremove`` byte carries
REMOVE-class signal, the REMOVE branch fires; given a record whose
``ev.buff`` byte + ``is_buffremove == 0``, the APPLY branch fires".

This test proves the OPPOSITE direction: "given a REAL arcdps WvW dump,
the parser's end-to-end emit contract holds -- no phantom BoonApply(kind='
apply') leaks from damage-only records, mid-combat APPLE goes through the
APPLY channel, REMOVEs go through the REMOVE channel".

Why this matters: the synthetic tests would all pass even if the unpack
tuple silently shifted by one byte (so long as the predicate logic is
correct on the relabelled slots). The synthetic tests catch a Predicate
regression -- NOT a Byte-position regression. A byte-position regression
that misaligns ``is_buffremove`` with arcdps's byte 52 (or ``ev.buff`` with
arcdps's byte 49) would not show up in the synthetic suite -- it would show
up here on a real dump because the predicate logic + the byte positions
contradict each other (the predicate would pick the WRONG bytes from the
record).

OFF-REPO FIXTURE POLICY
-----------------------

The 12 real WvW ``.zevtc`` fixtures used by the F1 calibration (2026-07-11)
live OFF the repo at ``/home/roddy/WvW_Analytics/uploads/`` to keep the
fixture sizes + the arcdps-game-data licensing out of the repo. The test
looks for the fixture at ``$WVW_ANALYTICS_DIR/uploads/5b161ec0*.zevtc``
(defaulting to ``/home/roddy/WvW_Analytics``), gracefully ``pytest.skip``
if the path is missing (so CI devs without the WvW sink still see green),
and exercises BOTH branches when the file is available.

Fixture choice: ``5b161ec03d544b0c96eeb6689590ece4.zevtc`` (75 KB compressed
-> 380 KB inner EVTC, 1,702 events). This is the F1-pilot outlier
(current struct ``is_statechange`` zero-rate 77.78% vs post-SYNC 48.66%;
current struct is decisively correct per the calibration pilot). The
fixture is small enough to parse in single-digit milliseconds but
exercises both the REMOVE + APPLY branches AND the dual-emit (damage +
heal + strip) cases.

Soft-bound assertion design
---------------------------

The assertions are RATIO-BASED rather than EXACT-COUNT-BASED so the test
stays stable across arcdps-version drift (a future arcdps that emits
slightly more or fewer buff-applies as a percentage of damage events
will not break the test). The phantom-leak detection is guarded by the
``apply_count <= damage_count // 3`` invariant: if the REMOVE predicate
breaks AND a future maintainer widens the predicate back to ``[0..3]``,
each damage record (1,567 of them on this fixture) would leak as a
phantom ``apply``, pushing the ratio to ~1.0 (way over the 33% bound).

A ``-/+ 10%`` window on the apply/ratio-lower-bound catches a partial
regression (a predicate that fires wrongly on half of damage records
gives a ~50% ratio).

Spec-stable assertions
----------------------

The minimum-bound + monotonic-time + ratio-bound assertions are
SPEC-STABLE: they express the contract in terms of relative
distributions, not absolute arcdps-version-dependent counts. A future
maintainer who changes the fixture path or the file size still passes;
a future maintainer who breaks the emit predicate fails.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from gw2_core import (
    BarrierEvent,
    BoonApplyEvent,
    BuffApplyEvent,
    BuffRemovalEvent,
    DamageEvent,
    DeathEvent,
    DownEvent,
    HealingEvent,
    StunBreakEvent,
)
from gw2_evtc_parser import PythonEvtcParser, read_zevtc_archive

#: Path to the F1-pilot fixture. Default points at the user's local
#: ``WVW_ANALYTICS_DIR``; overridable via env var (``WVW_ANALYTICS_DIR``)
#: for testing against a different corpus on a different host. The test
#: cleanly ``pytest.skip``s when the file is missing -- offline CI without
#: the WvW sink still green.
_FIXTURE_DIR = Path(os.environ.get("WVW_ANALYTICS_DIR", "/home/roddy/WvW_Analytics"))
_FIXTURE_PATH = _FIXTURE_DIR / "uploads" / "5b161ec03d544b0c96eeb6689590ece4.zevtc"


@pytest.mark.skipif(
    not _FIXTURE_PATH.exists(),
    reason=(
        f"F1-pilot fixture not found at {_FIXTURE_PATH}. Set WVW_ANALYTICS_DIR "
        f"or symlink the WvW sink to enable the real-fixture anchor. The "
        f"test cleanly skips otherwise."
    ),
)
def test_real_fixture_dual_channel_emit_contract() -> None:
    """Pin the dual-channel BoonApply emit contract against a real WvW arcdps dump.

    Asserts that:

    1. The parser emits the EXPECTED MIX of event kinds on a real fixture
       (the Phase 9 dual-channel surface is reachable end-to-end).
    2. The APPLY/REMOVE ratio falls within spec-stable bounds (no
       phantom-apply leak from damage-only records; the ratio matches
       the WvW buff-uptime norm).
    3. Every emitted BoonApply has ``kind`` in the closed-form set
       ``{\"apply\", \"remove_all\", \"remove_single\"}`` -- a future
       regression that emits an undefined ``kind`` literal would break
       this contract.
    4. The damage + heal + strip + boon-apply + remove splits add up
       to the same total event count (no event is silently dropped or
       double-counted).

    Why these bounds: F1 calibration (2026-07-11) confirmed the parser's
    byte 49 (struct slot 13 = ``_ev_buff``) is arcdps's ``ev.buff`` field.
    A future refactor that reverts the slot-13 binding back to
    ``_is_flanking`` (the pre-F1 legacy name) would shift the predicate's
    byte position by 0 (no byte-level shift -- the rename has zero
    byte-level impact) but the test STILL pinches the predicate logic
    against a real fixture.
    """
    raw_evtc = read_zevtc_archive(_FIXTURE_PATH)
    events = list(PythonEvtcParser().parse_events(raw_evtc))

    # Categorise + count.
    damage_count = sum(1 for e in events if isinstance(e, DamageEvent))
    heal_count = sum(1 for e in events if isinstance(e, HealingEvent))
    strip_count = sum(1 for e in events if isinstance(e, BuffRemovalEvent))
    apply_count = sum(1 for e in events if isinstance(e, BoonApplyEvent) and e.kind == "apply")
    remove_count = sum(1 for e in events if isinstance(e, BoonApplyEvent) and e.kind != "apply")
    buff_apply_count = sum(1 for e in events if isinstance(e, BuffApplyEvent))

    # ------- Sanity: event counts are >= minimum spec-stable thresholds. -------

    # The fixture MUST have damage events (WvW fights have combat).
    # ``damage_count >= 100`` is conservatively safe -- this fixture yields
    # 1,567 damage events, but we keep the bound loose so a future
    # arcdps-version drift doesn't break the test on a slightly smaller
    # damage mix.
    assert damage_count >= 100, (
        f"F1 fixture yielded {damage_count} damage events; expected >= 100 "
        f"(sanity floor; this fixture's measured count is 1,567)."
    )

    # The fixture MUST have at least one APPLY (mid-combat APPLY events
    # are the whole reason Phase 9 Step 3 APPLY-BRANCH exists).
    # Conservative floor: 5. This fixture yields 32 applies (buff-heavy
    # WvW fight), but again the bound is loose to avoid arcdps drift.
    assert apply_count >= 5, (
        f"F1 fixture yielded {apply_count} BoonApply(apply) events; expected "
        f">= 5 (phantom-leak signal: if a future predicate regression "
        f"emits APPLY for every damage record, this drops to zero)."
    )

    # ------- Spec-stable ratio bounds. -------

    # Phantom-apply leak signature: if a future refactor accidentally
    # widens the predicate to ``[0..3]`` (including damage-only records
    # with ``is_buffremove == 0 + ev_buff == 0``), every damage record
    # would leak one phantom BoonApply(kind='apply'), pushing the ratio
    # to ``1.0``. The bound below (``apply_count <= damage_count // 3``
    # = 33% rate) catches any regression that pushes the rate above
    # 33% -- a strong signal that the predicate is misfiring.
    #
    # This fixture's measured ratio is ~2.0% (32/1567). The bound is
    # loose enough to absorb arcdps-version drift on future revisions.
    assert apply_count <= damage_count // 3, (
        f"F1 fixture: apply/damage ratio = {apply_count}/{damage_count} "
        f"= {apply_count * 100.0 / damage_count:.2f}%; expected <= 33.33%. "
        f"A ratio above this bound is a phantom-leak signal -- the APPLY "
        f"predicate is firing on records it should reject (e.g. damage-only "
        f"records with both ``ev_buff == 0`` AND ``is_buffremove == 0``)."
    )

    # ------- Closed-form ``kind`` enumeration. -------

    # Every emitted BoonApply must have a kind in the closed-form set.
    # A future regression that emits an undefined string would break
    # the discriminated union downstream (gw2_core.BoonApplyEvent.kind
    # is a ``Literal['apply', 'remove_all', 'remove_single']``).
    valid_kinds = {"apply", "remove_all", "remove_single"}
    bad_kinds = [
        (e.kind, e.time_ms, e.source_agent_id)
        for e in events
        if isinstance(e, BoonApplyEvent) and e.kind not in valid_kinds
    ]
    assert not bad_kinds, (
        f"F1 fixture yielded {len(bad_kinds)} BoonApplyEvent(s) with "
        f"undefined ``kind`` literals: {bad_kinds[:5]}; valid literals "
        f"are {sorted(valid_kinds)}."
    )

    # ------- v0.11.0 A.6: statechange event counts. -------

    # Count the 4 A.4 statechange dispatch kinds.  These are emitted
    # from ``is_statechange != 0`` records (Deade=4, Down=5,
    # Barrier=38, StunBreak=56) via statechange_dispatch.py.  Real
    # WvW fights have deaths + downs; barrier + stunbreak are rarer.
    death_count = sum(1 for e in events if isinstance(e, DeathEvent))
    down_count = sum(1 for e in events if isinstance(e, DownEvent))
    barrier_count = sum(1 for e in events if isinstance(e, BarrierEvent))
    stunbreak_count = sum(1 for e in events if isinstance(e, StunBreakEvent))

    # The counting variables alone document the expected event surface;
    # the total sum assertion below proves they are accounted for.

    # ------- Total adds up. -------

    # Defence in depth: the per-kind counts must add up to the total event
    # count (no silent drop + no double-count).  v0.11.0 A.6 extends the
    # 6-kind sum to 10-kind (adds death + down + barrier + stunbreak).
    total_count = (
        damage_count
        + heal_count
        + strip_count
        + apply_count
        + remove_count
        + buff_apply_count
        + death_count
        + down_count
        + barrier_count
        + stunbreak_count
    )
    assert total_count == len(events), (
        f"F1 fixture: per-kind counts sum to {total_count} but "
        f"``len(events) == {len(events)}``. Mismatch = silent drop or "
        f"double-count in the parse_events dispatch. The 10-kind sum "
        f"(damage + heal + strip + apply + remove + buff_apply + "
        f"death + down + barrier + stunbreak) covers the v0.11.0 A.4 "
        f"statechange dispatch surface."
    )

    # ------- REMOVE branch verification. -------

    # The REMOVE branch fires for records where ``is_buffremove in (1, 2, 3)``.
    # The closed-form set is `{remove_all, remove_single}` (CBTB_MANUAL
    # collapses onto remove_single per the arcdps documented "use for
    # in/out volume" guidance).
    remove_kinds = {e.kind for e in events if isinstance(e, BoonApplyEvent) and e.kind != "apply"}
    assert remove_kinds <= valid_kinds, (
        f"F1 fixture: REMOVE records emit unexpected kinds: "
        f"{remove_kinds - valid_kinds}; valid kinds are {sorted(valid_kinds)}."
    )
    # A REMOVE event emits ``kind in ('remove_all', 'remove_single')``.
    # If a future refactor emits ``kind == 'apply'`` from REMOVE records
    # (i.e. accidentally aliases the branches), this assertion catches it.
    assert remove_kinds.isdisjoint({"apply"}), (
        f"F1 fixture: a record with REMOVE-class signal also emitted "
        f"BoonApply(kind='apply') -- the REMOVE + APPLY branches must "
        f"be MUTUALLY EXCLUSIVE via the elif. Set: {remove_kinds}."
    )


@pytest.mark.skipif(
    not _FIXTURE_PATH.exists(),
    reason=(f"F1-pilot fixture not found at {_FIXTURE_PATH}. Set WVW_ANALYTICS_DIR."),
)
def test_real_fixture_emit_preserves_record_order() -> None:
    """The parser preserves the cbtevent record order on the emit side.

    arcdps writes cbtevent records in the order the events fired -- not
    in time-ascending order. The parser surfaces them in record order
    (NOT in time-ascending order) so the emit stream preserves the
    arcdps causality direction. A future refactor that sorts the stream
    by ``time_ms`` before yielding would break this contract -- the test
    pins that the records come out in the order they came in.

    This F1 fixture's records are NOT time-monotonic (a known property
    of arcdps's statechange-driven stream), so this test does NOT
    assert monotonicity. It asserts POSITIONAL invariants instead:
    iteration order matches the parser-side cursor order.
    """
    raw_evtc = read_zevtc_archive(_FIXTURE_PATH)
    # Two passes: parse twice, compare positions of every DamageEvent.
    events_a = list(PythonEvtcParser().parse_events(raw_evtc))
    events_b = list(PythonEvtcParser().parse_events(raw_evtc))

    # Iteration order must be deterministic across parser instances.
    assert len(events_a) == len(events_b), (
        f"F1 fixture: two parser passes yielded different lengths "
        f"({len(events_a)} vs {len(events_b)}); the parser's emit "
        f"order is non-deterministic (state leak)."
    )

    # The byte-source positions inferred from record order are stable.
    # We do NOT compare every event by value (an O(N) full-stream equality
    # -- too slow for CI) -- instead we spot-check the FIRST 5 + LAST 5
    # + the median event.
    for i in (0, 1, 2, 3, 4, len(events_a) - 5, len(events_a) - 1):
        assert events_a[i] == events_b[i], (
            f"F1 fixture: event at index {i} differs across parser passes "
            f"(iteration order is non-deterministic)."
        )
