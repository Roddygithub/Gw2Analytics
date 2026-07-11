# Plan 023 — Refresh stale documentation (ROADMAP, web/README, statechange-ids, GraphQL decision)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat f0249ef..HEAD -- docs/ web/README.md`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: docs
- **Planned at**: commit `f0249ef`, 2026-07-11

## Why this matters

Four docs issues waste contributor and maintainer time:

1. **`docs/ROADMAP.md`**: Lists "Cross-account comparison" and other features as "not yet implemented" — they shipped in v0.10.0. A maintainer reading this to decide priorities may re-implement or deprioritize already-shipped work.

2. **`web/README.md`**: Documents 3 routes (`/`, `/fights`, `/account`) but the actual app has 8+ pages including `/upload`, `/players`, `/players/[account_name]`, `/players/compare`, `/fights/[id]` + error boundaries.

3. **`docs/statechange-ids.md`**: Contains a raw shell template `$(grep -cE ...)` that was never expanded. Claims to be "Refreshed: 2026-07-07" but the template residue undermines trust.

4. **GraphQL subscription channel**: Multiple docs mention "GraphQL subscription channel" as planned (v0.9.0+, v1.0+), but the webhook system already covers push notifications. No explicit decision record exists, so the next contributor may waste cycles evaluating it.

## Current state

### `docs/ROADMAP.md`
See line ~52: "Cross-account comparison (v1.0 candidate, M effort, not yet implemented)" — shipped in v0.10.0.

### `web/README.md`
Lines 26-30: 3-row route table. Actual routes: `/`, `/fights`, `/fights/[id]`, `/upload`, `/players`, `/players/[account_name]`, `/players/compare`, `/account` = 8 pages + `error.tsx` + `not-found.tsx` + `loading.tsx` boundaries.

### `docs/statechange-ids.md`
Line 5: `**Total entries:** $(grep -cE '^\s+[A-Z][a-zA-Z0-9_]+\s*=\s*[0-9]+' /tmp/StateChange.cs.clean) + 1 (Unknown)` — unexpanded shell template.

### GraphQL in docs
- `docs/v0.8.0-backend-design.md:59`: "GraphQL subscription channel — out of scope for v0.8.0, target v0.9.0+"
- `docs/ROADMAP.md:~183`: "GraphQL subscription channel — v1.0+ strategic item"

## Scope

**In scope**:
- `docs/ROADMAP.md`
- `web/README.md`
- `docs/statechange-ids.md`
- `docs/` (potentially new decision record)

**Out of scope**:
- Code changes (no backend/frontend edits)
- CHANGELOG.md (maintained separately)

## Steps

### Step 1: Refresh `docs/ROADMAP.md`

- Move "Cross-account comparison" and any other shipped features to a "### Shipped" archival section (or strikethrough in the v1.0 section).
- Update the "Last refreshed" header to the current date.
- Re-estimate remaining candidates (if any changed).
- Keep the "what to build next" signal accurate.

**Verify**: `grep -c "not yet implemented" docs/ROADMAP.md` → fewer matches than before (or 0 for shipped items).

### Step 2: Update `web/README.md` route table

Replace the 3-row table with the full 8-row table:

| Route | Description |
|-------|-------------|
| `/` | Landing page with navigation cards |
| `/account` | GW2 API key → world enrichment |
| `/upload` | `.zevtc` combat log upload with 3-step wizard |
| `/fights` | Paginated fight list grid |
| `/fights/[id]` | Fight drilldown: events, timeline, squads, skills |
| `/players` | Cross-fight player list with profession filter |
| `/players/[account_name]` | Player profile with per-fight breakdown + timeline |
| `/players/compare` | Cross-account timeline comparison (2-4 accounts) |

Add a note about the 3 error/loading boundaries (`error.tsx`, `not-found.tsx`, `loading.tsx`) and the 7 Playwright screenshot fixtures.

**Verify**: `grep -c "|" web/README.md` → 8+ route rows.

### Step 3: Fix `docs/statechange-ids.md`

Either:
- Run the grep command and replace the shell template with the literal count, OR
- Add a prominent "**NOT IMPLEMENTED**" banner at the top explaining the statechange parser was never built, and archive the doc under `docs/archive/`.

**Verify**: `grep -c '\$(' docs/statechange-ids.md` → 0 (or file moved to archive).

### Step 4: Add GraphQL decision record

Create `docs/adr/001-graphql-subscription-channel.md` (or add a note to `docs/ROADMAP.md`) stating:

> **Decision**: GraphQL subscription channel is not planned. The webhook system (v0.9.1) covers push notifications via HMAC-signed HTTP callbacks. Any future GraphQL proposal must demonstrate a concrete user requirement that webhooks cannot satisfy.

**Verify**: File exists at `docs/adr/001-graphql-subscription-channel.md`.

## Test plan

No tests needed — documentation only.

## Done criteria

- [ ] ROADMAP.md accurately reflects shipped features
- [ ] web/README.md lists all 8 routes
- [ ] statechange-ids.md has no unexpanded shell template (or archived)
- [ ] GraphQL decision record exists
- [ ] No code files modified

## STOP conditions

Stop and report if:
- A shipped feature referenced in ROADMAP.md has unverifiable status (check git log / CHANGELOG).
- The route table in web/README.md doesn't match `find web/src/app -name 'page.tsx'`.

## Maintenance notes

Set a calendar reminder to refresh ROADMAP.md every major release. The `docs/adr/` directory should accumulate decision records for future architecture choices.
