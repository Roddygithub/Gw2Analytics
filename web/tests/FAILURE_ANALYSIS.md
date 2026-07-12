# v0.10.17 D3 Failure Analysis — web vitest pre-existing failures

**Cycle:** v0.10.17
**Phase:** Phase 3 (C1+C2 deferred from v0.10.16)
**Date:** 2026-07-12
**D3 deliverable:** v0.10.16 deferred D1-D4 work — fix 7 pre-existing vitest failures in the per-fight drill-down page tests.

---

## TL;DR

All 7 pre-existing vitest failures in ``web/tests/app/fight-events-page.test.tsx`` are the SAME failure class (F-VT-CLASS-1: mock-strategy-vs-runtime-substrate mismatch), fixed via ONE atomic change (swap the mock target from ``@/lib/api`` to ``@/lib/fetchCached`` so the mock intercepts the page's actual runtime round-trips).

- **Count:** 7 failures -> 0 failures (post-D3)
- **Test file:** ``web/tests/app/fight-events-page.test.tsx``
- **Diagnosis:** 2 LoC miss; v0.8.9 plan/002 added the 5th fetcher (per-fight player timeline) but the test fixture set was never extended to mock it. The bigger architectural miss: the ``@/lib/api`` mocks were STRUCTURAL NO-OPS because the page.tsx imports those functions ONLY as TypeScript type constraints (erased at runtime).
- **Fix components:**
  1. vi.mock target swap: ``@/lib/api`` -> ``@/lib/fetchCached`` (1 line of vitest setup; the mock now intercepts the page's actual ``fetchCached(url, init)`` calls).
  2. ``mockFightFetch({ events, squads, skills, timeline, playerTimeline })`` helper (URL-keyed dispatch; longest substring FIRST so ``/timeline/players`` matches before ``/timeline``).
  3. ``POPULATED_PLAYER_TIMELINE`` fixture added (the 5th fetcher — was missing in pre-D3 fixture set).

---

## F-VT-CLASS-1: mock-strategy-vs-runtime-substrate mismatch

### Affected tests (7 of 7 in the file, all failing pre-D3)

The pre-D3 test failures share one root cause: the test's ``vi.mock("@/lib/api", ...)`` replaced ``fetchFightEvents``, ``fetchFightSquads``, ``fetchFightSkills``, ``fetchFightTimeline`` with ``vi.fn()`` stubs. But the page.tsx Server Component imports those name from ``@/lib/api`` ONLY as TypeScript type constraints (the ``import("@/lib/api").FightSquads`` shape is type-only and is erased at runtime). The page's actual runtime calls go through ``fetchCached`` (from ``@/lib/fetchCached``) which internally calls ``globalThis.fetch(url, init)``. In jsdom, native ``fetch`` for an arbitrary URL rejects with a network error, and the page renders the upstream-error card with ``<p>404: fetch failed</p>`` (the pattern seen on all 7 failures).

Additionally, the v0.8.9 plan/002 added a 5th fetcher (``fetchFightPlayerTimeline`` for the per-fight per-player timeline) without extending the test fixture set; the page fired the 5th call but the test never mocked it. Post-D3 the ``POPULATED_PLAYER_TIMELINE`` fixture covers this gap.

### Tests in the file (all 7 covered by the F-VT-CLASS-1 fix):

| Index | Test name (post-D3) | Pre-D3 status |
|-------|---------------------|---------------|
| 1 | renders the header + section headings when fetchCached returns a populated payload | FAIL |
| 2 | renders the upstream-error card when fetchCached throws for /events | FAIL |
| 3 | renders the header + section headings on empty roll-ups (parser yielded zero events) | FAIL |
| 4 | forwards searchParams.window_s to the gateway URL via fetchCached (window-s selector wiring) | FAIL |
| 5 | clamps an out-of-range window_s to the gateway default (no upstream 422) | FAIL |
| 6 | filters the three roll-up tables to a single target when ?target=N is set | FAIL |
| 7 | falls back to the unfiltered view when ?target= is malformed | FAIL |

### Fix verification

```bash
cd web
pnpm vitest run tests/app/fight-events-page.test.tsx --reporter=verbose
# Expected: 7/7 PASS (pre-D3: 7/7 FAIL)
```

### Why this is ONE class + ONE fix (per the audit taxonomy)

All 7 failures share:
- Common SOURCE: ``@/lib/api`` is type-only in page.tsx; runtime goes through ``fetchCached`` (which is NOT mocked).
- Common FIX: swap ``vi.mock`` target to ``@/lib/fetchCached`` + add a per-URL dispatch helper ``mockFightFetch`` that maps URL -> fixture.
- Common ROOT: the test was designed before v0.7.1 (when page.tsx spawned 3 parallel fetchers via ``Promise.allSettled``); v0.8.9 plan/002 added a 5th fetcher + the duck-typed ``vi.mock("@/lib/api")`` shortcut silently regressed to a no-op.

A per-test classification (F-VT-1 through F-VT-7) would obscure the common fix; a single F-VT-CLASS-1 with the shared fix description is the cleaner documentation.

### Anti-regression pin

A future maintainer who reintroduces the ``vi.mock("@/lib/api")`` mock strategy will immediately fail ALL 7 tests because the mock will become a no-op. The post-D3 ``vi.mock("@/lib/fetchCached")`` is the durable contract. A grep for ``vi.mock("@/lib/api"`` in the test file should return 0 matches (negative regression-pin).

---

## Carry-forward

The 5th-fetcher story (v0.8.9 plan/002 added per-fight player-timeline) deserves a future audit: the page's runtime signature changed but other test files referencing the page (e.g. e2e tests in ``web/tests/e2e/``) may also lack matching fixtures. A future cycle could:
- Run ``pnpm vitest run --reporter=verbose 2>&1 | grep -E 'FAIL|fetch failed'`` to spot any remaining mock-substrate issues.
- Audit all test files importing from ``@/lib/api`` to confirm runtime-vs-type distinction.

Not in v0.10.17 scope; noted for the next cycle end audit.
