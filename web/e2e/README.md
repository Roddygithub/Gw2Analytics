# Real-stack E2E user journey

`user-journey.spec.ts` drives a full, real user flow — **no mocks** — against
a live stack: it uploads real `.zevtc` files through the `/upload` wizard,
waits for the parse, browses the fights list + fight detail + players, tests
the 100 MiB upload cap (client + server), screenshots every step, and records
console errors / page errors / `>=400` responses to `_diagnostics.json`.

It is **separate from the default Playwright suite** (`tests/e2e/`, which runs
against a mock server) and is **OFF by default**: the spec self-skips unless
the stack is reachable **and** a real small `.zevtc` path is provided. So it is
safe to have in the tree — CI and a laptop without the stack stay green.

The journey covers: landing → upload (small/medium/large) → fights list →
fight detail → players list → player profile → account/API key → players
compare → webhooks. Screenshots are captured at every step, validated to be
non-empty, and a `_diagnostics.json` records console errors, page errors and
HTTP >=400 responses.

## Prerequisites (the full stack, running)

1. **Postgres** on `:5432` (e.g. `brew services start postgresql@16` + `createdb gw2analytics`).
2. **MinIO** (S3 blob storage) on `:9000` (e.g. `minio server <dir> --address 127.0.0.1:9000`).
   *(The upload flow stores blobs in S3 — there is no filesystem fallback.)*
3. **FastAPI** on `:8000` with the required env (`DATABASE_URL`, `S3_*`,
   `SECRETS_KEK`). Set `ALLOW_INREQUEST_PARSE_FALLBACK=1` to parse in-request
   and skip needing Redis + the arq worker:
   `uv run uvicorn gw2analytics_api.main:app --host 127.0.0.1 --port 8000`
4. **Migrations** applied: `cd apps/api && uv run alembic upgrade head`.
5. **Next.js dev** on `:3000`, pointed at the real API:
   `API_BASE_URL=http://localhost:8000 pnpm dev`
6. (Optional) the **arq worker** if you want the async parse path instead of
   the in-request fallback.

## Environment variables

| Var | Default | Meaning |
|---|---|---|
| `E2E_STACK_URL` | `http://localhost:3000` | Next.js frontend base URL |
| `E2E_API_URL` | `http://localhost:8000` | FastAPI base URL (direct 413 cap probe) |
| `E2E_ZEVTC_SMALL_PATH` | *(unset → suite skips)* | real small `.zevtc` (the core journey) |
| `E2E_ZEVTC_MEDIUM_PATH` | *(unset → step skips)* | medium `.zevtc` || `E2E_ZEVTC_LARGE_PATH`   | *(unset → step skips)* | large `.zevtc` to exercise parse + browse (legacy single-file alias) |
| `E2E_ZEVTC_LARGE_PATHS`  | *(unset → falls back to `LARGE_PATH`)* | comma-separated list of large `.zevtc` files; each file runs as its own test, so you can stress-test several real file sizes in one run |
| `E2E_GW2_API_KEY` | *(unset → uses dummy key)* | real GW2 API key for the `/account` step |
| `E2E_SCREENSHOT_DIR` | `./playwright-e2e-screenshots` | screenshot output (gitignored) |

> **Security note:** never commit a real GW2 API key. Pass it via the
> `E2E_GW2_API_KEY` environment variable. The input is rendered as
> `type="password"`, so Playwright screenshots mask the value, but avoid
> sharing raw screenshots, traces, or `_diagnostics.json` that could leak the
> key through network logs. If the key is ever exposed in shell history or
> shared logs, rotate it immediately in your ArenaNet account settings.

## Run

```bash
cd web
E2E_ZEVTC_SMALL_PATH=/abs/path/small.zevtc \
E2E_ZEVTC_MEDIUM_PATH=/abs/path/medium.zevtc \
E2E_ZEVTC_LARGE_PATH=/abs/path/large.zevtc \
E2E_GW2_API_KEY="<your-gw2-api-key>" \
pnpm exec playwright test --config playwright.journey.config.ts
```

To run only the large-upload proxy-bypass regression:

```bash
cd web
E2E_ZEVTC_LARGE_PATH=/abs/path/large.zevtc \
pnpm exec playwright test --config playwright.journey.config.ts e2e/large-upload.spec.ts
```

To run only the negative test that proves the 10 MB limit is hit:

```bash
cd web
E2E_ZEVTC_LARGE_PATH=/abs/path/large.zevtc \
pnpm exec playwright test --config playwright.journey.config.ts e2e/proxy-limit.spec.ts
```

To run all real-stack specs at once:

```bash
cd web
E2E_ZEVTC_SMALL_PATH=/abs/path/small.zevtc \
E2E_ZEVTC_MEDIUM_PATH=/abs/path/medium.zevtc \
E2E_ZEVTC_LARGE_PATHS="/abs/path/large1.zevtc,/abs/path/large2.zevtc" \
E2E_GW2_API_KEY="<your-gw2-api-key>" \
pnpm exec playwright test --config playwright.journey.config.ts
```

If `E2E_ZEVTC_SMALL_PATH` is unset/missing, or the stack isn't reachable at
`E2E_STACK_URL`, the test is **skipped** (not failed). Screenshots + a
`_diagnostics.json` land in `E2E_SCREENSHOT_DIR`.

## Large uploads and the Next.js dev proxy limit

The Next.js dev server (`next dev`) rewrites `/api/v1/*` to the FastAPI
backend, but its internal proxy enforces a hard **10 MB request body limit**.
Uploading a real `.zevtc` larger than 10 MB through `http://localhost:3000`
therefore fails with `ECONNRESET` / 500, even though the same upload succeeds
when posted directly to the backend at `http://localhost:8000`.

The real-stack specs work around this by intercepting `POST /api/v1/uploads`
in Playwright and forwarding it straight to `E2E_API_URL`:

```ts
await page.route("/api/v1/uploads", async (route) => {
  const request = route.request();
  if (request.method() !== "POST") {
    await route.continue();
    return;
  }
  const response = await route.fetch({
    url: `${API_URL}/api/v1/uploads`,
  });
  await route.fulfill({ response });
});
```

This keeps the test honest (the browser still drives the upload wizard) while
avoiding the dev-server payload cap. In production, a real reverse proxy such
as Caddy/NGINX handles large uploads natively and does not need this
interception.

The shared helpers live in `web/e2e/helpers/`:

* `proxy.ts` — `bypassNextJsProxyForLargeUploads()` is reused by both
  `user-journey.spec.ts` and `large-upload.spec.ts`. It uses Playwright's
  `route.continue({ url })`, which preserves the original multipart body and
  headers while changing only the destination URL.
* `env.ts` — `parseLargeZevtcPaths()` parses `E2E_ZEVTC_LARGE_PATHS`.
* `string.ts` — `safeFileLabel()` sanitizes file paths for screenshot names
  and test step titles.

`large-upload.spec.ts` isolates this behavior: it uploads the file provided by
`E2E_ZEVTC_LARGE_PATH` through the wizard with the interceptor enabled and
asserts the wizard reaches the done state with status `completed`.

`proxy-limit.spec.ts` is the negative counterpart: it uploads the same large
file **without** the bypass and asserts the wizard surfaces an error, proving
the 10 MB limit is real.

> No `.zevtc` handy? The repo ships fixtures under `web/tests/fixtures/zevtc/`
> (`real_small.evtc` is a real 47-agent fight) and a generator at
> `tests/load/scripts/generate_sample_zevtc.py`. Zip a raw `.evtc` into a
> single-entry `.zevtc` (`fight.evtc` first) to feed the small/medium slots.
