# advisor-plan 013 — /account BFF proxy via Next.js API route

## Problem

`web/src/app/account/page.tsx` posts the GW2 API key DIRECTLY from the browser to the FastAPI gateway via `Authorization: Bearer <key>`. The component AUTHOR NOTES this as a known trade-off ("Next.js developer should add a server-side proxy if production wants to bypass browser exposure entirely — the gateway is the source of truth either way"), but the proxy has not been implemented. In a prod deploy with a non-CORS-strict proxy, the browser retains the key in JS heap briefly between `setApiKey(value)` → `setApiKey("")` — visible to DevTools / extensions / XSS-vulnerable deps.

## Context

- `web/src/app/account/page.tsx:46-50` — directly POSTs `apiKey` to the gateway via `resolveAccount(apiKey)` (a thin wrapper around `fetch`).
- `web/src/lib/api.ts` has the `resolveAccount` helper that calls the gateway directly.
- The gateway endpoint is `/api/v1/account` (verify in `apps/api/src/gw2analytics_api/routes/account.py` — Bearer-protected).
- Next.js App Router supports `route.ts` for API routes; `force-dynamic` ensures runtime env resolution.

## Approach

Add a Next.js API route at `web/src/app/api/account/resolve/route.ts` that:
1. Accepts POST with the API key in the JSON body (NOT header — keeps the contract simple).
2. Server-side forwards to the gateway's `/api/v1/account` with `Authorization: Bearer <server_received_key>`.
3. Returns the gateway response verbatim (status + body).

Refactor the browser component to POST to `/api/account/resolve` instead of directly to the gateway. The browser ONLY ever sees the public Next.js API; the gateway sees the Next.js server.

## Files

**In scope**:
- NEW `web/src/app/api/account/resolve/route.ts`
- MODIFIED `web/src/app/account/page.tsx` (replace `resolveAccount(apiKey)` → `fetch('/api/account/resolve')`)
- MODIFIED `web/src/lib/api.ts` (deprecate `resolveAccount`, add `resolveAccountViaProxy`)
- NEW `web/tests/app/api-account-resolve.test.ts` (vitest unit)
- NEW `web/tests/e2e/account-bff.spec.ts` (Playwright e2e)

**Out of scope**:
- `apps/api/src/gw2analytics_api/routes/account.py` (gateway endpoint unchanged).
- The gateway's Bearer handling.

## Steps

1. Create `web/src/app/api/account/resolve/route.ts`:
   ```ts
   import { NextResponse } from "next/server";
   import { apiBaseUrl } from "@/lib/env";

   export const dynamic = "force-dynamic";

   export async function POST(req: Request): Promise<NextResponse> {
     const body = (await req.json()) as { api_key?: string };
     if (!body?.api_key) {
       return NextResponse.json({ detail: "api_key required" }, { status: 400 });
     }
     const upstream = await fetch(`${apiBaseUrl}/api/v1/account`, {
       method: "GET",
       headers: { Authorization: `Bearer ${body.api_key}` },
     });
     const data = await upstream.json().catch(() => ({}));
     return NextResponse.json(data, { status: upstream.status });
   }
   ```
   Note: use `apiBaseUrl` (server-side import) — NOT `clientApiBaseUrl` or `NEXT_PUBLIC_*`.
2. Refactor `web/src/app/account/page.tsx` line 47:
   - Replace `const resolved = await resolveAccount(apiKey);` with:
     ```ts
     const resp = await fetch("/api/account/resolve", {
       method: "POST",
       headers: { "Content-Type": "application/json" },
       body: JSON.stringify({ api_key: apiKey }),
     });
     if (!resp.ok) throw new ApiError(resp.status, await resp.text());
     const resolved = (await resp.json()) as AccountEnrichedRow;
     ```
3. Update `web/src/lib/api.ts`:
   - Mark `resolveAccount` as `@deprecated`.
   - Add `resolveAccountViaProxy(apiKey)` wrapper.
4. Add `web/tests/app/api-account-resolve.test.ts`:
   - Mock `fetch`; assert the route forwards `Authorization: Bearer <key>` to upstream.
   - Assert 400 on missing `api_key`.
   - Assert upstream status preserved on pass-through.
5. Add `web/tests/e2e/account-bff.spec.ts`:
   - Navigate to `/account`, submit a fake key, assert the resolved world triple is shown (use the mock-server fixture).
   - Submit an empty key, assert validation error.

## Verification

- `find web/src/app -path '*api/account/resolve*'` → 1 file.
- `npx tsc --noEmit` → 0 errors.
- `pnpm test:unit` → all green including the new test.
- `pnpm test:e2e` → all green including the new spec.
- Visual: navigate to `/account` in mock-server mode, paste a key, observe the resolved world.

## Test plan

- 1 vitest test for the route handler.
- 1 Playwright e2e spec for the full submit-and-resolve flow.
- The route MUST be `force-dynamic` (opt out of static caching — runtime env resolution needed).

## Done criteria

- `web/src/app/api/account/resolve/route.ts` exists.
- `web/src/app/account/page.tsx` calls the proxy.
- 2 new tests pass.
- TypeScript + lint + e2e + visual regression all green.

## Maintenance note

- The new route is keyed server-side; if the operator runs multiple Next.js instances, they ALL forward independently. No state.
- If the gateway endpoint signature changes, the proxy is now the API boundary — change ONE place.
- `apiBaseUrl` is server-only; the browser should NOT see the gateway URL at all (defense in depth via indirection).

## Escape hatch

- If the operator already proxies the gateway behind their own Caddy via an `/account` sub-route, plan 013 is redundant. Skip.
- If a future Next.js version replaces `route.ts` with `route.js` (camelCase) or `app/api/.../route.ts` with `app/api/.../route.js`, port the handler to the new shape.
- If a generic `app/api/*` route guard is added in a future plan, factor out the `Authorization` header forwarding into a shared helper.
