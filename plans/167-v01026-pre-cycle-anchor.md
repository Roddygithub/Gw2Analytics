# Plan 167 — v0.10.26-pre — Cycle anchor (formalizes scope + ordering)

**Source:** This landing commit (post-`1813881` + post-`e250623`) opens
the cycle window for the 5 E2E-deferred + carryforward plans:
`plans/159` (already shipped via `edacc4b`), `plans/160..163` (opened
in `1813881`), `plans/164..166` (opened in `e250623`), `plan/167`
(this file).
**Severity:** N/A (anchor spec — no code change).
**Effort:** XS (cal only).
**Drift base:** `e250623` (post-`1813881` head).

## Why this plan exists

The mimo-half cycle that just landed brought the FOLLOWUP backlog
to:

- 1 fix already shipped (`edacc4b` = plan 159 timeline guard).
- 4 plans opened (`1813881` = plans 160, 161, 162, 163).
- 3 plans opened (`e250623` = plans 164, 165, 166).
- 1 LICENSE + README sync shipped (`f5bef7d`).
- 2 surgical python fixes shipped (`8bf41c4` = BarrierEvent dedup,
  RUF059 underscore).

That is 7 plans to land across 4-6 calendar mimo-half cycles. Without
a cycle anchor, each plan's README would have to rebuild the
cross-plan dependency graph from scratch.

## Cycle topology

```
e250623 (head)
  |
  +-- [M-1] plan 164 (parser time_ms + skill-table, L)   ──┐
  |                                                          │
  +-- [M-1] plan 163 (PlayerSearchBar hydration, S)       │ parallel
  |                                                          │
  +-- [M-2] plan 161 (section isolation, M)   ◄────────────┤ depends on 164
  |                                                          │
  +-- [M-2] plan 162 (timeline/players perf, M)  ◄─────────┤ parallel to 161
  |                                                          │
  +-- [M-3] plan 165 (vitest migration, M)   ───── independent
  |
  +-- [M-3] plan 160 (fight_id collision, S)   ◄──── depends on operator (a or b)
```

(`159` is shipped; `166` is analysis-only already shipped.)

## Cycle-by-cycle signature

### Wave 1 — v0.10.26-pre

- **[M-1] plan 164** — parser-side `time_ms` normalization +
  skill-table re-read (closes the root cause bug #2 of
  E2E-JOURNEY findings; unblocks `plan 161` non-empty rendering).
- **[M-1] plan 163** — `PlayerSearchBar` hydration mismatch
  (frontend-only S effort).

### Wave 2 — v0.10.26

- **[M-2] plan 161** — per-section error isolation on
  `/fights/[id]` (frontend-only M effort; `web/src/app/fights/[id]/page.tsx`).
- **[M-2] plan 162** — `/fights/{id}/timeline/players` lazy-load
  (M effort; backend+frontend split).

### Wave 3 — v0.10.27-pre

- **[M-3] plan 165** — carryforward vitest migration (`plans/168`
  carries the 5-bullet recipe).
- **[M-3] plan 160** — `fight_id` collision (operator picks (a)
  idempotent or (b) 409 — see `plans/160` §"Suggested fix" + §"Decision needed").

## Operator handoff checklist

- [ ] Confirm cycle-by-cycle cal dates with maintainer (this plan
      sets the order; the cal is the operator's call).
- [ ] Plan 160 decision: (a) idempotent OR (b) 409. Pick one before
      the v0.10.26 cycle authorization.
- [ ] Plan 164 Stage 2 cross-link to libs/gw2_skills SCAFFOLD
      (already in plan doc) — covers the placeholder-vs-catalog
      fallback sequencing.
- [ ] Plan 165 recipe (5-bullet migration to `renderWithSession`
      helper) lives in `plans/168`. Read before starting Wave 3.
- [ ] Plan 166 (already-shipped) acts as the cal ship-target;
      use it as the source of truth for cycle shipts.

## Cross-link audit trail

- `plans/E2E-JOURNEY-2026-07-11.md` — the journey that surfaced
  bugs 1-7 (#1 shipped in `159`/`edacc4b`).
- `plans/159..166` — per-plan spec.
- `plans/168-vitest-implementation.md` — M-3 sub-recipe for plan 165.
- `docs/ROADMAP.md` — refresh at v0.10.27-pre cycle closure.
