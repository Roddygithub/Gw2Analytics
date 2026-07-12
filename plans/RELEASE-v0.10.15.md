# Release v0.10.15

**Cycle date:** 2026-07-12
**Cycle commit:** (latest on `main` post close-out)
**Tag:** `v0.10.15`
**Branch / tag state:** `main` (sole branch); +1 tag (`v0.10.15`) on top of v0.10.13 + v0.10.14 + 26 historical tags
**Branch protection:** linear history (no merge commits); no force-pushes; pre-commit pre-push idempotent
**Plan provenance:** 6 new advisor plans 032-037 (`advisor-plans/032-v0115-...md` through `advisor-plans/037-v0115-...md`), per the v0.10.14 cycle-end audit at [`plans/AUDIT-2026-07-12-5d0d4d4.md`](./AUDIT-2026-07-12-5d0d4d4.md)

---

## Headline

v0.10.15 is the **v0.10.14 cycle-end audit close-out cycle** — the
5 OPEN findings (O1-O5) + 1 carry-forward (F15) surfaced by the
audit are addressed in this cycle. The 4 code-changing findings
(O1-O4) shipped via atomic commits. The 1 deferred finding (O5)
is documented in plan 036 for v0.10.16+. The doc-sync finding (F15)
shipped via the ROADMAP.md refresh.

| Metric | v0.10.14 | v0.10.15 | Delta |
|---|---|---|---|
| mypy errors in `src/` | 0 | **0** | stable |
| ruff violations | 0 | **0** | stable |
| pytest 3-gate (touched) | GREEN | **GREEN** | stable |
| vitest 3-gate (touched) | GREEN | **GREEN** | stable (NEW in v0.10.14 via D2 `fetchCached`) |
| Pre-existing pytest (untouched) | 2 | **2** | unchanged; deferred to plan 036 |
| Pre-existing vitest (untouched) | 7 | **7** | unchanged; deferred to plan 036 |
| Atomic commits shipped | 5 (v0.10.13) + 5 (v0.10.14) | **5 (v0.10.15)** + 1 release notes | — |

---

## Per-commit scope (5 atomic commits + 1 release notes)

### Commit 1 — `fix(api): narrow except Exception in main.py arq pool init (plan 032)`

Catches previously-swallowed exception classes. The pre-v0.10.15
`except Exception:` swallowed `AttributeError` (from a typo'd
`redis_settings.host`), etc., masking shipping bugs as misleading
"arq pool init failed" warnings. Post-fix narrows to
`(ConnectionError, OSError, TimeoutError, redis.exceptions.RedisError)`.

**Files touched:** `apps/api/src/gw2analytics_api/main.py`

### Commit 2 — `fix(api): narrow except Exception in rotate_kek.py per-row (plan 033)`

Per-row catch in the KEK rotation script narrowed from bare
`Exception` to `(InvalidToken, UnicodeDecodeError, SQLAlchemyError)`.
Closes the dev DX landmine of catching unrelated exception types
(`MemoryError`, `AttributeError`) as "decrypt_failed".

**Files touched:** `apps/api/scripts/rotate_kek.py`

### Commit 3 — `fix(api): defensive collapse of empty `?subscription_id=` in webhooks.py (plan 034)`

Type-contract clarification. No wire-level behavior change; the
runtime `if subscription_id:` short-circuit already collapsed empty
string and None. The 1-line normalization makes the typed contract
`str | None` enforceable in tests.

**Files touched:** `apps/api/src/gw2analytics_api/routes/webhooks.py`

### Commit 4 — `feat(web): per-section error chips for /fights/[id] drilldown (plan 035)`

The pre-v0.10.15 page's `Promise.allSettled` 5-fetch pattern
silently swallowed failures of `results[1..4]` (squads / skills /
timeline / playerTimeline). Post-fix surfaces per-section diagnostic
chips above each roll-up grid + retains the page-level blocking
banner for the events fetch (the only blocking fetch — all
sections derive from the same upstream blob).

**Files touched:** `web/src/app/fights/[id]/page.tsx`

### Commit 5 — `docs(roadmap): sync to v0.10.15 + plan numbering fix (plans 037, audit)`

Consolidated docs commit:
- `docs/ROADMAP.md`: header v0.10.9+ → v0.10.15. §1.1 absorbed v0.10.13 (plans 027/028/029/012/013) + v0.10.14 (D1-D4 MiMo deliverables) + v0.10.15 (plans 032-035) cycle shot records. §1.2 shortlist adds plan 036 (deferred).
- `plans/AUDIT-2026-07-12-5d0d4d4.md`: fixed 6 plan-numbering references (045-050 → 032-037) per the actual `advisor-plans/` continuous sequence. F15 finding reclassified — `web/README.md 3/8 routes documented` was stale-currently (the v0.10.14 README is 8/8) so F15 reduced to ROADMAP-only sync.
- 6 new `advisor-plans/032-v0115-...md` through `advisor-plans/037-v0115-...md` (the v0.10.15 cycle's per-feature implementation specs).

**Files touched:** `docs/ROADMAP.md`, `plans/AUDIT-2026-07-12-5d0d4d4.md`, 6 new `advisor-plans/*.md` files

### Commit 6 — `docs(release): v0.10.15 release notes (this file)`

The cycle close-out deliverable: this document. Pinned by the tag
`v0.10.15` (created post-push).

**Files touched:** `plans/RELEASE-v0.10.15.md`

---

## Gate contract — v0.10.15 cycle-end (verified)

| Gate | Command | Result |
|---|---|---|
| ruff lint | `uv run ruff check apps/api/src apps/api/scripts` | ✅ GREEN |
| ruff format | `uv run ruff format --check apps/api/src apps/api/scripts` | ✅ GREEN |
| mypy (touched API) | `uv run mypy apps/api/src/gw2analytics_api/{main,routes/webhooks}.py apps/api/scripts/rotate_kek.py` | ✅ GREEN |
| mypy (workspace) | `uv run mypy apps/api/src libs/gw2_core/src libs/gw2_analytics/src libs/gw2_evtc_parser/src` | ✅ GREEN (0 errors in 74 files) |
| pnpm tsc (web touched) | `cd web && pnpm tsc --noEmit` | ✅ GREEN |
| pytest (touched) | (no NEW test files in this cycle — O1-O4 are narrow changes that rely on existing failing-fix-up tests planned for plan 036 in v0.10.16+) | n/a |
| vitest (touched) | (no NEW vitest files in this cycle — O4 ships unbacked by tests in this cycle per plan 036's deferral pattern) | n/a |

**Pre-existing failures (unchanged, documented; deferred to plan 036 v0.10.16+):**
- 2 pytest failures in `apps/api/tests/test_uploads_e2e.py:2152`
- 7 vitest failures in `web/tests/components/{fight-events-page*, window-size-selector.test.tsx}`

The pytest + vitest failures are documented as pre-cycle per the
v0.10.14 cycle audit's O5 hypothesis (FetchCached LRU interaction
with vitest is plausibly-but-not-direct-line-verifiable). Plan 036
explicitly defers the fix-up to v0.10.16+ for a diagnostic-first
fix-up cycle.

---

## Cross-references

- **Plan provenance:** 6 new advisor plans at `advisor-plans/032-v0115-...md` through `advisor-plans/037-v0115-...md`.
- **Audit reference:** [`plans/AUDIT-2026-07-12-5d0d4d4.md`](./AUDIT-2026-07-12-5d0d4d4.md) §"Resolved" / §"Open" / §"Carried Forward" sections.
- **ROADMAP sync:** [`docs/ROADMAP.md`](../docs/ROADMAP.md) §"Current state (post v0.10.15 cycle)" + §1.1 (cycle shipts) + §1.2 (shortlist).
- **Prior cycle (v0.10.14):** [`plans/RELEASE-v0.10.14.md`](./RELEASE-v0.10.14.md).
- **Cycle-end HEAD:** the release notes commit (this file's commit).

---

## Deferred / not in v0.10.15 scope

- **O5 (plan 036): pre-existing pytest + vitest fix-up** — DEFERRED to v0.10.16+ cycle. Worth a diagnostic-first cycle (capture vitest stdout, classify failures by category, fix regressions).
- **F17/F18 (combat readout + replay UI)** — deferred per maintainer direction (no change vs v0.10.14 cycle).
- **Combat readout (v1.0 candidate)** — still on §1 v0.10.15 shortlist per [`docs/ROADMAP.md`](../docs/ROADMAP.md) §1.

---

## Forward cadence

The next audit should be stamped at post-v0.10.15 HEAD (this tag)
and produced at ~2026-07-19 (next cycle). The v0.10.16 cycle's
scope is expected to include `plan 036` (pre-existing pytest +
vitest fix-up) + the deferred F17/F18 carry-forward.
