#!/usr/bin/env python3
"""One-shot helper: insert the v0.9.28 section into plans/README.md.

Usage:
    python3 scripts/_insert_v0928_section.py

Idempotent: re-running finds the new section and refuses to re-insert.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README_PATH = ROOT / "plans" / "README.md"

# Anchor: the section immediately after v0.9.28 in the current
# chronological layout. v0.9.27 sits between v0.9.26 and v0.9.22;
# v0.9.28 follows the same pattern (current is moved to closed;
# new section is appended before v0.9.22).
ANCHOR_ANCHOR = "## v0.9.22 audit (closed)"

NEW_SECTION = """## v0.9.28 audit (current)

**Author:** senior-advisor audit (improve skill, standard effort) — Phase 8 cascade-gaps deep pass (a follow-up to v0.9.27 plan 083's finding that ``event_window.py`` was NOT updated when Phase 8 added ``BuffRemovalEvent`` to ``gw2_core``: this pass audits the 2nd-order impact of the same Phase 8 commit on (a) the test-side cascade for ``event_window.py`` (the tests are frozen at Phase 7 despite the source gaining Phase 8 handling), (b) an unrelated streaming-friendly refactor in ``per_fight_timeline._check_invariants``, and (c) a low-leverage docstring cleanup in ``services.py``)
**Stamped at:** 44ea862 (origin/main HEAD at audit time — after the v0.9.27 libs/gw2_analytics sibling-aggregators pass landed: 3 plans 083/084/085 written + indexed)
**Recon scope:** ``libs/gw2_analytics/src/gw2_analytics/per_fight_timeline.py`` + ``libs/gw2_analytics/tests/test_event_window.py`` + ``apps/api/src/gw2analytics_api/services.py`` (``libs/gw2_analytics/tests/test_target_dps.py`` + ``test_target_healing.py`` + ``test_target_buff_removal.py`` + ``test_per_fight_timeline.py`` already validated for Phase 8 — no findings there)
**Audit mode:** standard effort; targeted deep pass on Phase 8 cascade gaps + 2 unrelated DX findings; 3 findings selected for planning (1 MED test reliability + 1 LOW perf + 1 LOW DX/docs hygiene)

### v0.9.28 status table

| # | Plan | Status | Addresses finding | Effort |
|---|---|---|---|---|
| 086 | [086-v0928-event-window-test-phase8-cascade](./086-v0928-event-window-test-phase8-cascade.md) | **pending** (1 file edit on ``libs/gw2_analytics/tests/test_event_window.py``: add 1 factory ``_strip(time_ms, buff_removal) -> BuffRemovalEvent`` + 6 NEW test methods to the existing ``TestEventWindowAggregator`` class — BuffRemoval-only path + DPS-only with default-zero + mixed-kinds same-bucket + multi-bucket strip accumulation + dual-emit precision + Pydantic field introspection. The 7 existing Phase 6+v1 tests are unchanged) | #1 ``libs/gw2_analytics/tests/test_event_window.py`` is frozen at Phase 7 — it tests only ``DamageEvent`` + ``HealingEvent`` (no ``BuffRemovalEvent``, no ``buff_removal_total`` assertion). After plan 083 adds the Phase 8 source-code path (``elif isinstance(e, BuffRemovalEvent):`` branch + a new ``buff_removal_total`` field on ``EventBucket``), the tests pass verbatim (the ``default=0`` keeps pre-Phase-8 fixtures validate-cleanly) but DO NOT exercise the new code path → a future regression (e.g., a ``ruff`` rename of ``e.buff_removal`` to ``e.strip_magnitude`` in the source) would NOT be caught by the test suite, because no test triggers the strip accumulator branch. Same diagnostic class as plan 083 (source side), but on the test side (test reliability, MED) | S |
| 087 | [087-v0928-per-fight-timeline-check-invariants-materialization-fix](./087-v0928-per-fight-timeline-check-invariants-materialization-fix.md) | **pending** (1 file edit on ``libs/gw2_analytics/src/gw2_analytics/per_fight_timeline.py``: refactor ``aggregate()`` + ``_check_invariants`` plumbing. The ``_check_invariants(rows, events)`` parameterised call is replaced by ``_check_invariants(rows, expected_damage, expected_healing, expected_strip)`` — the 3 expected totals are now computed inline in the ``aggregate()`` for-loop (single pass) instead of via a second-pass ``list(events)`` materialisation in ``_check_invariants``. Net code change: ~0 lines (replace 2-line ``events_list = list(events)`` block with 3-int param plumbing). 1 NEW test file ``libs/gw2_analytics/tests/test_per_fight_timeline_invariants_refactor.py`` with 4 hermetic tests: empty-input + damage-only happy path + mixed-kinds same-bucket + invariant-failure fires) | #2 ``libs/gw2_analytics/src/gw2_analytics/per_fight_timeline.py::PerFightTimelineAggregator._check_invariants`` parameterised as ``_check_invariants(rows, events: Iterable[Event])`` materialises the events stream a SECOND time via ``list(events)`` to compute the 3 sum-preservation invariants. For a canonical WvW raid event blob (~100k+ events), the materialisation is a real memory hit: the events were decoded once + walked once for the per-bucket accumulator (``aggregate()`` body), and ``_check_invariants`` drains them again for the invariant check. Plumbing the 3 expected totals as ints makes the canonical caller 1-pass (perf + memory, LOW) | S |
| 088 | [088-v0928-services-docstring-started-at-framing-update](./088-v0928-services-docstring-started-at-framing-update.md) | **pending** (1 file edit on ``apps/api/src/gw2analytics_api/services.py::_save_fight``: the 12-line inline comment on ``started_at = datetime.now(UTC)`` is reorganised into 2 cleaner paragraphs — (a) "current canonical behavior" (the v0.8.1 unconditional override + the pre-v0.8.1 guard bug it closed) + (b) "Future work" block (the v0.9+ plan could parse the EVTC build field ``yyyyMMdd`` as a date anchor). Net code change: ~5 lines shorter) | #3 ``apps/api/src/gw2analytics_api/services.py::_save_fight`` has a 12-line comment block on the canonical ``started_at = datetime.now(UTC)`` override that mixes 3 things: an historical-bug explanation (v0.8.0 → v0.8.1), the current canonical behavior, and an aspirational future ("a future v0.9 could parse the EVTC build field (``yyyymmdd``) to get a date anchor"). The aspirational line is in-inline, not in a clearly-labelled future-work block — a future maintainer reading the comment is misled to think the v0.9 build-field parsing is a current refactor target. The ``libs/gw2_evtc_parser`` ``EvtcHeader.build_version`` already carries the ``yyyyMMdd`` string; a future plan can add an opt-in "use EVTC build for date anchor" flag. The cleaner framing labels the aspirational line as a ``Future work:`` block so a maintainer can scan past it without ambiguity (DX/docs hygiene, LOW) | S |

### Recommended execution order (v0.9.28)

1. **Plan 086** (event_window Phase 8 test cascade) — S effort, the most-impactful reliability finding (closes the source-side plan 083's silent-regression risk). 1 file edit + 0 NEW test files (extend the existing). Independent of 087/088.
2. **Plan 087** (per_fight_timeline materialization) — S effort, the streaming-friendly perf win for large event blobs. 1 file edit + 1 NEW test file. Independent of 086/088.
3. **Plan 088** (services doc cleanup) — S effort, the lowest-leverage finding (docs hygiene only). 1 file edit + 0 tests. Independent of 086/087.

All 3 are independent. Could ship in any order. The recommended order is by severity (MED reliability first), then by leverage (perf for 100k-event fights = O(100k) saved per request), then docs hygiene.

### Dependency graph (v0.9.28)

```
  plan 086 ──┐                              (libs/gw2_analytics/tests/test_event_window.py)
  plan 087 ──┼── INDEPENDENT ──────────     (libs/gw2_analytics/src/gw2_analytics/per_fight_timeline.py + libs/gw2_analytics/tests/test_per_fight_timeline_invariants_refactor.py)
  plan 088 ──┘                              (apps/api/src/gw2analytics_api/services.py)
```

All 3 plans touch DIFFERENT files. Plan 086 + plan 087 both touch ``libs/gw2_analytics`` (test + source) — could be a single PR for the v0.9.27 plan 083 follow-ups (the canonical "Phase 8 cascade gap is a project-wide concern, close it in one go" pattern). Plan 088 is independent.

### Considered and rejected (v0.9.28)

- **Plan 086 alternative: split into a NEW test file ``test_event_window_phase8_cascade.py``** — duplicates the ``_damage`` + ``_healing`` factories; loses the test-matrix visual continuity. The 6 new tests fit naturally into the existing ``TestEventWindowAggregator`` class.
- **Plan 086 alternative: add a single "Phase 8 smoke test"** — 1 test is weaker than 6 discrete tests; the per-bucket accumulator + the multi-bucket invariants + the dual-emit path are SEPARATE concerns that should each have a test.
- **Plan 087 alternative: pass a callback ``expected_sum_fn: Callable[[Iterable[Event]], tuple[int, int, int]]``** — the callable can drain the stream once, but the canonical caller (``aggregate()``) already drains the stream once; passing the 3 ints directly is simpler and saves 1 callable layer.
- **Plan 087 alternative: skip the invariant check entirely** (rely on type-checking) — the sum-preservation invariants are the canonical tests for "did the aggregator drop / double-count any events"; removing them would regress test quality.
- **Plan 087 alternative: use ``functools.reduce`` for the per-bucket accumulator** — the canonical per-bucket accumulator IS a ``defaultdict(int)`` + a per-iteration accumulator; the ``functools.reduce`` approach is less idiomatic.
- **Plan 088 alternative: remove the comment entirely** — the historical context (the pre-v0.8.1 guard bug) is genuinely useful for a maintainer who needs to understand why the unconditional override is canonical. Removing the comment loses that context.
- **Plan 088 alternative: extract the aspirational line to a separate ``TODO`` docstring on ``_save_fight``** — ``TODO`` markers read as "incomplete"; the ``Future work:`` block reads as "intentionally future-planned".
- **Plan 088 alternative: move the aspirational line to a ``## Future work`` section in ``docs/ROADMAP.md``** — ROCMAP is the canonical home for aspirational items; moving the line out of the inline comment fully unlocks the inline comment for "current behavior" only.

## v0.9.22 audit (closed)
"""


def main() -> int:
    text = README_PATH.read_text(encoding="utf-8")
    if "## v0.9.28 audit (current)" in text:
        print("v0.9.28 section already present; refusing to re-insert.")
        return 1
    if ANCHOR_ANCHOR not in text:
        print(f"Anchor {ANCHOR_ANCHOR!r} not found; aborting.")
        return 1
    new_text = text.replace(ANCHOR_ANCHOR, NEW_SECTION, 1)
    README_PATH.write_text(new_text, encoding="utf-8")
    print(f"Inserted v0.9.28 section. README grew {len(new_text) - len(text):+d} chars.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
