# Plan 076 — README test count breakdown table

Drift base : `main` (3 commits ahead of origin).

## Problem

The README's `**Status:**` headline (per plan 074's edit) and the
`## Highlights` section both reference "**339 active tests**" as a
single aggregate number across `pytest` + `vitest` + `Playwright`.
The headline reads:

> **339 active tests** across pytest + vitest + Playwright

And the `## Highlights` section reads:

> 🧪 **339+ automated tests** across `pytest` (241), `vitest` (82),
> and `Playwright` e2e (16) — all green on every PR.

Two drift bugs:

1. **The arithmetic is not transparent to a visitor.** The 3-component
   breakdown (241 + 82 + 16 = 339) is in the `## Highlights` bullet,
   but the `**Status:**` headline just says "339 across pytest +
   vitest + Playwright" — a visitor who only reads the headline
   doesn't know the per-suite counts. The `## Highlights` bullet
   has the per-suite numbers but they're in a sentence, not a
   scannable table.

2. **The "241 pytest" figure is the total Python test count across
   the monorepo** (the 4 libs + apps/api), but the v0.9.2 CHANGELOG
   section's validation table says "**apps/api pytest: 92 pass / 0
   fail / 3 skip**" — which is the apps/api subset only. A visitor
   reading the CHANGELOG might confuse "241 pytest" with "241 apps/api
   pytest" and expect a different number. The README currently does
   not break down the 241 into the apps/api vs libs/gw2_* split.

3. **The "+" in "339+" is stale.** Originally, the "339+" was a
   forward-compatibility marker ("at least 339, probably more as we
   add tests"). At the v0.9.2 close-out the actual count is 339
   exactly (241 + 82 + 16 = 339, no rounding). The "+" is a
   vestigial safety margin that no longer reflects reality; a
   visitor reading "339+" might assume the count is fuzzy when it
   is not.

## Fix

Two doc-only edits to `README.md`. No code changes. No new files.
Mirrors the discipline the project established for the v0.8.8 README
polish (CHANGELOG-style 1-commit scope: "docs - README test count
breakdown").

### Edit 1 — Add a `## Test coverage` section (NEW)

Insert a new top-level section between `## Architecture` and `## API
surface` (the natural reading flow: "what's the project" →
"how is it tested" → "what endpoints does it expose"):

```markdown
## Test coverage

| Suite | Count | Scope | CI step |
| --- | --- | --- | --- |
| `pytest` (libs) | 149 | `libs/gw2_core` + `libs/gw2_evtc_parser` + `libs/gw2_analytics` (frozen Pydantic shapes, deterministic ordering, cross-field invariants) | `uv run pytest libs/` |
| `pytest` (apps/api) | 92 | `apps/api` routes + workers + scripts + migrations (e2e with `TestClient` + transactional Postgres) | `uv run pytest apps/api/tests/` |
| `vitest` | 82 | `web/` component + app + lib unit tests (SSR fetcher mock pattern, jsdom component rendering) | `pnpm test:unit` |
| `Playwright` | 16 | `web/` end-to-end (6 spec files: fights / players / landing / account / upload / visual-regression) | `pnpm exec playwright test` |
| **Total** | **339** | (241 pytest + 82 vitest + 16 Playwright) | |

The 92 apps/api pytest is the v0.9.2 close-out count (90 + the 2
pre-existing test fixes per CHANGELOG `[0.9.2]`); the 149 libs
pytest is the remainder (241 total - 92 apps/api). The vitest + 92
apps/api figures match the v0.9.2 CHANGELOG's "Test totals" line
("241 -> 241 pytest + 82 vitest (unchanged) + 16 playwright
(unchanged)"). The 16 Playwright count includes the 5 visual-regression
specs in `web/tests/e2e/visual-regression.spec.ts`.
```

The 5-row table is the canonical "where the 339 comes from"
breakdown. The 4-row body + 1-row total mirrors the `## API surface`
table's pattern (5 columns: Suite / Count / Scope / CI step; 4 body
rows + 1 total row).

### Edit 2 — Update the `## Highlights` bullet to drop the "+"

Replace the existing:

> 🧪 **339+ automated tests** across `pytest` (241), `vitest` (82),
> and `Playwright` e2e (16) — all green on every PR.

With:

> 🧪 **339 automated tests** across `pytest` (241), `vitest` (82),
> and `Playwright` e2e (16) — all green on every PR. See the `## Test
> coverage` section for the per-suite breakdown.

The 1-line change drops the stale "+" + adds a pointer to the new
section. (The 4 numbers are preserved verbatim — they match the
v0.9.2 close-out state.)

### Edit 3 — Update the `**Status:**` headline to match the new exact count

Per plan 074's edit, the new `**Status:**` headline is:

> **Status:** Latest tagged release: `v0.9.2` · v0.9.0 + v0.9.1 + v0.9.2
> form the **3-cycle webhook hardening arc** (HMAC-signed delivery +
> SSRF block + retry/DLQ/replay + payload byte-integrity) · **339
> active tests** across pytest + vitest + Playwright · strict CI lint +
> test + typecheck + OpenAPI drift gate active.

Drop the "+" if it appears (it currently does not in the v0.8.8
polish, but verify). The "**339 active tests**" line stays — the
table in `## Test coverage` is the drill-down.

## Files modified

- `README.md` (3 edits, ~15 lines added — 1 new `## Test coverage`
  section of ~12 lines + 1 `## Highlights` bullet line edit + 1
  `**Status:**` headline line edit (no-op if the "+" is already
  absent)).

## CHANGELOG entry to add at v0.9.x close-out

```markdown
### Added (docs - README test coverage breakdown)

- `README.md`: new `## Test coverage` section between `##
  Architecture` and `## API surface`. 4-row + 1-total table
  (pytest libs 149 + pytest apps/api 92 + vitest 82 + Playwright
  16 = 339 total) with the per-suite scope + the matching CI
  step for each suite. The 92 apps/api pytest figure matches the
  v0.9.2 close-out count (90 + 2 pre-existing test fixes); the
  149 libs pytest is the remainder (241 total - 92 apps/api).
  No code changes; the `## Highlights` bullet drops the stale
  "339+" → "339" and adds a pointer to the new section; the
  `**Status:**` headline's "339 active tests" line is unchanged.
```

## Validation

- `git diff README.md` shows the 3 edits cleanly; no other lines
  modified.
- The 4 + 1 table sums to 339 (149 + 92 + 82 + 16 = 339).
- The 4 CI steps in the table match the 4 commands the project's
  CI workflow runs (per `.github/workflows/ci.yml`):
  - `uv run pytest libs/`
  - `uv run pytest apps/api/tests/`
  - `pnpm test:unit`
  - `pnpm exec playwright test`
- The `## Highlights` bullet's "339" matches the `## Test
  coverage` table's "**Total** | **339**" row exactly.
- The `**Status:**` headline's "339 active tests" matches both.

## Rejected alternatives

1. **Add a "Last refreshed" timestamp to the table.** Would
   introduce a maintenance burden (the table needs to be
   hand-updated on every test count change; the project has no
   CI gate that updates the README on test count drift). The
   CHANGELOG's "Test totals" line is the canonical per-cycle
   count; the README's table is the at-a-glance summary. Rejected.
2. **Auto-generate the table from `uv run pytest --collect-only
   -q | wc -l` + `pnpm test:unit --list | wc -l` + `pnpm exec
   playwright test --list | wc -l`.** Would couple the README
   to a shell pipeline; the v0.8.8 polish explicitly chose
   "single manual edit" over a codegen tool for the `## API
   surface` table. The 4 hand-written rows are 1 minute of
   work and 0 deps. Rejected.
3. **Break down the 92 apps/api pytest into routes/workers/scripts
   sub-counts.** Would be useful for a developer triaging a
   failure, but the visitor-facing scope of the README is
   "apps/api as a whole"; the sub-breakdown is the
   `apps/api/tests/` directory listing (one folder per
   concern). The 4-row + 1-total granularity is the right
   level for the landing page. Rejected.
4. **Move the test counts into a separate `docs/TESTING.md`
   and link from the README.** Would split a 4-row table
   across 2 files; the visitor has to follow a link to see
   the per-suite breakdown. The whole point of the new
   section is to make the breakdown 1-click away on the
   landing page. Rejected.
5. **Add a "Coverage %" column to the table.** The project
   does not use `coverage.py` or `c8` (per `web/package.json`
   + `apps/api/pyproject.toml` — no `coverage` dep). The %
   column would be all-N/A or omitted. Rejected.
