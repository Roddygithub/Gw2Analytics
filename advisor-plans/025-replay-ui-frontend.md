# Plan 025 — Webhook replay UI frontend

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat f0249ef..HEAD -- web/src/ apps/api/src/gw2analytics_api/routes/webhooks.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding.

## Status

- **Priority**: P3
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none (backend replay endpoint already exists)
- **Category**: direction
- **Planned at**: commit `f0249ef`, 2026-07-11

## Why this matters

The backend has a working replay endpoint (`POST /api/v1/webhooks/dlq/{delivery_id}/replay`) shipped in v0.9.1, but there is **no frontend UI** for it. Analysts must `curl` the endpoint to replay a failed delivery. A DLQ list page with a "Replay" button per row would close the operational loop without any backend changes.

## Current state

- Backend: `apps/api/src/gw2analytics_api/routes/webhooks.py` — `POST /api/v1/webhooks/dlq/{delivery_id}/replay` exists and is tested
- Frontend: `web/src/app/` has an `/account` page but no `/webhooks` or DLQ management page
- `web/src/lib/api.ts` — likely has no `replayDlq` fetch function exposed (or it exists but has no UI caller)

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Install | `pnpm install` | exit 0 |
| Typecheck | `pnpm typecheck` | exit 0 |
| Test | `pnpm test:unit` | all pass |
| Generate API | `pnpm generate:api` | exit 0 |

## Scope

**In scope**:
- `web/src/app/webhooks/` (NEW — route group with DLQ list page)
- `web/src/components/WebhookDlqGrid.tsx` (NEW — AG Grid table showing failed deliveries)
- `web/src/lib/api.ts` (or `api/webhooks.ts` from plan 021) — ensure `fetchWebhookDeliveries` and `replayDlq` are callable
- `web/tests/` (NEW — component and page tests)

**Out of scope**:
- Backend changes (no routes/models/endpoints)
- Webhook subscription creation/editing UI (future feature)
- Authentication/authorization for the webhook page

## Steps

### Step 1: Add/verify API client functions

Ensure `api.ts` (or `api/webhooks.ts`) has:
- `fetchWebhookDeliveries()` → fetches DLQ delivery list (check the backend for the exact endpoint, likely `GET /api/v1/webhooks/dlq` or similar)
- `replayDlq(deliveryId: string)` → `POST /api/v1/webhooks/dlq/{delivery_id}/replay`

If they don't exist, add them following the existing fetch pattern (see `fetchFights` or `fetchAccount`).

**Verify**: `pnpm typecheck` → exit 0

### Step 2: Create WebhookDlqGrid component

Create `web/src/components/WebhookDlqGrid.tsx`:

```tsx
// AG Grid component showing failed deliveries with:
// - delivery_id, subscription_id, status_code, error_message, attempt, next_attempt_at
// - "Replay" button column that calls replayDlq(id) and refreshes the row
// - Empty state: "No failed deliveries" when list is empty
// - Loading state: skeleton while fetching
// - Error state: formatted API error message
```

Follow the existing grid pattern from `FightsGrid.tsx` or `PlayersGrid.tsx` (AG Grid Community, `ClientSideRowModelModule`, sort/filter enabled). The Replay button should call `replayDlq(id)`, show a success toast, and refresh the grid data.

**Verify**: `pnpm test:unit -t "WebhookDlqGrid"` → tests pass (write tests in step 4)

### Step 3: Create /webhooks page

Create `web/src/app/webhooks/page.tsx`:

```tsx
// Server Component with force-dynamic
// Fetches delivery list server-side
// Renders WebhookDlqGrid client component
// Error boundary: wrapped in error.tsx
// Loading state: loading.tsx
```

**Verify**: `pnpm dev` → navigate to `/webhooks` → see DLQ grid with data or "No failed deliveries" if empty.

### Step 4: Add tests

Component tests in `web/tests/components/WebhookDlqGrid.test.tsx`:
- Renders "No failed deliveries" when list is empty
- Renders rows when deliveries are present
- "Replay" button calls replay endpoint

Page test in `web/tests/app/webhooks.test.tsx` (or e2e):
- Page renders grid or empty state

**Verify**: `pnpm test:unit` → all pass

## Test plan

- `WebhookDlqGrid.test.tsx` — 3 component tests
- `webhooks.test.tsx` — 1-2 page tests
- Follow the pattern in `web/tests/components/` for existing grid tests

## Done criteria

- [ ] `/webhooks` page exists with DLQ grid
- [ ] DLQ grid shows failed deliveries with delivery_id, status_code, error, attempt count
- [ ] "Replay" button per row works (calls POST and refreshes)
- [ ] Empty state, loading state, and error state render correctly
- [ ] `pnpm typecheck` passes
- [ ] `pnpm test:unit` passes
- [ ] No backend files modified

## STOP conditions

Stop and report if:
- The backend DLQ list endpoint doesn't exist or has a different shape than expected (check the actual route file).
- The replay endpoint requires admin auth that the frontend can't provide.

## Maintenance notes

The webhooks page can be extended later with subscription management (create/edit/revoke webhooks). Keep the grid component generic enough to accept different data shapes if the backend evolves.
