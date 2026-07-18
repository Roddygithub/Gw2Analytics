# Plan 164 — v0.10.25 — Parser-side `time_ms` normalization + skill-table re-read

**Source:** E2E journey finding #2 (`plans/E2E-JOURNEY-2026-07-11.md`).
**Severity:** **HIGH** (parser, root cause of 3 observed E2E failures).
**Effort:** **L** (parser-layer + hermetic regression tests).
**Drift base:** `1813881` (origin/main HEAD post-E2E-JOURNEY PR).

## Symptom

`real_small.evtc` (47-agent / 2000-skill fight) misparses
during the 2026-07-18 real-backend E2E user-journey:
- Per-event `time_ms ≈ 1.4e19` (raw arcdps timestamp; not fight-relative)
- 0 player summaries (zeros roll up because the per-skill rollup mis-read)
- Cascades through:
  - **Bug #1** `PerFightTimelineAggregator` (already mitigated via plan 159
    `_MAX_BUCKETS=50_000` — converts the DoS hang into a fast 500)
  - `/api/v1/fights/{id}/events` 500 (defensive guard fires on garbage `time_ms`)
  - `/players` empty (skill-table mis-read → 0 rollups)

## Root cause

1. **`time_ms` not normalized.** arcdps writes `time_ms` as raw
   machine-time on the source (a `uint64` from the arcdps in-game
   overlay logger) — the parser picks it up byte-for-byte without
   subtracting the per-fight start offset. The +1.4e19 magnitude
   comes from a `time_t`-style encoding on the `real_small.evtc`
   fixture (probably arcdps test-mode timestamp leak).

2. **`player_attendance` skill-table mis-read.** The per-skill
   rollup (`OrmFightPlayerSummary`) builds per-player counters by
   iterating the skill events; when the skill-table read produces
   a 0-row seed under the misaligned `time_ms`, every sum is 0 →
   the players endpoint surfaces an empty list.

## Fix

### Stage 1 — Parser emit path normalization

In `libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py::parse_events`
(or the WAVE-8 `_dispatch_event` SCAFFOLD path):

- Detect raw timestamps (`time_ms > 0` + module-level
  `_MAX_FIGHT_DURATION_MS = 6 * 60 * 60 * 1000 = 21.6M` ms = 6 h cap)
  vs fight-relative (smaller).
- Trigger a **single-shot rebase** on the first event's `time_ms`
  (subtract that constant from every later event).
- Emit a `parser_log` warning (LOG WARNING, not error — keeps
  parse pipeline alive).

### Stage 2 — Skill-table re-read invariant

In the same parser pass, when `len(skill_table) == 0` but
`agent_count > 0` AND `len(events) > 0`, emit a WARN log
and **synthesize a placeholder skill table** (`Skill(id=0, name="UNKNOWN")`)
so downstream aggregators don't divide by zero / iterate 0 times.

Stage 2 overlaps with the ``libs/gw2_skills`` v0.11.0 SCAFFOLD
catalog population (Blocker B per ``plans/WAVE-8-parser-side.md``
§B.1-B.7): once the catalog lands at
``libs/gw2_skills/src/gw2_skills/data/gw2_skills.ndjson``, the
placeholder synthesis here is replaced by a seeded lookup (the
``SkillCatalog.__contains__(skill_id)`` path); until then this
synthesis is the canonical fallback and emits a WARN log so a
catalog reviewer can see the gap on the per-fight diagnostics
page. The WAVE-8 reader can trace the linkage without grepping
this plan against the Skills DB catalog.

### Stage 3 — Hermetic regression tests

`libs/gw2_evtc_parser/tests/test_parser_emit_statechange.py`:

- `test_time_ms_normalization_rebases_raw_timestamps`: feed
  `real_small.evtc` (or a fixture-slim clone if binary fixture
  is too large for a unit test — see `tests/fixtures/zevtc/real_small.evtc`).
  Assert first event `time_ms == 0` + last event
  `time_ms < _MAX_FIGHT_DURATION_MS`.
- `test_skill_table_synthesis_fires_on_zero_length`: feed
  a binary with `agent_count=1, skill_count=0` (still legal
  arcdps layout). Assert post-parse
  `len(skill_table) == 1` + skill_id 0 = UNKNOWN sentinel.

## Verification (live stack)

Mirroring the plan-159 verification recipe:

**Before**: `real_small.evtc` parses to garbage `time_ms≈1.4e19`,
players list 0 entries, `/events` 500, `/timeline` 500.

**After**: `real_small.evtc` parses to `time_ms ∈ [0, 21.6M]`,
players list 47 entries, `/events` 200, `/timeline` 200.

## Effort rationale (L)

- Stage 1: M (parser-layer change + WARN log plumbing)
- Stage 2: S (synthesize one sentinel + emit WARN)
- Stage 3: M (binary fixture + 2 hermetic tests + edge cases)
- Stage 4 (live stack e2e re-run): XS (reuse the harness from
  plan 159's verification pattern)

## Why this is HIGH despite plan 159's mitigation

Plan 159 closes the **hang** (DoS) but the underlying data
still ends up garbage on the wire — `/events` returns 500,
`/players` returns empty. Without plan 164, the whole `/fights/[id]`
detail page stays blank (per bug #4) for every REAL fight.
Plan 165 (section isolation) decouples the bad section from the
good ones; plan 164 actually fixes the BAD DATA.

## Suggested order

Land after plan 159 (already in), and before plan 161
(section isolation — that plan is purely frontend UX and
inherits the parser fix as a pre-condition for non-empty sections).
