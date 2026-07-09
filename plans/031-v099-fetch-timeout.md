# Plan 031 — v0.9.9 fetch() timeout in api.ts

**Drift base:** `44ea862` (origin/main HEAD at audit time)
**Author:** senior-advisor audit (improve skill, standard effort) — web/src/lib/* deep pass
**Status:** pending
**Effort:** S
**Category:** reliability + DoS hardening (fetch timeout)
**Files touched:** `web/src/lib/api.ts` (1 file, additive changes only)

## Problem

All 9 fetchers in `web/src/lib/api.ts` call the browser-native
`fetch()` WITHOUT an `AbortSignal` or a `timeout` option. A
hung gateway (e.g. a Postgres query that takes 60 s, or a
MinIO blob that takes 30 s to download, or a network
partition where the TCP socket is alive but no response
arrives) holds the fetch open **indefinitely**. The
consequences:

1. **Server Component hangs**: Next.js Server Components run
   on the Node.js event loop. A fetch that never resolves
   blocks the request handler for the lifetime of the
   underlying TCP socket (which can be minutes for a
   half-open connection). Under load, this exhausts the
   Node.js worker pool, and the entire Next.js server stops
   responding.

2. **Client Component hangs**: the browser's fetch can hang
   too (the browser's default timeout is OS-level, ~5 min
   for HTTP/1.1 keep-alive). The user sees a spinner
   indefinitely; the page never renders the canonical
   "Upstream error" card.

3. **DoS amplification**: an attacker who can submit a
   `.zevtc` upload (public endpoint `POST /api/v1/uploads`)
   + who can trigger a slow query (e.g. a per-account
   timeline with `limit=10000` on a player with 5000 fights)
   can hold a Next.js worker open for the full query
   duration. With 8 workers, 8 concurrent slow requests
   exhaust the pool.

### Severity

- **Reliability**: MED — a single hung request blocks a
  Node.js worker for minutes; 8 hung requests halt the
  server.
- **DoS amplification**: MED — public `POST /api/v1/uploads`
  + `/api/v1/account` + `/api/v1/webhooks` (all
  unauthenticated) make this a reachable attack surface.
- **User experience**: MED — the "Upstream error" card is
  the canonical "the gateway is having a bad day" surface;
  without a timeout, the user never sees it.

## Goals

- Add an `AbortSignal.timeout(N)` option to all 9 fetchers
  in `web/src/lib/api.ts`. Each fetcher gets a per-endpoint
  timeout tuned to the endpoint's expected response time.
- Add a shared `_TIMEOUTS` constants object at the top of
  the file so the timeouts are documented in one place.
- Add a clear `TimeoutError` handling path: a timed-out
  fetch throws an `ApiError(504, "gateway timeout")` so
  the existing `formatApiError` path renders the
  canonical "Upstream error: 504" card.
- Add a hermetic regression test that asserts the timeout
  is honoured.

## Non-goals

- Implementing retry-on-timeout. A timed-out fetch is a
  user-visible failure (the gateway is down or slow); the
  canonical "refresh the page" UX is the correct path.
  Adding retry would mask the symptom.
- Implementing request deduplication / per-request cache.
  Out of scope (the `cache: "no-store"` opt-in is the
  canonical pattern for dynamic content).
- Switching from `AbortSignal.timeout()` to a manual
  `AbortController` + `setTimeout`. The native
  `AbortSignal.timeout()` is the standard pattern since
  Node 18+ / browsers 2022+; no need for the manual pattern.
- Adding a global request timeout to the FastAPI gateway.
  Out of scope (the gateway is a separate service; the
  plan is a client-side defence).

## Implementation

### File: `web/src/lib/api.ts`

Add a shared `_TIMEOUTS` constants object + a helper
function `_fetchWithTimeout()` at the top of the file
(after the imports, before the first fetcher). Then
replace every `fetch(...)` call in the 9 fetchers with
`_fetchWithTimeout(...)`.

```typescript
/**
 * Per-endpoint timeout budgets (milliseconds). Tuned to
 * the expected response time of each endpoint on the
 * canonical self-host (Postgres 16 + MinIO on localhost
 * + 100 fights in the dataset). The timeouts are
 * intentionally generous to accommodate cold-start
 * Postgres plans + cold MinIO blob downloads; tighten
 * further if the canonical response times drop.
 *
 *   10_000 (10 s)  — default for most endpoints
 *   15_000 (15 s)  — fight-events + fight-timeline
 *                    (MinIO blob decompress; the largest
 *                    blob in the canonical dataset is
 *                    ~5 MB gzipped and decompresses in
 *                    ~500 ms; 15 s is 30x headroom)
 *   20_000 (20 s)  — player-timeline (the slowest
 *                    endpoint on a large dataset; can
 *                    walk the full fight set in the
 *                    worst case)
 *   30_000 (30 s)  — upload (multipart .zevtc upload
 *                    + gateway hash + MinIO PUT; a
 *                    30 MB .zevtc on a slow connection
 *                    can take 20+ s to land)
 */
const _TIMEOUTS = {
  fights: 10_000,
  fightEvents: 15_000,
  fightSquads: 10_000,
  fightSkills: 10_000,
  fightTimeline: 15_000,
  account: 10_000,
  uploads: 30_000,
  players: 10_000,
  player: 10_000,
  playerTimeline: 20_000,
} as const;

/**
 * Wrap a ``fetch()`` call with a per-endpoint timeout. A
 * timed-out fetch throws an ``ApiError(504, "gateway
 * timeout")`` so the existing ``formatApiError`` path
 * renders the canonical "Upstream error: 504" card.
 *
 * The native ``AbortSignal.timeout(N)`` is the standard
 * pattern since Node 18+ / browsers 2022+. The catch
 * block checks for ``AbortError`` (the canonical name
 * for the thrown DOMException when the signal aborts)
 * and re-throws as ``ApiError(504, ...)`` so the rest of
 * the fetcher's error-handling code is unchanged.
 */
async function _fetchWithTimeout(
  input: string,
  init: RequestInit,
  timeoutMs: number,
): Promise<Response> {
  try {
    return await fetch(input, {
      ...init,
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (err) {
    if (err instanceof Error && err.name === "AbortError") {
      throw new ApiError(504, `gateway timeout after ${timeoutMs}ms`);
    }
    throw err;
  }
}
```

Then replace every fetcher's `fetch(...)` call with
`_fetchWithTimeout(...)`. The diff is a 1-line change per
fetcher (9 fetchers total) + the timeout constant. For
example, `fetchFights()` becomes:

```typescript
export async function fetchFights(): Promise<FightRow[]> {
  const resp = await _fetchWithTimeout(
    `${API_BASE_URL}/api/v1/fights`,
    { cache: "no-store" },
    _TIMEOUTS.fights,
  );
  // ... rest of the body unchanged
}
```

The same pattern applies to all 9 fetchers. The complete
mapping:

| Fetcher | Timeout constant |
|---|---|
| `fetchFights` | `_TIMEOUTS.fights` (10 s) |
| `fetchFightEvents` | `_TIMEOUTS.fightEvents` (15 s) |
| `fetchFightSquads` | `_TIMEOUTS.fightSquads` (10 s) |
| `fetchFightSkills` | `_TIMEOUTS.fightSkills` (10 s) |
| `fetchFightTimeline` | `_TIMEOUTS.fightTimeline` (15 s) |
| `resolveAccount` | `_TIMEOUTS.account` (10 s) |
| `uploadLog` | `_TIMEOUTS.uploads` (30 s) |
| `fetchPlayers` | `_TIMEOUTS.players` (10 s) |
| `fetchPlayer` | `_TIMEOUTS.player` (10 s) |
| `fetchPlayerTimeline` | `_TIMEOUTS.playerTimeline` (20 s) |

## Test plan

1. **Hermetic regression test** (NEW, in
   `web/tests/lib/api.test.ts`): a fetcher call against a
   never-resolving server (e.g. an HTTP server that
   sleeps forever) throws `ApiError(504, ...)` within
   `timeoutMs + 100 ms`.
2. **All existing tests still pass**: the change is
   backwards-compatible for any happy-path fetch (the
   `AbortSignal.timeout()` is a no-op when the fetch
   resolves within the budget).
3. **`pnpm exec tsc --noEmit`** is clean (the new
   `_TIMEOUTS` object + `_fetchWithTimeout` helper type-
   check against the existing fetcher signatures).
4. **`pnpm exec vitest run`** exits 0.

## Acceptance criteria

- [ ] `web/src/lib/api.ts` has the new `_TIMEOUTS` object
      + the `_fetchWithTimeout` helper.
- [ ] All 9 fetchers use `_fetchWithTimeout` instead of
      raw `fetch`.
- [ ] `web/tests/lib/api.test.ts` has the new
      timeout-triggers-ApiError-504 test; it passes.
- [ ] All existing tests pass.
- [ ] `tsc --noEmit` is clean.
- [ ] No production code paths change (the timeouts are
      a new behaviour; the existing fetcher signatures
      are unchanged).

## Out-of-scope / deferred

- **Per-environment timeout tuning** (e.g. longer
  timeouts on a slow VPS): the plan hardcodes the
  timeouts. A future plan can add a `NEXT_PUBLIC_*`
  env var to override each timeout. Out of scope for
  v0.9.9.
- **Retry on transient timeout**: out of scope (a
  timed-out fetch is a user-visible failure; retry
  would mask the symptom).
- **Server-side request timeout in the FastAPI
  gateway**: out of scope (separate service).
- **Connection timeout (vs read timeout)**: the
  `AbortSignal.timeout()` covers the read timeout
  (the time between request sent and response
  received). A separate connect timeout is not
  exposed by the `fetch` API; the OS-level connect
  timeout applies.

## Maintenance notes

- **`AbortSignal.timeout()` is supported in Node 18+
  and all modern browsers (Chrome 103+, Firefox 100+,
  Safari 15.4+)**. The plan assumes the canonical
  deploy uses Node 20+ (per the CI workflow
  `actions/setup-node@v4` + `node-version: 20`). For
  older Node versions, the operator must upgrade
  (Node 18 EOL was April 2025; Node 20 is the
  current LTS).
- **Timeout tuning**: the per-endpoint timeouts are
  conservative for the canonical self-host. Operators
  with a faster gateway (e.g. local Postgres + local
  MinIO + SSD) can tighten the timeouts by editing
  the `_TIMEOUTS` object. Operators with a slower
  gateway (e.g. cross-region Postgres) can lengthen
  them. The plan's values are the safe defaults.
- **The `504 Gateway Timeout` status code** is the
  canonical "upstream timeout" code (vs `408 Request
  Timeout` which is "the client took too long to
  send the request"). The plan uses `504` because
  the Next.js front-end is the client + the
  FastAPI gateway is the upstream.
