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
| `E2E_ZEVTC_MEDIUM_PATH` | *(unset → step skips)* | medium `.zevtc` |
| `E2E_ZEVTC_LARGE_PATH` | *(unset → step skips)* | `>100 MiB` `.zevtc` for the cap test |
| `E2E_SCREENSHOT_DIR` | `./playwright-e2e-screenshots` | screenshot output (gitignored) |

## Run

```bash
cd web
E2E_ZEVTC_SMALL_PATH=/abs/path/small.zevtc \
E2E_ZEVTC_MEDIUM_PATH=/abs/path/medium.zevtc \
E2E_ZEVTC_LARGE_PATH=/abs/path/large.zevtc \
pnpm exec playwright test --config playwright.journey.config.ts
```

If `E2E_ZEVTC_SMALL_PATH` is unset/missing, or the stack isn't reachable at
`E2E_STACK_URL`, the test is **skipped** (not failed). Screenshots + a
`_diagnostics.json` land in `E2E_SCREENSHOT_DIR`.

> No `.zevtc` handy? The repo ships fixtures under `web/tests/fixtures/zevtc/`
> (`real_small.evtc` is a real 47-agent fight) and a generator at
> `tests/load/scripts/generate_sample_zevtc.py`. Zip a raw `.evtc` into a
> single-entry `.zevtc` (`fight.evtc` first) to feed the small/medium slots.
