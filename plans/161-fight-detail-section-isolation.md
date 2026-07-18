# Plan 161 — fight-detail page: per-section error isolation

**Source:** E2E journey finding #4 (`plans/E2E-JOURNEY-2026-07-11.md`). **Severity:** MED (UX). **Effort:** M.

## Problem

`/fights/[id]` SSR-fetches several endpoints (`/events`, `/squads`, `/skills`, `/timeline`, `/timeline/players`). If **any one** fails (e.g. `/events` → 500 on a fight with non-normalized `time_ms`), the whole page renders a single **"Upstream error: 500"** and shows **nothing else** — even the sections whose endpoints returned 200 (`/squads`, `/skills`). Observed live in the E2E on a mis-parsed fight.

## Suggested fix

Decouple the per-section fetches so each renders independently:
- Fetch each section's data in its own error boundary (React `error.tsx` per segment, or per-section `try/catch` in the Server Component that renders an inline "this section is unavailable" panel instead of throwing to the page-level boundary).
- Sections that succeed render normally; only the failing section shows an error/empty state.

Net effect: a partially-corrupt fight still shows its working tables. Pairs well with a friendlier error string (UX reco #3). Frontend-only (`web/src/app/fights/[id]/`).
