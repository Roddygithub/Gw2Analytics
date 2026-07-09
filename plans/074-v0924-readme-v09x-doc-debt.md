# Plan 074 — README v0.9.x doc debt (Release Tags table + Phase history + Status line)

Drift base : `main` (3 commits ahead of origin).

## Problem

The README is the project's public landing page on github.com. It contains
**three independent drift bugs** that have accumulated across the
v0.9.0 / v0.9.1 / v0.9.2 cycles:

1. **`## Release Tags` table is missing v0.9.0 / v0.9.1 / v0.9.2.** The table
   ends at `v0.8.9` (`apps/api + web: per-account timeline ?tz=Continent/City
   + per-fight timeline section`). The 3 most recent cycles (which contain
   the **webhook subscription + delivery + retry + DLQ + replay** surface
   — the largest feature addition since v0.4.0) are completely invisible
   to a visitor. The table is the canonical "what was released" surface;
   its silence on v0.9.x makes the project look stale to anyone evaluating
   it from the README alone.

2. **`<details>` Phase history block ends at v0.8.9.** Same drift — the
   "Phase 0 → v0.8.9" summary in the collapsed block does not list any
   v0.9.x cycle. The block is meant to be the dev-history deep-dive
   (canonical per-release content lives in `CHANGELOG.md`; the block is
   one click away for developers who want the dev history). Silently
   ending at v0.8.9 contradicts the CHANGELOG.

3. **`**Status:**` headline line is misleading.** It reads:

   > `v0.9.0 + v0.9.1 + v0.9.2 close-out committed on `main` (not yet
   > released; tag pending operator ceremony)`

   But the CHANGELOG has a `## [0.9.2]` header with a
   `compare/v0.9.1...v0.9.2` link, and a `## [0.8.8] → ## [0.8.9] →
   ## [Unreleased]` ordering. The headline's framing ("close-out
   committed on main, not yet released") is the v0.9.0-→v0.9.2 cycle
   position, but the v0.9.2 release line in the CHANGELOG suggests it
   WAS released at one point. A visitor reading the headline will not
   know whether to trust the README or the CHANGELOG. (Per plan 075 the
   `[Unreleased]` link is `compare/v0.8.8...HEAD` not `compare/v0.9.2...HEAD`,
   so the CHANGELOG is also stale on the same axis — both files drift in
   the same direction.)

The 3 bugs are symptoms of the same root cause: the README was last
substantively updated for the v0.8.8 polish pass (per the CHANGELOG's
own `### Changed (docs - README professional polish)` entry), and the
3 v0.9.x cycles were shipped without a corresponding README refresh.

## Fix

Three small doc-only edits to `README.md`. No code changes. No new
files. Mirrors the discipline the project established for the v0.8.8
README polish (a single commit scoped to "docs - README refresh"; the
CHANGELOG entry will be added at the v0.9.x close-out).

### Edit 1 — `## Release Tags` table (3 new rows + 1 row reorder)

Insert 3 new rows in the table after the existing `v0.8.9` row, in
strict chronological order:

```markdown
| `v0.9.0` | `apps/api` | Webhook subscriptions + delivery worker (HMAC-SHA256 signed, 3-attempt retry, DLQ, replay, SSRF HTTPS-only block). |
| `v0.9.1` | `apps/api` | Webhook hardening slice: schema `int`→`str` discriminator + universal SSRF block + BG-task closed-session fix + retry+DLQ+replay tests + OpenAPI drift gate functional baseline. |
| `v0.9.2` | `apps/api` | Webhook correctness hardening: `webhook_deliveries.payload` + `webhook_dlq.payload` `JSONB`→`LargeBinary` for HMAC byte-for-byte integrity + DLQ-replay row-level lock + discriminator-encoding docstring convention + 2 pre-existing test fixes + test isolation conftest. |
```

(Each cell is 1-line per the v0.8.8 polish convention; the full per-commit
detail is in `CHANGELOG.md`.)

No reordering of existing rows. The pre-v0.8.9 rows are correct as-is
(the table already ends at v0.8.9 in the right order).

### Edit 2 — `<details>` Phase history block (3 new bullet entries)

Insert 3 new bullet lines at the end of the collapsed block, after
`v0.8.9`:

```markdown
✅ **v0.9.0** — `apps/api`: webhook subscription + delivery worker (HMAC-SHA256 signed, SSRF block, atomic per-upload commit).
✅ **v0.9.1** — `apps/api`: webhook hardening slice (5 audit plans: schema int→str, universal SSRF, BG-task closed-session fix, retry+DLQ+replay tests, OpenAPI drift gate).
✅ **v0.9.2** — `apps/api`: webhook correctness hardening (payload JSONB→LargeBinary for HMAC byte-for-byte integrity + DLQ-replay row-level lock + test isolation conftest).
```

(3 new `✅` lines, matching the v0.8.0 → v0.8.9 lineage. No edits to
existing bullets — the pre-v0.8.9 lines are correct as-is.)

### Edit 3 — `**Status:**` headline line

Replace the existing 1-line Status headline with a 3-line rewrite that
matches the actual state:

```markdown
**Status:** Latest tagged release: `v0.9.2` · v0.9.0 + v0.9.1 + v0.9.2
form the **3-cycle webhook hardening arc** (HMAC-signed delivery +
SSRF block + retry/DLQ/replay + payload byte-integrity) · **339
active tests** across pytest + vitest + Playwright · strict CI lint +
test + typecheck + OpenAPI drift gate active.
```

The 3-line format mirrors the v0.8.8 polish ("Tightened the
`**Status:**` headline from a 200+ char run-on sentence to 2 lines").
The 3 new lines:

1. **Latest tagged release: `v0.9.2`** — corrects the v0.8.9 stale
   value.
2. **3-cycle webhook hardening arc** — surfaces the 3 v0.9.x cycles as
   a single coherent feature arc (the visitor immediately understands
   the project's "current focus"; matches the discipline of the
   `## Highlights` 5-bullet section).
3. **339 active tests + CI gates** — verbatim from the existing
   headline (no change; the test count is correct per the v0.9.2
   close-out).

The 3-line format matches the v0.8.8 polish line-count convention
("2 lines" → "3 lines" is a 1-line delta, not a regression to a
200-char run-on).

## Files modified

- `README.md` (3 edits, ~10 lines added total — 3 Release Tags rows +
  3 Phase history bullets + 1 Status headline replacement of 1 line by
  3 lines = net +5 lines; 0 deletions).

## CHANGELOG entry to add at v0.9.x close-out

```markdown
### Changed (docs - README v0.9.x doc debt)

- `README.md`: 3 doc-only edits scoped to the v0.9.x cycle's
  README drift:
  * `## Release Tags` table gains 3 rows for `v0.9.0` (webhook
    subscriptions + delivery worker), `v0.9.1` (hardening slice:
    schema fix + SSRF block + BG-task fix + retry/DLQ/replay tests +
    OpenAPI drift gate), and `v0.9.2` (correctness hardening:
    payload `JSONB`→`LargeBinary` + DLQ-replay row-level lock +
    test isolation conftest). Each cell is 1-line per the v0.8.8
    polish convention; per-commit detail lives in `CHANGELOG.md`.
  * `<details>` Phase history block gains 3 `✅` bullets for the
    same 3 cycles, matching the pre-v0.8.9 lineage format.
  * `**Status:**` headline replaced with a 3-line rewrite: latest
    tagged release is now `v0.9.2` (was `v0.8.9`); surfaces the
    "3-cycle webhook hardening arc" as the project's current
    focus; preserves the existing "339 active tests + strict CI
    gates" line verbatim. The 3-line format matches the v0.8.8
    polish line-count convention.
  No code changes; the `## Highlights` + `## Documentation` +
  `## API surface` + `## Screenshots` + `## Quickstart` + `##
  Architecture` sections are preserved verbatim.
```

## Validation

- `git diff README.md` shows the 3 edits cleanly; no other lines
  modified.
- The 3 new Release Tags rows are in strict chronological order
  (after `v0.8.9`, before any future `v0.9.3`).
- The 3 new Phase history bullets match the v0.8.0 → v0.8.9 line
  format (`✅ **vX.Y.Z** — <scope>: <one-line summary>`).
- The new `**Status:**` headline is 3 lines, not a run-on.
- `gh view --web` (or the GitHub UI) renders the table + the
  collapsed block + the new headline correctly. (Out-of-scope
  for CI; the README polish is a human-eyeball test.)

## Rejected alternatives

1. **Auto-generate the Release Tags table from the CHANGELOG.** Would
   couple the README to the CHANGELOG parser (the project has no such
   tool; would require a new dep). The 3-row manual edit is ~3 minutes
   of work and 0 deps. Rejected.
2. **Add a separate "Webhook hardening arc (v0.9.0 → v0.9.2)" callout
   section.** The v0.8.8 polish removed the verbose phase paragraphs
   in favour of `## Highlights` (5-bullet) + `## Release Tags` (25-row
   table). Adding a 4th top-level section would re-introduce the
   clutter. The 3-line Status headline + the 3 new table rows surface
   the same information in 2 places without adding a new section.
   Rejected.
3. **Refresh the `<details>` block to v0.9.2 in a single edit covering
   all 3 cycles' detailed narrative.** The v0.8.8 polish deliberately
   collapsed the per-cycle narrative (the CHANGELOG is the canonical
   per-commit history; the collapsed block is the 1-line dev-history
   summary). Re-introducing the narrative would re-clutter the
   landing page. Rejected.
4. **Use a sed/awk script to auto-refresh the table from CHANGELOG
   headings.** Would couple the README to the CHANGELOG's heading
   structure; the project does not have a doc-codegen pipeline for
   the README (the v0.8.8 polish explicitly chose "single manual
   edit" over a codegen tool). Rejected.
5. **Reorder the existing v0.8.x rows to interleave with v0.9.x.**
   Would muddle the chronology (v0.8.x is a coherent phase — the
   Phase 9 web arc — and the v0.9.x rows are the post-Phase-9
   webhook hardening arc). Strict chronological append is the
   v0.8.8 convention. Rejected.
