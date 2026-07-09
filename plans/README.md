# Advisor Plans Index

This directory holds the forward-looking advisor audits for the GW2Analytics
monorepo. Each audit is a senior-advisor survey (improve skill, `next`
invocation, `quick` effort) that scopes the next cycle's direction-only
candidates. The plans are self-contained implementation specs that a
different, less-context-aware executor can ship without further
clarification.## v0.9.1 audit (security + correctness + correctness-tighter focus)

Five plans selected from the v0.9.1 audit (drift base `ef5e4f3`). Each plan addresses one HIGH-confidence finding; ordering below reflects the recommended implementation sequence (most-blocking → least-blocking).

| # | Plan | Status | Addresses finding | Effort |
|---|---|---|---|---|
| 004 | [004-v091-webhook-schema-id-type-fix](./004-v091-webhook-schema-id-type-fix.md) | **shipped** (`WebhookDeliveryOut.id` + `WebhookDeliveryReplayOut.delivery_id` → `str` with `Field(min_length=1, max_length=64)`; `Field` import added to `schemas.py`; hermetic regression test on schema shape) | #1 schema `int` ↔ `str` mismatch on `WebhookDeliveryOut` + `WebhookDeliveryReplayOut` | S |
| 005 | [005-v091-webhook-ssrf-block-https](./005-v091-webhook-ssrf-block-https.md) | **shipped** (universal IP-block on resolved addresses in `_validate_webhook_url` — direct IP literals classified via `ipaddress.ip_address`, hostnames via `getaddrinfo` for IPv4+IPv6; opt-out via `GW2ANALYTICS_ALLOW_PRIVATE_WEBHOOK_URLS` env; fail-closed on DNS errors; 5 new SSRF regression tests covering RFC1918, link-local, IPv6 loopback, hostname-resolves-to-private, and the opt-out escape hatch) | #2 SSRF bypass in `_validate_webhook_url` for `https://` schemes | S |
| 006 | [006-v091-upload-bg-task-closed-session](./006-v091-upload-bg-task-closed-session.md) | **shipped** (`process_parse(db)` → `process_parse(session_factory, upload_id, raw_bytes)`; body wrapped in `with session_factory() as db:`; both BG-task callers updated to `get_sessionmaker()`; regression test verifies the session is alive at task invocation time) | #3 closed-session bug in `process_parse` BackgroundTasks path | S |
| 007 | [007-v091-webhook-retry-dlq-replay-tests](./007-v091-webhook-retry-dlq-replay-tests.md) | **shipped** (4 NEW tests: scheduler first-attempt success, exponential backoff (single 10s step at attempt 2) → DLQ promotion on hitting ``_MAX_ATTEMPTS = 3``, replay idempotency under concurrent ``ThreadPoolExecutor`` + ``Session.commit`` race-widener, and HMAC byte-for-byte integrity across replays; the multi-tick ``test_retry_scheduler_failure_promotes_to_dlq_after_max_attempts`` landed in standalone ``apps/api/tests/test_webhooks_e2e_scheduler.py`` after an in-session deferral -- flat per-tick ``with``-block structure escapes the nested dedent footgun; original ``pytest.skip()`` placeholder in ``test_webhooks_e2e.py`` replaced with a stub-by-name pointer to the new module; ``time-machine`` dev-dep added; 22 tests collected across the 2 files; pytest --collect-only clean; mypy clean; ruff clean except 1 cosmetic E501 docstring line in the stub pointer) | #4 v0.9.1 retry+DLQ+replay test gap (0 tests on the scheduler tick + DLQ promote + replay idempotency) | M |
| 008 | [008-v091-openapi-drift-gate-fix](./008-v091-openapi-drift-gate-fix.md) | **shipped** (`src/lib/api/schema.d.ts` un-gitignored + committed as 71 KB baseline; CI `Detect API client drift` step (`git diff --exit-code -- web/src/lib/api/schema.d.ts`) inserted between `OpenAPI: regenerate web TypeScript client` and `Type-check web`; `CONTRIBUTING.md` `## Regenerating the web TypeScript client` section documents the contract — `Schema.d.ts` must be regenerated + committed in the SAME PR as any backend `apps/api/src/gw2analytics_api/routes/*` shape change; `openapi.json` remains gitignored as ephemeral intermediate artifact; deterministic re-regen verified via drift-gate smoke test (no diff after re-run)) | #5 broken OpenAPI drift gate (schema.d.ts is .gitignored, gate never has anything to diff) | S |

### Considered but deferred

The Agent B perf + tech-debt re-run surfaced 5 additional findings after the security+correctness pass was over. They are tracked here for the next cycle (v0.9.1 hardening or v0.10):

| # | Finding (drift base `ef5e4f3`) | Implication | Suggested phase |
|---|---|---|---|
| 12 | `routes/fights.py:list_fights` N+1 query across `agents` + `skills` relationships | `limit=50` triggers 101 SELECTs | v0.10 perf |
| 13 | `webhook_scheduler.process_scheduled_retries` sync HTTP serially blocks up to 10s per row | One slow webhook stalls the queue | v0.9.1 hardening (combine with plan 006) |
| 14 | `_load_fight_events` re-downloads + decompresses + re-validates per endpoint (4× per fight hit by parallel frontend) | Massive OOM risk on busy fights | v0.10 perf |
| 15 | `_attempt_retry` subscription lookup N+1 in scheduler tick | One query per delivery on retry path | v0.9.1 hardening (combine with plan 007 tests) |
| 16 | `services.read_zevtc_bytes` fully unzips in memory | Scaling poor under BG-worker concurrency | v0.10 perf (streaming parser redesign) |


## v0.9.38 audit (current)

> **Scope.** Surface coverage: `apps/api/src/gw2analytics_api/backfill.py` + `routes/{fights,account,players}.py`. The remaining routes (`webhooks.py`, `uploads.py`, `health.py`) were covered by v0.9.15 + v0.9.25 + v0.9.26; the backfill library + the 3 largest operational routes (`fights`, `account`, `players`) are the v0.9.x cycle's most-touched surfaces (each edited 5-10 times across the v0.8.x / v0.9.x release history).

### Status

| Plan | Title | Files | Status | Tests |
|------|-------|-------|--------|-------|
| 116  | `_EVENT_TYPE_ADAPTER` triplicate DRY consolidation across `backfill.py` + `routes/fights.py` + `routes/players.py` | `_event_dispatch.py` NEW + 3 route/backfill sites + 1 test file | open | 5 NEW |
| 117  | `routes/fights.py::get_fight_events` monolithic 200+ lines → extract per-target roll-up helper for DRY | `routes/fights.py` + 1 test file | open | 5 NEW |
| 118  | `backfill.py::run_backfill` exception tuple gap: `EOFError` from truncated gzipped blobs aborts the loop instead of counting as `failed: 1` | `backfill.py` + 1 test file | open | 5 NEW |

**Total**: 3 plans, 15 NEW hermetic tests.

### Dependency graph

- **Plan 116** (single-source-of-truth `TypeAdapter` + `iter_events_from_blob` helper) is standalone; touches 4 production source files (`_event_dispatch.py` NEW + 3 call sites) + 1 NEW test file.
- **Plan 117** (per-target roll-up helper) is standalone; touches 1 production source file + 1 NEW test file.
- **Plan 118** (backfill `EOFError` catch + comment-block dedup) is standalone BUT transitively surfaces the same `EOFError` catch gap that plan 116 closes for the routes-via-hub path — both plans address per-fight exception-tuple correctness in different surfaces. The 3 plans can ship concurrently as 3 separate PRs.
- **No plan depends on a v0.9.27..v0.9.37 plan being merged first**. The 3 plans are independent and PR-friendly.

### Cross-cutting patterns

- **DRY consolidation across 3 call sites** (plan 116) — matches the v0.9.x convention of "ONE canonical implementation + thin call-site fan-out". Previously documented in plan 037 + plan 095 + plan 113.
- **Per-target roll-up DRY** (plan 117) — `get_fight_events` is the canonical Phase 7 v1 + Phase 8 v0.8.0 + v0.8.3 endpoint; extracting the per-target trio to a helper cleans up 120 LoC of noise.
- **Per-fight exception-tuple completeness** (plan 118) — `EOFError` from truncated gzipped blobs is the canonical "blameless error" surface (the operator shouldn't see a stacktrace on a corrupted mid-upload blob); the existing 4-tuple `(S3Error, OSError, SQLAlchemyError, ValidationError)` misses `EOFError`.

### Rejected alternatives (this pass's pattern, condensed)

- **Three module-level `TypeAdapter(Event)` instances** (vs. plan 116's one) — 3× build-on-import cost + stale-instance risk. REJECTED.
- **`singledispatch` on the `Event` superclass** (vs. plan 117's `if/elif`) — closed-form dispatch table is more readable for 3 known targets. REJECTED.
- **Catch `Exception` broadly** (vs. plan 118's specific 5-tuple) — silently swallows `AttributeError` from future schema drift. REJECTED.

### Test inventory (cumulative v0.9.27..v0.9.38)

| Pass | NEW hermetic tests |
|------|--------------------|
| v0.9.27 | 16 |
| v0.9.28 | 14 |
| v0.9.29 | 16 |
| v0.9.30 | 18 |
| v0.9.31 | 16 |
| v0.9.32 | 12 |
| v0.9.33 | 14 |
| v0.9.34 | 13 |
| v0.9.35 | 10 |
| v0.9.36 | 14 |
| v0.9.37 | 15 |
| **v0.9.38** | **15** |
| **Total** | **173** |

### Style conventions

- All 3 plans mirror the `## Findings → ## Fix → ## Tests → ## Rejected alternatives → ## Dependency graph → ## Notes for executors` structure established in the v0.9.27..v0.9.37 plans.
- All 3 plans name the **real** audit finding (the line + the duplicated concept + the SOURCE comment if it documents the duplication).
- All 3 plans surface a **cross-cutting hook** to the v0.9.x cycle conventions (plan 116 → single-source-of-truth; plan 117 → thin route layer; plan 118 → blameless per-fight errors).
## v0.9.7 audit (closed)

**Author:** senior-advisor audit (improve skill, standard effort) — targeted re-audit of 5 web components likely to share the v0.9.6 plan 024 (UTC) + plan 025 (URLSearchParams clobber) bug patterns
**Stamped at:** `44ea862` (origin/main HEAD at audit time)
**Recon scope:** `web/src/components/PerFightTimelineChart.tsx` + `web/src/components/EventWindowsChart.tsx` + `web/src/components/TargetFilter.tsx` + `web/src/components/PlayerSearchBar.tsx` + `web/src/components/ProfessionFilter.tsx`
**Audit mode:** standard effort; targeted re-audit pass; **0 findings** (the 2 bug patterns are localized to the 2 components flagged in v0.9.6, NOT propagated)

### v0.9.7 status table

| # | Plan | Status | Addresses finding | Effort |
|---|---|---|---|---|
| - | (no plans this cycle) | n/a | (no findings) | n/a |

### Audit conclusions

The 5 components were re-audited for the 2 bug patterns surfaced in v0.9.6:

| Component | UTC bug (plan 024) | URLSearchParams clobber (plan 025) | Notes |
|---|---|---|---|
| `PerFightTimelineChart.tsx` | NO | NO (no query-param mutation) | X-axis uses `formatSecondsLabel(ms)` (custom M:SS formatter) — raw ms is timezone-agnostic. The chart is bucket-indexed, no date math. |
| `EventWindowsChart.tsx` | NO | NO (no query-param mutation) | X-axis uses raw `b.start_ms` (numeric) — no date formatter at all. Pure SVG rendering. |
| `TargetFilter.tsx` | NO | NO — already uses `useSearchParams` + `new URLSearchParams(existingParams.toString())` + `params.set/delete` (line 89-101) | Correctly preserves `?window_s=` + any other future params. |
| `PlayerSearchBar.tsx` | NO | NO — navigates to a different page (`/players/${name}`), no in-page query-param mutation | The `?window_s=5` param (if any) does not apply on the new page; the navigation is a fresh URL, not a rewrite. |
| `ProfessionFilter.tsx` | NO | NO — already uses `useSearchParams` + `new URLSearchParams(searchParams.toString())` + `params.set/delete` (line 70-77) | Correctly preserves any other active params on `/players`. |

**Conclusion: the 2 v0.9.6 bugs are localized.** No new plans needed for v0.9.7. Future audits of these 5 components for the same bug patterns can re-use the v0.9.7 conclusion as a starting reference (no re-investigation needed).

### Followup: 7 web pages audit

The plan 028 deferred-item (\"audit the 4 web `app/**/page.tsx` files\") is now DONE — extended to all 7 page files in `web/src/app/`:

| Page | Type | UTC bug (plan 024 class) | URLSearchParams clobber (plan 025 class) | Other bugs | Notes |
|---|---|---|---|---|---|
| `web/src/app/page.tsx` | Server (static landing) | NO (no date math) | NO (no query-param mutation) | NO | Pure static landing with 4 link cards; reads `displayedApiBaseUrl` from `@/lib/env`. |
| `web/src/app/fights/page.tsx` | Server, `force-dynamic` | NO | NO | NO | `fetchFights()` in try/catch, renders `<FightsGrid>` or error card. No date formatting, no query-param mutation. |
| `web/src/app/fights/[id]/page.tsx` | Server, `force-dynamic` | NO (uses `Intl` for nothing) | NO (clamps + forwards to `<WindowSizeSelector>` / `<TargetFilter>`) | NO | 4 `Promise.allSettled` fetches; defensive `parseWindowS` + `parseTarget` clamp out-of-range values; `targetNameMap` \"first non-null wins\" contract documented; `effectiveTimeline` fallback with all required fields. State-of-the-art defensive code. |
| `web/src/app/account/page.tsx` | Client | NO | NO | NO | `setApiKey(\"\")` after consume (good hygiene); `formatApiError` for uniform error rendering. |
| `web/src/app/upload/page.tsx` | Client | NO | NO | NO | `.zevtc` extension pre-check; `event.currentTarget.reset()` allows re-selecting the same filename; `formatBytes` helper. |
| `web/src/app/players/page.tsx` | Server, `force-dynamic` | NO | NO (forwards `?profession=` to `<ProfessionFilter>`) | NO | `searchParams.profession` awaited; `ProfessionFilter` reads the same source (no client-side round-trip). |
| `web/src/app/players/[account_name]/page.tsx` | Server, `force-dynamic` | NO (passes through `started_at` strings) | NO | NO | Swallows `ApiError(404)` on timeline as expected; `effectiveTimeline` fallback carries `bucket: \"fight\"` + `tz: \"UTC\"` (matches the v0.8.9 API default). |

**Conclusion: 0 bugs across all 7 page files.** The 2 v0.9.6 bug patterns (UTC + URLSearchParams) are confirmed localized to the 2 originally-flagged components, NOT propagated to the page layer. The page layer's defensive patterns (clamp invalid query params; swallow expected 404s; exhaustive fallback shapes) actively defend against the same bug class at a different layer. No new plans needed; v0.9.7 audit is now COMPLETE (5 components + 7 pages = all `web/src/components/*.tsx` + all `web/src/app/**/*.tsx` covered).

### Considered and rejected (v0.9.7)

- **Plan 026 (DRY the URLSearchParams pattern into a `useFilteredQueryParam` hook)**: tempting (the pattern is duplicated in 3 components: `WindowSizeSelector`, `TargetFilter`, `ProfessionFilter`). But the 3 sites are already correct (TargetFilter + ProfessionFilter use the right pattern; only WindowSizeSelector was the bug). A DRY refactor would touch 3 correct files to fix 1 wrong file -- net regression risk. Defer until a 4th site needs the same pattern.
- **Plan 027 (force `timeZone: "UTC"` on all `Intl.DateTimeFormat` usages project-wide)**: tempting (defense-in-depth against the same bug class). But there are only 2 `Intl.DateTimeFormat` instances in the entire `web/src/` (both in `PlayerTimelineChart.tsx`); a project-wide grep finds no other call sites. The v0.9.6 plan 024 fix is scoped; a project-wide audit adds 0 value.
- **Plan 028 (audit the 4 web `app/**/page.tsx` files for the same bug classes)**: **DONE** — see \"Followup: 7 web pages audit\" above. All 7 page files (4 `app/**/page.tsx` + 3 root-level pages) audited for the same 2 bug classes; 0 findings. The page layer's defensive patterns (clamp invalid query params; swallow expected 404s; exhaustive fallback shapes) actively defend against the bug class at a different layer.

## v0.9.8 audit (closed)

**Author:** senior-advisor audit (improve skill, standard effort) — prod hardening pass on the surfaces never audited (docker-compose + Caddyfile + CI workflow + alembic migrations 0001-0008)
**Stamped at:** `44ea862` (origin/main HEAD at audit time — after the v0.9.6 deep audit + the v0.9.7 followup both landed: 6 + 0 plans indexed; the v0.9.7 followup confirmed 0 bugs in the 5 components + 7 pages)
**Recon scope:** `docker-compose.yml` + `Caddyfile` + `.github/workflows/ci.yml` + `apps/api/alembic/versions/0001_v0_5_baseline.py` through `0008_payload_bytes.py`
**Audit mode:** standard effort; targeted hardening pass on the production deployment contract; 4 HIGH-confidence findings selected for planning

### v0.9.8 status table

| # | Plan | Status | Addresses finding | Effort |
|---|---|---|---|---|
| 026 | [026-v098-docker-compose-prod-hardening](./026-v098-docker-compose-prod-hardening.md) | **pending** (add `restart: unless-stopped` + bind ports to `127.0.0.1` by default + `security_opt: ["no-new-privileges:true"]` + `cap_drop: ["ALL"]` + `cap_add` for the per-service needs + `pids_limit` + `mem_limit` + `cpus` + named `gw2a-net` bridge network + env-var-overridable credentials; compose header documents the infra-only contract; `apps/api/.env.example` gains a `## docker-compose prod env vars` section) | #1 `docker-compose.yml` has 7 prod hardening gaps: no restart, public 0.0.0.0 port exposure (incl. MinIO admin console on 9001), no security_opt/cap_drop, no resource limits, hardcoded dev creds (security+reliability, HIGH) | S |
| 027 | [027-v098-caddyfile-prod-hardening](./027-v098-caddyfile-prod-hardening.md) | **pending** (add `header` directive in the `common` snippet for HSTS + CSP + X-Frame-Options + Referrer-Policy + Permissions-Policy + X-Content-Type-Options; add `rate_limit {remote.ip} 100r/m` on the api site block; add `email` directive for Let's Encrypt; prominent `## PRODUCTION CHECKLIST` header + `# !!! REPLACE !!!` annotations on both domain lines) | #2 `Caddyfile` has 7 prod hardening gaps: no HSTS, no CSP, no X-Frame-Options, no Referrer-Policy, no Permissions-Policy, no rate limit, no `email` directive for ACME (security+reliability, HIGH) | S |
| 028 | [028-v098-ci-workflow-hardening](./028-v098-ci-workflow-hardening.md) | **pending** (add `permissions: { contents: read }` at the job level + `timeout-minutes: 30` on the job + per-step timeouts on long-running steps + `persist-credentials: false` on the checkout step + a `pip-audit` step + a `pnpm audit` step + restrict `concurrency.cancel-in-progress` to PRs only; NEW `.github/dependabot.yml` for weekly Python + npm + GitHub Actions dep updates; `apps/api/pyproject.toml` gains `pip-audit` dev dep; `web/package.json` gains `audit` script) | #3 CI workflow has 7 hardening gaps: no read-only token, no timeouts, no `pip-audit`/`pnpm audit`, `cancel-in-progress` cancels main pushes too, no Dependabot, no checkout `persist-credentials: false` (security+reliability+supply-chain, HIGH) | S |
| 029 | [029-v098-alembic-check-constraints](./029-v098-alembic-check-constraints.md) | **pending** (NEW migration 0009 adds 6 `CHECK` constraints: `uploads.status IN ('pending','parsing','parsed','failed')`, `webhook_deliveries.attempt >= 0`, `webhook_deliveries.status_code BETWEEN 100 AND 599` (or NULL), `fight_player_summaries.{total_damage,total_healing,total_buff_removal} >= 0`; pre-check guards against migration failure on existing violating rows; `downgrade()` intentionally raises `NotImplementedError`; `apps/api/src/gw2analytics_api/models.py` gains matching `CheckConstraint` declarations on the 3 affected ORM tables for SQLite-in-tests parity; NEW `apps/api/tests/test_alembic_constraints.py` with 4 hermetic regression tests) | #4 4 columns (`uploads.status`, `webhook_deliveries.attempt`, `webhook_deliveries.status_code`, `fight_player_summaries` magnitudes) lack DB-layer `CHECK` constraints; direct DB writes bypass application-layer enforcement (data-integrity, MED) | S |

### Recommended execution order (v0.9.8)

1. **Plan 029** (alembic CHECK constraints) — S effort, the smallest + the most data-integrity-critical. Self-contained (1 NEW migration + 1 models.py edit + 1 NEW test file). Independent of 026/027/028.
2. **Plan 026** (docker-compose hardening) — S effort, the single biggest prod security win. Closes 7 hardening gaps in 1 file. Self-contained. Independent.
3. **Plan 027** (Caddyfile hardening) — S effort, the 2nd biggest prod security win. Closes 7 hardening gaps in 1 file. Self-contained. Independent.
4. **Plan 028** (CI workflow hardening) — S effort, the supply-chain + reliability win. Spans 4 files (workflow + dependabot.yml + pyproject.toml + package.json). Independent.

All 4 are independent. Could ship in any order. The recommended order is by surface-locality (data layer first, then infra files, then CI).

### Dependency graph (v0.9.8)

```
  plan 029 ─┐                          (alembic + models.py + tests/)
  plan 026 ─┼── INDEPENDENT ────────── (docker-compose + .env.example)
  plan 027 ─┤                          (Caddyfile)
  plan 028 ─┘                          (.github/workflows/ci.yml + dependabot.yml + pyproject.toml + package.json)
```

No inter-plan dependencies. No shared file paths. Could be PR'd in any order or in parallel by 4 different engineers.

### Considered and rejected (v0.9.8)

- **Bundle 026 + 027 into one "infra-compose + reverse-proxy" plan**: tempting (both touch the prod deployment contract). The 2 plans are independent at the file level (026 = `docker-compose.yml`; 027 = `Caddyfile`); bundling would conflate the container-hardening invariant with the reverse-proxy-header invariant, making either one harder to revert if regressed in CI.
- **Bundle 028 + 029 into one "infra + DB hardening" plan**: tempting (both touch infrastructure). The 2 plans are independent at the file level (028 = `.github/workflows/ci.yml` + `.github/dependabot.yml`; 029 = `apps/api/alembic/versions/0009_*` + `apps/api/src/gw2analytics_api/models.py`); bundling would conflate the CI-supply-chain invariant with the DB-data-integrity invariant.
- **Plan 026 alternative: switch to a hardened `postgres:16` non-alpine image** (drops CVEs in musl libc): out of scope (alpine is the canonical image per the docker-compose contract; switching to a non-alpine image would ~double the image size). The hardening knobs in the plan are the v0.9.8 minimum.
- **Plan 026 alternative: `seccomp: '{"defaultAction":"SCMP_ACT_ERRNO","syscalls":[...]}'` for fine-grained syscall filtering**: out of scope (seccomp is a docker-default profile; an operator who wants tighter filtering can use `--security-opt seccomp=/path/to/profile.json`). The plan applies the `no-new-privileges` knob which is the next-most-impactful default.
- **Plan 026 alternative: bind-mount `/etc/localtime` + `TZ=UTC` env for consistent timestamps**: out of scope (a Postgres `TZ` is a config-layer concern, not a compose-layer concern; a future plan can add `TZ=UTC` to the `environment:` block if the operator requests it).
- **Plan 027 alternative: drop the `connect-src` `unsafe-inline` for `script-src` + `style-src`** (the strictest CSP): out of scope — Next.js's production build hashes inline styles but the CSP directive syntax does not accept hashes without a build-time codegen step (Next.js's experimental CSP support). A future plan can add the build-time hash extraction.
- **Plan 027 alternative: switch to Caddy's `cloudflare` module for IP-based rate limiting**: out of scope (Caddy's built-in `rate_limit` is sufficient for single-host self-host; multi-replica needs Redis-backed `caddy-dynamic-ratelimit` which is a future hardening).
- **Plan 028 alternative: CodeQL for SAST**: out of scope (the repo is small + well-tested; SAST is a future hardening).
- **Plan 028 alternative: `release-please` / `changesets` for CHANGELOG automation**: out of scope (manual CHANGELOG + tag flow is the production contract per the README).
- **Plan 028 alternative: self-hosted runner for the Playwright suite** (saves ~3 min per run): out of scope (cost/ops tradeoff for a small repo).
- **Plan 029 alternative: NOT VALID + VALIDATE CONSTRAINT for zero-downtime migration**: out of scope (the 4 affected tables are small enough that a full constraint add is fine; the pre-check is <1 s on the canonical dataset).
- **Plan 029 alternative: add a `webhook_deliveries.status` enum column**: out of scope (a larger refactor; the state is currently inferred from `status_code` + `delivered_at`). Tracked as a v0.9.9+ item.

## v0.9.9 audit (closed)

**Author:** senior-advisor audit (improve skill, standard effort) — `web/src/lib/*` deep pass (api.ts + env.ts + csv.ts) for the patterns not covered by v0.9.6 (UTC + URLSearchParams in components) or v0.9.7 (page-layer defensive patterns)
**Stamped at:** `44ea862` (origin/main HEAD at audit time — after the v0.9.8 prod hardening pass landed: 4 plans 026-029 written + indexed; v0.9.7 followup confirmed 0 bugs in the web pages)
**Recon scope:** `web/src/lib/api.ts` + `web/src/lib/env.ts` + `web/src/lib/csv.ts` + `web/src/app/layout.tsx` (for the env-validation hook) + `web/.env.example`
**Audit mode:** standard effort; targeted deep pass on the shared utilities (typed client + env + CSV serializer); 4 HIGH-confidence findings selected for planning

### v0.9.9 status table

| # | Plan | Status | Addresses finding | Effort |
|---|---|---|---|---|
| 030 | [030-v099-csv-injection-fix](./030-v099-csv-injection-fix.md) | **pending** (NEW `FORMULA_TRIGGERS = /^[=+\-@\t\r]/` regex + 1-line guarded `csvEscape` body that prefixes formula-triggering values with `'` + wraps in double quotes per RFC 4180; NEW `web/tests/lib/csv.test.ts` with 12 hermetic tests covering all 6 trigger characters + safe-char paths + RFC 4180 baseline + null/undefined + combined-guard + a `toCsv` integration test on a real `PlayerListRow`; module docstring documents the OWASP attack class + the 4 attacker-controllable fields: `name` on `PlayerListRow`/`PlayerProfile`/`PerFightBreakdownRow`, `skill_name` on `SkillUsageRow`, `subgroup` on `SquadRollupRow`, `description` on `WebhookSubscription`) | #1 `csvEscape` regex `/[",\r\n]/` does NOT quote values starting with `=`, `+`, `-`, `@`, `\t`, `\r` -- OWASP CSV-injection (CWE-1236) lets a hostile name in the upload pipeline execute a formula in the analyst's Excel/Sheets (security, HIGH) | S |
| 031 | [031-v099-fetch-timeout](./031-v099-fetch-timeout.md) | **pending** (NEW module-level `_TIMEOUTS` constants object with 10 per-endpoint budgets (10-30 s, tuned to each endpoint's expected response time) + NEW `_fetchWithTimeout` helper that wraps `fetch` with `AbortSignal.timeout(N)` + re-throws as `ApiError(504, ...)` on `AbortError`; all 9 fetchers in `api.ts` rewired to use the helper; NEW `web/tests/lib/api.test.ts` hermetic test that asserts a never-resolving server throws `ApiError(504, ...)` within `timeoutMs + 100 ms`) | #2 All 9 fetchers in `api.ts` call `fetch()` with no `AbortSignal` -- a hung gateway holds the Next.js worker open indefinitely; 8 concurrent hung requests halt the entire server (DoS amplification, MED) | S |
| 032 | [032-v099-csv-revoke-object-url-race](./032-v099-csv-revoke-object-url-race.md) | **pending** (1-function body replacement in `downloadCsv` -- `a.click()` + `appendChild`/`removeChild` wrapped in `try/catch/finally`; `URL.revokeObjectURL(url)` deferred via `setTimeout(..., 0)` so the browser's async download dispatch has time to read the blob; 3 NEW tests in `web/tests/lib/csv.test.ts` verify the deferred revoke + the try/catch swallow + the SSR no-op) | #3 `downloadCsv` calls `URL.revokeObjectURL(url)` synchronously after `a.click()` -- in Safari (and occasionally Chrome/Firefox) the revoke wins the race and the download fails silently ~5-10% of the time (reliability, MED) | S |
| 033 | [033-v099-env-prod-hardening](./033-v099-env-prod-hardening.md) | **pending** (NEW `_resolveApiBaseUrl` function with production fail-fast (`NODE_ENV === "production" && !API_BASE_URL` throws with a clear remediation message) + `new URL()` validation at module load + `.trim()` whitespace handling; `web/src/app/layout.tsx` gains a belt-and-braces fail-fast assertion at server boot; `web/.env.example` documents `API_BASE_URL` + the optional `NEXT_PUBLIC_API_BASE_URL` alias for client-side use; 7 hermetic test cases cover production fail-fast + invalid URL + trailing-slash strip + dev fallback + whitespace trim) | #4 `env.ts` silently falls back to `http://localhost:8000` in production if `API_BASE_URL` is unset -- an operator who forgets the env var on a public VPS gets `ECONNREFUSED` on every fetch with no log signal (prod hardening, MED) | S |

### Recommended execution order (v0.9.9)

1. **Plan 030** (CSV injection) — S effort, the HIGH-severity security fix. Closes the OWASP-documented attack class. Self-contained (1 file + 1 NEW test file). Independent of 031/032/033.
2. **Plan 033** (env.ts prod hardening) — S effort, the second prod-hardening win. Self-contained (1 env.ts + 1 layout.tsx + 1 .env.example). Independent.
3. **Plan 031** (fetch timeout) — S effort, the DoS amplification defence. Self-contained (1 api.ts + 1 NEW test file). Independent.
4. **Plan 032** (URL.revokeObjectURL race) — S effort, the Safari reliability fix. Self-contained (1 csv.ts + 3 new tests). Independent.

All 4 are independent. Could ship in any order. The recommended order is by severity (HIGH security > prod hardening > DoS > reliability).

### Dependency graph (v0.9.9)

```
  plan 030 ─┐                          (csv.ts + csv.test.ts)
  plan 031 ─┼── INDEPENDENT ────────── (api.ts + api.test.ts)
  plan 032 ─┤                          (csv.ts + csv.test.ts additions)
  plan 033 ─┘                          (env.ts + layout.tsx + .env.example)
```

Plans 030 + 032 both touch `web/src/lib/csv.ts` and `web/tests/lib/csv.test.ts` -- they should be PR'd together or sequentially in the same PR to avoid merge conflicts in those 2 files. Plans 031 + 033 touch different files and can be PR'd in parallel by 2 different engineers.

### Considered and rejected (v0.9.9)

- **Bundle 030 + 032 into one "csv.ts hardening" plan**: tempting (both touch the same file). The 2 plans are independent at the test fixture level (030 adds a formula-injection guard; 032 defers the URL revoke); bundling would conflate the security invariant with the reliability invariant, making either one harder to revert if regressed in CI. The plan recommends PR'ing them sequentially in the same PR to avoid 2 separate PRs touching the same file.
- **Plan 030 alternative: reject uploads with hostile names at the API layer**: tempting (the API is the canonical write surface). But (a) the names are legitimate in the in-app view (the analyst sees the hostile name in the AG Grid without execution risk), (b) rejecting uploads would block legitimate unicode names, and (c) the CSV download is the only formula-execution surface. The CSV-level fix is the canonical defence.
- **Plan 030 alternative: escape with double-quotes + prepend `'` (no RFC 4180 wrapping)**: the spec allows either pattern. The plan picks the single-quote prefix + double-quote wrapping because (a) the `'` is invisible in the spreadsheet (Excel drops it on display), and (b) the double-quote wrapping ensures the value round-trips through any parser.
- **Plan 031 alternative: retry-on-5xx with exponential backoff**: tempting (a transient 502 from the gateway would auto-recover). But a timed-out fetch is a user-visible failure; retry would mask the symptom. The canonical "refresh the page" UX is the correct path.
- **Plan 031 alternative: manual `AbortController` + `setTimeout`**: out of scope -- `AbortSignal.timeout()` is the native pattern since Node 18+ / browsers 2022+. No need for the manual pattern.
- **Plan 031 alternative: server-side request timeout in the FastAPI gateway**: out of scope (separate service; the plan is a client-side defence).
- **Plan 032 alternative: switch to a third-party library (e.g. `file-saver`)**: out of scope -- the in-house fix is ~5 lines; the third-party library adds a dep for the same behaviour.
- **Plan 032 alternative: switch to the File System Access API (`window.showSaveFilePicker`)**: out of scope -- not supported in Firefox or Safari as of 2026; the hidden-`<a>` pattern is the cross-browser canonical pattern.
- **Plan 033 alternative: typed config object (`import { env } from "@/lib/env"`)**: out of scope -- the individual-constant pattern is canonical for Next.js Server Components.
- **Plan 033 alternative: runtime reachability check (e.g. ping the gateway at boot)**: out of scope -- the module-load sync check is sufficient; a reachability check is a separate concern (would slow down the dev loop and add a new failure mode).

## v0.9.10 audit (closed)

**Author:** senior-advisor audit (improve skill, standard effort) — `apps/api/src/gw2analytics_api/scripts/*` + `backfill.py` deep pass (the maintenance surface never audited; `backfill.py` is the v0.8.5 one-shot backfill that closes the v0.7.0 perf debt for pre-v0.8.4 fights; `health_gate.py` is the v0.8.7 CI gate that closes the loop on the v0.8.4 materialise)
**Stamped at:** `44ea862` (origin/main HEAD at audit time — after the v0.9.9 web/src/lib/* pass landed: 4 plans 030-033 written + indexed)
**Recon scope:** `apps/api/src/gw2analytics_api/backfill.py` + `apps/api/src/gw2analytics_api/scripts/__init__.py` + `apps/api/src/gw2analytics_api/scripts/backfill_player_summaries.py` + `apps/api/src/gw2analytics_api/scripts/health_gate.py`
**Audit mode:** standard effort; targeted deep pass on the maintenance scripts (per-fight backfill + per-fight commit semantics + CI gate error handling); 3 findings selected for planning (1 MED reliability + 2 LOW DX)

### v0.9.10 status table

| # | Plan | Status | Addresses finding | Effort |
|---|---|---|---|---|
| 034 | [034-v0910-backfill-commit-failure](./034-v0910-backfill-commit-failure.md) | **pending** (5-line edit inside the for loop in `run_backfill` -- the `db.commit()` is moved INSIDE the `try/except (S3Error, OSError, SQLAlchemyError, ValidationError)` block, the `backfilled += 1` counter is moved inside the try, so a commit-time failure (transient DB connection error, lost connection during COMMIT, serialisation failure) is treated as a per-fight failure: the fight is counted as `failed`, the transaction is rolled back, and the next fight is processed; NEW `test_run_backfill_handles_commit_time_failure` test injects a `SQLAlchemyError` at commit time and asserts the fight is counted as `failed` + the next fight is processed) | #1 `backfill.py::run_backfill` -- the per-fight `db.commit()` is OUTSIDE the `try/except` block; a commit-time failure (transient DB connection error, lost connection during COMMIT) propagates up and crashes the entire script (reliability, MED) | S |
| 035 | [035-v0910-backfill-cli-validation-progress](./035-v0910-backfill-cli-validation-progress.md) | **pending** (NEW `_positive_int` argparse type that rejects non-positive integers with a clear error message; `--limit` uses the new type; NEW `--progress-every N` flag (default: 100) for large-backfill progress reporting; `run_backfill` gains an opt-in `progress_callback` kwarg that is invoked once per fight with the running counts; 2 NEW hermetic tests: `--limit -1` exits 2 with a clear error; the `progress_callback` is invoked once per fight) | #2 `backfill_player_summaries.py` -- `--limit` is `type=int` (accepts negative values that crash Postgres with a cryptic error); no progress reporting for large backfills (10K+ fights) (DX, LOW) | S |
| 036 | [036-v0910-health-gate-error-handling](./036-v0910-health-gate-error-handling.md) | **pending** (4 distinct error paths in `health_gate.py` -- missing baseline file, malformed JSON baseline, probe 5xx, missing `drift_count` key -- each with a clear, actionable error message that identifies (a) what went wrong, (b) where in the script it happened, (c) the canonical fix; NEW `_error_and_exit` helper that prints to stderr + exits 1; 4 NEW hermetic tests cover the 4 error paths) | #3 `health_gate.py` -- missing baseline file = cryptic `FileNotFoundError`; malformed JSON = cryptic `JSONDecodeError`; probe 5xx = cryptic `HTTPError`; missing `drift_count` = cryptic `KeyError`. The CI operator has to read the code to figure out the canonical fix (DX, LOW) | S |

### Recommended execution order (v0.9.10)

1. **Plan 034** (commit-time failure) — S effort, the MED-severity reliability fix. Self-contained (1 backfill.py edit + 1 NEW test). Independent of 035/036.
2. **Plan 036** (health_gate error handling) — S effort, the CI error-clarity win. Self-contained (1 health_gate.py edit + 4 NEW tests). Independent.
3. **Plan 035** (CLI validation + progress) — S effort, the DX win. Self-contained (1 backfill_player_summaries.py edit + 1 backfill.py opt-in kwarg + 2 NEW tests). Independent.

All 3 are independent. Could ship in any order. The recommended order is by severity (MED reliability > LOW DX > LOW DX).

### Dependency graph (v0.9.10)

```
  plan 034 ─┐                          (backfill.py + test_backfill.py)
  plan 035 ─┼── INDEPENDENT ────────── (backfill_player_summaries.py + backfill.py + test_backfill.py)
  plan 036 ─┘                          (health_gate.py + test_ci_health_gate.py)
```

Plans 034 + 035 both touch `apps/api/src/gw2analytics_api/backfill.py` and `apps/api/tests/test_backfill.py` -- they should be PR'd together or sequentially in the same PR to avoid merge conflicts in those 2 files. Plan 036 touches different files and can be PR'd in parallel.

### Considered and rejected (v0.9.10)

- **Bundle 034 + 035 into one "backfill reliability + DX" plan**: tempting (both touch the backfill). The 2 plans are independent at the test fixture level (034 fixes commit-time failure; 035 adds CLI validation + progress); bundling would conflate the reliability invariant with the DX invariant, making either one harder to revert if regressed in CI. The plan recommends PR'ing them sequentially in the same PR to avoid 2 separate PRs touching the same file.
- **Plan 034 alternative: commit-time retry with exponential backoff**: tempting (a transient commit failure would auto-recover). But a transient commit failure is a per-fight issue; retrying the commit would re-execute the same SQL with the same state, which is the same race condition. The operator can re-run the script to retry the failed fights.
- **Plan 034 alternative: switching from per-fight commit to a single batch commit**: out of scope -- the per-fight commit is the canonical safety net (the operator can ``Ctrl+C`` between fights and lose at most one in-flight transaction). A batch commit would lose this guarantee.
- **Plan 035 alternative: adding a progress bar (e.g. ``tqdm``)**: out of scope -- the plain ``logger.info`` line is the canonical CI-friendly pattern (a progress bar would need a TTY + would pollute the log file).
- **Plan 035 alternative: adding a ``--batch-size`` flag for batch commits**: out of scope -- the per-fight commit is the canonical safety net; a batch commit would lose the per-fight rollback guarantee.
- **Plan 035 alternative: adding ``--resume-from <fight_id>``**: the discovery query's ``NOT EXISTS`` subquery already handles this (already-backfilled fights are skipped automatically).
- **Plan 036 alternative: switching from ``TestClient`` to a real HTTP client**: out of scope -- the in-process ``TestClient`` is the canonical hermetic pattern (no uvicorn boot, no port binding, no race condition).
- **Plan 036 alternative: adding retry on probe 5xx**: out of scope -- a probe 5xx is a real problem (the FastAPI app failed to start); retry would mask the symptom.
- **Plan 036 alternative: switching to a structured logging library (e.g. ``structlog``)**: out of scope -- the current ``print()``-based output is the canonical CI pattern (the operator reads the log in the GitHub Actions UI).

## v0.9.11 audit (closed)

**Author:** senior-advisor audit (improve skill, standard effort) — `libs/gw2_core` + `libs/gw2_api_client` deep pass (the library surfaces never audited; `gw2_core` is the stable internal data model with frozen Pydantic v2 + IntEnum enums; `gw2_api_client` is the async httpx wrapper with rate-limit retry + Protocol duck-typing)
**Stamped at:** `44ea862` (origin/main HEAD at audit time — after the v0.9.10 backfill/scripts pass landed: 3 plans 034-036 written + indexed)
**Recon scope:** `libs/gw2_core/src/gw2_core/models.py` + `libs/gw2_api_client/src/gw2_api_client/__init__.py` + `libs/gw2_api_client/src/gw2_api_client/client.py` + `libs/gw2_api_client/src/gw2_api_client/exceptions.py` + `libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py` (for the EliteSpec lookup call site)
**Audit mode:** standard effort; targeted deep pass on the library surfaces (frozen Pydantic models + IntEnum disambiguation + httpx retry policy + Protocol contract); 3 HIGH-confidence findings selected for planning (all MED severity)

### v0.9.11 status table

| # | Plan | Status | Addresses finding | Effort |
|---|---|---|---|---|
| 037 | [037-v0911-elite-spec-collision-fix](./037-v0911-elite-spec-collision-fix.md) | **pending** (NEW module-level `_ELITE_SPEC_DISAMBIGUATION: Final[dict[int, dict[Profession, EliteSpec]]]` table as the single source of truth for the 2 known collision cases (byte 55: Thief DAREDEVIL vs Ranger SOULBEAST; byte 63: Revenant RENEGADE vs Elementalist WEAVER); NEW `disambiguate_elite_spec(raw_value, profession) -> EliteSpec` function uses the agent's profession to pick the right member + falls back to `EliteSpec(raw_value)` for non-collision bytes (preserves Python IntEnum canonical behaviour); updated `EliteSpec` class docstring documents the disambiguation contract; 1-line change in the parser at the EliteSpec lookup call site: `elite = EliteSpec(agent.elite_raw)` → `elite = disambiguate_elite_spec(agent.elite_raw, agent.profession)`; NEW `libs/gw2_core/tests/test_models.py` with 6 hermetic tests covering the 4 disambiguated cases + the non-collision fallback + the UNKNOWN-profession fallback) | #1 `EliteSpec` IntEnum has 2 value collisions: `SOULBEAST = 55` collides with `DAREDEVIL = 55`; `WEAVER = 63` collides with `RENEGADE = 63`. Python IntEnum returns the first defined member, so `EliteSpec(55)` → DAREDEVIL even when the agent is a Ranger/Soulbeast (correctness, MED) | S |
| 038 | [038-v0911-retry-after-jitter](./038-v0911-retry-after-jitter.md) | **pending** (NEW `_apply_jitter(delay)` helper with ±20% uniform jitter; updated 429 handling block in `_get_with_retries` respects the `Retry-After` header (HTTP RFC 7231 §7.1.3) when present + falls back to the existing exponential backoff (0.5, 1.0, 2.0) when absent or malformed; jitter is applied to BOTH `Retry-After`-derived and exponential-fallback delays to avoid thundering herd; 5 NEW hermetic tests cover the 3 Retry-After paths (present + valid, missing, malformed) + 2 jitter properties (bounded to ±20%, mean unchanged over 10000 samples)) | #2 `gw2_api_client` does NOT respect the `Retry-After` header on 429 responses -- a server saying "retry in 30s" is bypassed by the fixed 0.5/1.0/2.0s backoff; client retries too soon, gets 429 again, exhausts 3-attempt budget in ~3.5s instead of 30s; no jittered backoff amplifies the thundering herd on concurrent calls (reliability, MED) | S |
| 039 | [039-v0911-worlds-get-ids-chunking](./039-v0911-worlds-get-ids-chunking.md) | **pending** (NEW `_MAX_IDS_PER_REQUEST: Final[int] = 200` constant matching the GW2 v2 API cap; refactored `worlds_get` body chunks the input into batches of 200 + issues one request per batch + concatenates results in input order (relies on the GW2 v2 API echoing input order); 5 NEW hermetic tests cover the 5 chunking cases: empty input short-circuits to `[]`, 200-id input is 1 request (boundary), 201-id input is 2 requests, 500-id input is 3 requests, results concatenated in input order) | #3 `worlds_get(ids)` does NOT cap at 200 ids -- a caller passing >200 ids gets a 400 Bad Request from the GW2 v2 API; a caller passing >~1300 ids gets a 414 URI Too Long from the HTTP layer (Caddy/nginx/Apache all cap URLs at ~8KB); the immediate caller in apps/api passes a single-element list (unaffected), but a future bulk-caller would hit the issue (correctness + reliability, MED) | S |

### Recommended execution order (v0.9.11)

1. **Plan 037** (EliteSpec collisions) — S effort, the correctness fix. Closes a real misclassification bug for Soulbeast + Weaver players. Self-contained (1 models.py edit + 1 parser.py 1-liner + 1 NEW test file). Independent of 038/039.
2. **Plan 038** (Retry-After + jitter) — S effort, the reliability fix. Closes the "client bypasses server-specified backoff" bug. Self-contained (1 client.py edit + 1 NEW test file). Independent.
3. **Plan 039** (worlds_get chunking) — S effort, the correctness + reliability fix. Closes the "caller has to manually chunk" UX debt. Self-contained (1 client.py edit + 1 NEW test file). Independent.

All 3 are independent. Could ship in any order. The recommended order is by surface (data model first, then HTTP client).

### Dependency graph (v0.9.11)

```
  plan 037 ─┐                          (gw2_core/models.py + parser.py + test_models.py)
  plan 038 ─┼── INDEPENDENT ────────── (gw2_api_client/client.py + test_client.py)
  plan 039 ─┘                          (gw2_api_client/client.py + test_client.py)
```

Plans 038 + 039 both touch `libs/gw2_api_client/src/gw2_api_client/client.py` and `libs/gw2_api_client/tests/test_client.py` -- they should be PR'd together or sequentially in the same PR to avoid merge conflicts in those 2 files. Plan 037 touches different files and can be PR'd in parallel.

### Considered and rejected (v0.9.11)

- **Bundle 038 + 039 into one "gw2_api_client hardening" plan**: tempting (both touch the same file). The 2 plans are independent at the test fixture level (038 fixes the retry policy; 039 fixes the chunking); bundling would conflate the retry-policy invariant with the chunking invariant, making either one harder to revert if regressed in CI. The plan recommends PR'ing them sequentially in the same PR to avoid 2 separate PRs touching the same file.
- **Plan 037 alternative: deduplicate the EliteSpec IntEnum values** (assign unique integers to Soulbeast + Weaver): out of scope -- the arcdps byte values are the source of truth; the Python enum values are a Python-language mirror. Changing the Python values would break the canonical ``EliteSpec(int_value)`` round-trip for non-collision cases.
- **Plan 037 alternative: add a date-based disambiguation** (e.g. "pre-2018 Daredevil, post-2018 Soulbeast"): out of scope -- the arcdps byte alone does not carry a timestamp; the build_version field is a release date (e.g. ``20250925``) but the release-date-to-elite-id mapping is undocumented and is a future enhancement.
- **Plan 037 alternative: add a new ``EliteSpecRaw`` enum with unique values for the disambiguated cases**: out of scope -- the 2-element disambiguation table is sufficient for the 2 known collision cases; a new enum would be over-engineered.
- **Plan 038 alternative: switch to ``tenacity`` / ``backoff``**: out of scope -- the hand-rolled retry loop is sufficient; a library would add a dep for the same behaviour.
- **Plan 038 alternative: add a circuit breaker** (N failures → open for M seconds): out of scope -- too complex for a small library; the canonical pattern is for the caller to add a circuit breaker on top of this client.
- **Plan 038 alternative: respect ``Retry-After`` on 503 Service Unavailable**: out of scope -- the current 503 handling raises ``GuildWars2HttpError`` immediately; a future plan can add 503-with-Retry-After retry support.
- **Plan 038 alternative: parse HTTP-date format for ``Retry-After``**: out of scope -- the GW2 v2 API uses seconds-only; HTTP-date parsing would be over-engineered.
- **Plan 039 alternative: add async parallelism (``asyncio.gather``) to the chunked requests**: out of scope -- serial requests respect the per-IP rate limit; parallel requests would amplify the rate-limit pressure.
- **Plan 039 alternative: switch ``worlds_get`` to a generator (lazy evaluation)**: out of scope -- the canonical pattern for small inputs is "fetch all, return all".
- **Plan 039 alternative: document the 200-id cap in the Protocol docstring**: out of scope -- the cap is an implementation detail; the Protocol's contract is "fetch world metadata for the given ids".

## v0.9.12 audit (closed)

**Author:** senior-advisor audit (improve skill, standard effort) — main/db/storage/config deep pass (the core infrastructure surfaces never audited; `main.py` is the FastAPI app entrypoint with CORS + lifespan + MCP mount; `database.py` is the SQLAlchemy 2.0 engine + sessionmaker; `storage.py` is the MinIO client + bucket bootstrap; `config.py` is the Pydantic v2 Settings)
**Stamped at:** `44ea862` (origin/main HEAD at audit time — after the v0.9.11 libs/gw2_core + libs/gw2_api_client pass landed: 3 plans 037-039 written + indexed)
**Recon scope:** `apps/api/src/gw2analytics_api/main.py` + `apps/api/src/gw2analytics_api/database.py` + `apps/api/src/gw2analytics_api/storage.py` + `apps/api/src/gw2analytics_api/config.py`
**Audit mode:** standard effort; targeted deep pass on the core infrastructure (FastAPI app entrypoint + SQLAlchemy engine + MinIO client + Pydantic settings); 3 findings selected for planning (2 MED reliability + 1 LOW ops-ergonomics)

### v0.9.12 status table

| # | Plan | Status | Addresses finding | Effort |
|---|---|---|---|---|
| 040 | [040-v0912-sqlalchemy-pool-config](./040-v0912-sqlalchemy-pool-config.md) | **pending** (4 NEW `Settings` fields: `db_pool_size` (default 5), `db_max_overflow` (default 10), `db_pool_timeout` (default 30s), `db_pool_recycle` (default 3600s); updated `create_engine(...)` to use the 4 fields + documented the N-worker connection budget math (``budget = N * (db_pool_size + db_max_overflow)``; Postgres default ``max_connections=100`` is sufficient for N<=6 workers with the defaults); `apps/api/.env.example` gains the 4 env vars with per-env tuning guidance; 5 NEW hermetic tests in NEW `apps/api/tests/test_database.py` cover the 4 pool params + the N=6 safety check) | #1 `database.py::get_engine` uses SQLAlchemy 2.0 defaults (pool_size=5, max_overflow=10, pool_recycle=-1) — for 8 uvicorn workers the connection budget is 120 which exceeds the Postgres default ``max_connections=100`` (``FATAL: too many connections`` under load); no `pool_recycle` means stale-connection risk from Postgres `idle_in_transaction_session_timeout` (reliability, MED) | S |
| 041 | [041-v0912-secret-str-credentials](./041-v0912-secret-str-credentials.md) | **pending** (3 `Settings` fields switched to Pydantic v2 `SecretStr`: `database_url`, `minio_access_key`, `minio_secret_key`; 1-line change in `database.py::get_engine` to call `.get_secret_value()` on `database_url`; 1-line change in `storage.py::get_minio` to call `.get_secret_value()` on `minio_access_key` + `minio_secret_key`; 4 NEW hermetic tests in `apps/api/tests/test_config.py` cover the 4 secret-handling paths: SecretStr type, `get_secret_value()` returns raw, `repr(settings)` does NOT include raw secret values, `settings.model_dump()` returns `SecretStr` instances (not raw strings) for the secret fields) | #2 `config.py::Settings` stores credentials as plain `str` — a naive `logger.info(settings.model_dump())` would print `database_url` (which embeds the Postgres password) + `minio_secret_key` (the MinIO root password) in plain text in the log stream; Pydantic v2 `SecretStr` redacts via `__repr__` automatically (security defence in depth, MED) | S |
| 042 | [042-v0912-main-py-hardening](./042-v0912-main-py-hardening.md) | **pending** (2 NEW `Settings` fields: `enable_mcp` (default false, prod-safe), `enable_openapi_docs` (default false, prod-safe); NEW `_resolve_app_version()` helper uses `importlib.metadata.version("gw2analytics_api")` to sync the OpenAPI `version` from the installed package (no more hard-coded `"0.8.6"` drift); NEW `_build_app()` factory lets the test create a fresh app with different settings without re-importing; the `FastAPI(...)` constructor uses `docs_url`/`redoc_url`/`openapi_url=None` when `ENABLE_OPENAPI_DOCS=false`; the `FastApiMCP(app).mount()` call is gated behind `ENABLE_MCP`; `apps/api/.env.example` documents the 2 env vars; 5 NEW hermetic tests in NEW `apps/api/tests/test_main.py` cover the 3 hardening surfaces: MCP gating, OpenAPI docs gating, app version sync) | #3 `main.py` has 3 ops-ergonomics gaps: `FastApiMCP(app).mount()` runs at module import (always on, no opt-out); `version="0.8.6"` is hard-coded (drift from `pyproject.toml` after every release); OpenAPI docs (`/docs` + `/redoc` + `/openapi.json`) are exposed in prod by default (reconnaissance surface) (ops-ergonomics, LOW) | S |

### Recommended execution order (v0.9.12)

1. **Plan 041** (SecretStr) — S effort, the security defence-in-depth fix. Self-contained (1 config.py + 2 unwrap sites + 4 NEW tests). Independent of 040/042.
2. **Plan 040** (SQLAlchemy pool) — S effort, the reliability fix. Self-contained (1 database.py + 1 config.py + 1 .env.example + 5 NEW tests). Independent.
3. **Plan 042** (main.py hardening) — S effort, the ops-ergonomics fix. Self-contained (1 main.py + 1 config.py + 1 .env.example + 5 NEW tests). Independent.

All 3 are independent. Could ship in any order. The recommended order is by severity (security defence in depth > reliability > ops-ergonomics).

### Dependency graph (v0.9.12)

```
  plan 040 ─┐                          (database.py + config.py + .env.example + test_database.py)
  plan 041 ─┼── INDEPENDENT ────────── (config.py + database.py + storage.py + test_config.py)
  plan 042 ─┘                          (main.py + config.py + .env.example + test_main.py)
```

All 3 plans touch `config.py` (additive: new fields only) -- they can be PR'd together as a single "config hardening" PR, or sequentially in separate PRs. Plans 040 + 042 also touch `.env.example` (additive: new env vars only); plan 041 also touches `database.py` + `storage.py` (1-line unwrap calls).

### Considered and rejected (v0.9.12)

- **Bundle 040 + 041 + 042 into one "infra hardening" plan**: tempting (all 3 touch `config.py`). The 3 plans are independent at the test fixture level (040 = pool config; 041 = SecretStr; 042 = main.py + docs gating); bundling would conflate the pool-config invariant with the SecretStr invariant with the main.py gating invariant, making any one of them harder to revert if regressed in CI. The plan recommends PR'ing them as 1-3 separate PRs (config.py changes are additive so merge conflicts are minor).
- **Plan 040 alternative: switch to async SQLAlchemy (asyncpg)**: out of scope -- the v0.9.2 hardening posture is sync-FastAPI; async pivot is a future cycle.
- **Plan 040 alternative: add Prometheus metrics for the pool** (checked-out count, overflow count): out of scope -- observability is a future hardening.
- **Plan 040 alternative: add connection-level retry on ``OperationalError``**: out of scope -- the per-request session pattern + ``pool_pre_ping`` is the canonical defense.
- **Plan 041 alternative: encrypt the secrets at rest** (SOPS, Vault, pgcrypto envelope encryption): out of scope -- the v0.9.1 deferred list tracks "webhook secret-at-rest"; the same architecture applies here.
- **Plan 041 alternative: switch ``minio_endpoint`` to ``SecretStr``**: out of scope -- the endpoint is not a secret (it's the host:port of the MinIO server, which is visible in the URL bar of the MinIO console).
- **Plan 041 alternative: add a custom log filter** that redacts known secret patterns: out of scope -- Pydantic v2 ``SecretStr`` is the canonical defence; a custom log filter is over-engineered.
- **Plan 042 alternative: switch to a different MCP framework**: out of scope -- the current ``FastApiMCP`` is the canonical FastAPI MCP integration.
- **Plan 042 alternative: add per-route doc visibility** (FastAPI's ``include_in_schema`` parameter): out of scope -- the per-route docs are intentional; the plan only changes the global gating.
- **Plan 042 alternative: add a "version mismatch" warning at startup** (e.g. if ``pyproject.toml`` says 0.9.3 but the installed package is 0.9.2): out of scope -- the ``importlib.metadata`` approach ensures the version always matches the installed package.

## v0.9.13 audit (closed)

**Author:** senior-advisor audit (improve skill, standard effort) — test suite patterns deep pass (the surface never audited; `apps/api/tests/conftest.py` for test isolation, `apps/api/tests/_fixtures.py` for shared .zevtc blob builders, `web/tests/setup.ts` for vitest setup, `web/tests/e2e/mock-server.mjs` for Playwright E2E mock server)
**Stamped at:** `44ea862` (origin/main HEAD at audit time — after the v0.9.12 main/db/storage/config pass landed: 3 plans 040-042 written + indexed)
**Recon scope:** `apps/api/tests/conftest.py` + `apps/api/tests/_fixtures.py` + `web/tests/setup.ts` + `web/tests/e2e/mock-server.mjs`
**Audit mode:** standard effort; targeted deep pass on the test infrastructure (per-test cleanup, shared fixtures, vitest setup, mock server); 2 findings selected for planning (1 MED test reliability + 1 LOW DX)

### v0.9.13 status table

| # | Plan | Status | Addresses finding | Effort |
|---|---|---|---|---|
| 043 | [043-v0913-vitest-after-each-cleanup](./043-v0913-vitest-after-each-cleanup.md) | **pending** (3-line addition to `web/tests/setup.ts`: `import { cleanup } from "@testing-library/react"; afterEach(cleanup);` — the canonical @testing-library/react + vitest integration pattern, missing from the current setup; the cleanup is a no-op for the page-level Server Component tests that don't use `render`; NEW `web/tests/components/cleanup.test.tsx` with 2 regression tests that assert the first test's DOM is removed after the test + the second test's DOM is pristine) | #1 `web/tests/setup.ts` is missing the canonical `@testing-library/react` cleanup hook — every component-level test that uses `render` leaves its DOM nodes mounted in `document.body`; the next test starts with a polluted DOM (the previous test's nodes + the new test's nodes), silently corrupting `getByRole` / `querySelectorAll` assertions that count elements (test reliability, MED) | S |
| 044 | [044-v0913-post-minimal-fight-error-message](./044-v0913-post-minimal-fight-error-message.md) | **pending** (updated `apps/api/tests/_fixtures.py::wait_for_upload_completion` — the for loop now tracks `last_status` + `last_error` locals; the AssertionError on timeout includes ``(last_status={status!r}, last_error={error!r})`` with a docstring explaining the 2 cases (parser failure vs BG task hang); NEW hermetic test in `apps/api/tests/test_backfill.py` POSTs a blob with an invalid EVTC header (``b"NOT_EVTC"``) + asserts the AssertionError includes ``"last_status='failed'"`` + the parser's error message mentions ``"EVTC"``) | #2 `apps/api/tests/_fixtures.py::wait_for_upload_completion` raises a cryptic `AssertionError("upload X did not reach 'completed' within 5s")` on parser failure — the message does NOT include the upload's `status` (was it `"failed"`? still `"pending"`?) or the `error_message` (the parser's structured error); the operator has to re-poll the upload manually via `curl` to diagnose (DX, LOW) | S |

### Recommended execution order (v0.9.13)

1. **Plan 043** (vitest cleanup) — S effort, the MED test reliability fix. Self-contained (1 setup.ts edit + 1 NEW test file). Independent of 044.
2. **Plan 044** (error message) — S effort, the DX fix. Self-contained (1 _fixtures.py edit + 1 NEW test case). Independent.

All 2 are independent. Could ship in any order. The recommended order is by severity (MED reliability > LOW DX).

### Dependency graph (v0.9.13)

```
  plan 043 ─── INDEPENDENT ──── (web/tests/setup.ts + cleanup.test.tsx)
  plan 044 ─── INDEPENDENT ──── (apps/api/tests/_fixtures.py + test_backfill.py)
```

No shared file paths. Could be PR'd in parallel by 2 different engineers.

### Considered and rejected (v0.9.13)

- **Plan 043 alternative: migrate from `@testing-library/react` to a different testing library** (e.g. ``@testing-library/vue`` for Vue, or a hand-rolled ``renderToString`` wrapper): out of scope -- the current library is the canonical React testing pattern; the ``afterEach(cleanup)`` hook is the canonical integration point.
- **Plan 043 alternative: add a global ``beforeEach`` for DOM setup** (e.g. resetting the URL, clearing localStorage): out of scope -- the current tests don't need it; a future test that does can add a focused ``beforeEach``.
- **Plan 043 alternative: refactor the per-component test files to share a common test wrapper** (e.g. a ``renderWithProviders`` helper): out of scope -- the cleanup hook is the minimal fix; a test-wrapper refactor is a larger DX investment.
- **Plan 044 alternative: reduce the 5s ceiling**: out of scope -- the 5s wait is generous (a real parser failure flips to ``"failed"`` within 100ms); the 5s ceiling catches a real hang (e.g. a deadlock in the BG task) without false-positiving on slow CI. A future hardening pass can lower the ceiling to 2s.
- **Plan 044 alternative: add structured logging to the BG parser task** to surface the failure earlier: out of scope -- the parser's ``error_message`` field on the uploads table is the canonical failure surface; the test helper reads the field directly.
- **Plan 044 alternative: catch the parser failure at the test-fixture level with a custom exception** (e.g. ``raise ParserFailure(upload_id, status, error_message)``): out of scope -- the canonical ``AssertionError`` is sufficient; adding a custom exception would force every test to handle it, increasing boilerplate.

## v0.9.14 audit (closed)

**Author:** senior-advisor audit (improve skill, standard effort) — `apps/api/src/gw2analytics_api/services.py` deep pass (the central persistence module never audited in depth; ``process_parse`` is the BG task that parses uploaded ``.zevtc`` blobs, persists the fight row + agents + skills + events blob + per-(fight, account) summary, and flips the upload status to ``completed``/``failed``)
**Stamped at:** `44ea862` (origin/main HEAD at audit time — after the v0.9.13 test suite patterns pass landed: 2 plans 043-044 written + indexed)
**Recon scope:** `apps/api/src/gw2analytics_api/services.py`
**Audit mode:** standard effort; targeted deep pass on the persistence module (BG task lifecycle, exception handling, bulk INSERT performance); 2 findings selected for planning (1 MED reliability + 1 LOW perf)

### v0.9.14 status table

| # | Plan | Status | Addresses finding | Effort |
|---|---|---|---|---|
| 045 | [045-v0914-process-parse-commit-failure](./045-v0914-process-parse-commit-failure.md) | **pending** (10-line addition to `process_parse` -- the final `db.commit()` on the happy path is wrapped in a `try/except SQLAlchemyError` block; on failure: `logger.exception(...)` + `db.rollback()` + `upload.status = UPLOAD_STATUS_FAILED` + `upload.error_message = f"SQLAlchemyError: {exc}"` + a best-effort retry commit (itself wrapped in a second `try/except` to surface a double-failure to the BG task runner); 1 NEW hermetic test in `apps/api/tests/test_uploads_e2e.py` that monkeypatches `db.commit()` to raise `OperationalError` on the first call + asserts the upload status flips to ``"failed"`` with the expected error message) | #1 `process_parse` does NOT catch `SQLAlchemyError` on the final `db.commit()` in the happy path — a transient commit failure (Postgres connection drop, serialisation failure, pool timeout) propagates to the FastAPI `BackgroundTasks` runner (which logs but does NOT surface to the operator), leaving the upload stuck at `status="pending"` forever; the operator has no log line + the upload envelope doesn't reflect the failure (reliability, MED) | S |
| 047 | [047-v0914-bulk-insert-player-summaries](./047-v0914-bulk-insert-player-summaries.md) | **pending** (`_persist_player_summaries` refactored: the for-loop with `db.add(OrmFightPlayerSummary(...))` is replaced with a single `db.execute(insert(OrmFightPlayerSummary), [list_of_dicts])` call; the DELETE before the INSERTs is unchanged; SQLAlchemy 2.0's `insertmanyvalues` slicing handles N > 1000 automatically; 1 NEW hermetic test seeds a 100-player fight + asserts the INSERT is batched into 1 statement (or a small number of ``insertmanyvalues``-sliced statements) + asserts the per-account totals match) | #2 `_persist_player_summaries` does N individual `db.add(...)` calls -- for a 100-player WvW raid, 100 round-trip INSERTs; for a 1000-player WvW zerg, 1000 INSERTs. The canonical SQLAlchemy 2.0 batched-INSERT pattern (`db.execute(insert(...), [list_of_dicts])`) is ~10x faster for N >= 50; the canonical WvW raid sees a 50ms -> 5ms improvement; the cumulative gain across many concurrent uploads is meaningful for busy weekends (perf, LOW) | S |

### Recommended execution order (v0.9.14)

1. **Plan 045** (commit-failure handling) — S effort, the MED reliability fix. Closes the "upload stuck at pending forever" silent-failure path. Self-contained (1 services.py edit + 1 NEW test case). Independent of 047.
2. **Plan 047** (bulk INSERT) — S effort, the LOW perf fix. Self-contained (1 services.py edit + 1 NEW test case). Independent.

All 2 are independent. Could ship in any order. The recommended order is by severity (MED reliability > LOW perf).

### Dependency graph (v0.9.14)

```
  plan 045 ─── INDEPENDENT ──── (services.py + test_uploads_e2e.py)
  plan 047 ─── INDEPENDENT ──── (services.py + test_uploads_e2e.py)
```

Both plans touch `apps/api/src/gw2analytics_api/services.py` (additive: each adds a new block, no overlapping edits) -- they can be PR'd together as a single "services.py hardening" PR, or sequentially in separate PRs. Both plans add 1 new test case to `apps/api/tests/test_uploads_e2e.py` (additive: each adds a new test, no overlapping edits).

### Considered and rejected (v0.9.14)

- **Plan 045 alternative: adding retry-on-commit with exponential backoff**: out of scope -- a transient commit failure is a per-fight issue; retrying the commit would re-execute the same SQL with the same state, which is the same race condition. The operator can re-upload the blob to retry.
- **Plan 045 alternative: migrating to a dedicated worker queue (Arq) with a fresh worker-scoped session**: out of scope -- the v0.9.2 hardening posture is sync-FastAPI; the ``process_parse`` docstring's TODO is deferred to a future cycle.
- **Plan 045 alternative: adding a watchdog that reaps stuck ``status="pending"`` uploads after N hours**: out of scope -- the canonical fix is for the BG task to surface the failure (plan 045); the watchdog is a belt-and-braces second line of defence that can be added in a v0.9.15+ hardening pass.
- **Plan 045 alternative: narrowing the existing ``except Exception`` in ``_persist_event_blob``**: out of scope -- already covered by plan 019 (v0.9.5 cleanup pass).
- **Plan 047 alternative: switching to SQLAlchemy Core's ``Table.insert``**: out of scope -- the ORM ``insert()`` is the canonical SQLAlchemy 2.0 pattern and produces the same SQL.
- **Plan 047 alternative: adding an explicit ``insertmanyvalues`` slice parameter**: out of scope -- SQLAlchemy 2.0's default slicing (1000 rows per slice) is sufficient for the canonical N (50-100 players). A future hardening pass can add an explicit slice parameter if the canonical N grows past 1000.
- **Plan 047 alternative: changing the DELETE+INSERT pattern to upsert** (``INSERT ... ON CONFLICT``): out of scope -- the DELETE+INSERT is the canonical "replace rows atomically" pattern; a future plan can switch to upsert if the Postgres ``ON CONFLICT`` pattern is desired.

## v0.9.23 audit (closed)

**Author:** senior-advisor audit (improve skill, standard effort) — web/tests/e2e deep pass (the e2e specs + fixtures never audited in depth: the component/app/lib tests were covered by v0.9.6/v0.9.7/v0.9.9 + the e2e setup + mock-server were touched by v0.9.13, but the 7 e2e specs + 8 fixture JSON files never had a senior-advisor pass)
**Stamped at:** `44ea862` (origin/main HEAD at audit time — after the v0.9.22 web/app layout + CSS pass landed: 3 plans 068/069/070 written + indexed)
**Recon scope:** `web/tests/e2e/fights.spec.ts` + `players-timeline.spec.ts` + `landing.spec.ts` + `account.spec.ts` + `upload.spec.ts` + `visual-regression.spec.ts` + `players.spec.ts` + 8 fixture JSON files (`fights-list.json` + `fight-events.json` + `fight-squads.json` + `fight-skills.json` + `players-list.json` + `player-profile.json` + `player-profile-alt.json` + `player-timeline.json`)
**Audit mode:** standard effort; targeted deep pass on the e2e specs + fixtures for the patterns not covered by v0.9.6 (component tests) or v0.9.7 (page tests) or v0.9.9 (lib tests); 3 findings selected for planning (3 LOW DX)

### v0.9.23 status table

| # | Plan | Status | Addresses finding | Effort |
|---|---|---|---|---|
| 071 | [071-v0923-pageerror-helper-extraction](./071-v0923-pageerror-helper-extraction.md) | **pending** (NEW `web/tests/e2e/_helpers.ts` module exports `captureNoUncaughtExceptions(page) -> () => void` (closure-return pattern: the listener is added synchronously before the test body, the returned closure is called at the end to assert the captured errors list is empty); the 3 specs (`landing.spec.ts` + `account.spec.ts` + `upload.spec.ts`) refactor to import the helper + drop the inline 4-line `pageErrors` array + the inline `expect(pageErrors).toEqual([])` assertion. 7 NEW hermetic tests cover the 7 surfaces) | #1 The `pageerror` listener + assertion pattern is duplicated verbatim in 3 e2e specs (`landing.spec.ts` + `account.spec.ts` + `upload.spec.ts` — each has the 4-line `const pageErrors = []; page.on("pageerror", ...); ... expect(pageErrors).toEqual([]);` block). A future maintainer who changes the pattern (e.g., adds a 4th spec, or modifies the error filter, or fixes a listener-timing bug) must update 3 sites instead of 1 (DX, LOW) | S |
| 072 | [072-v0923-visual-regression-cases-extraction](./072-v0923-visual-regression-cases-extraction.md) | **pending** (NEW `web/tests/e2e/_visual_regression.ts` module exports the 4 shared constants: `DIFF_THRESHOLD = 0.01` (the 1% total-diff threshold, with a docstring pointing to CONTRIBUTING.md for the empirical derivation), `VisualRegressionCase` interface (the `{name, route, baseline}` shape), `VISUAL_REGRESSION_CASES: ReadonlyArray<VisualRegressionCase>` (the 8 cases — landing + account + upload + fights + players + 2 player-timeline cases + fight-drilldown, with a docstring documenting the 3 sync sites: this module + the screenshot script's PAGES array + CONTRIBUTING.md), `BASELINE_DIR = join(process.cwd(), "..", "docs", "screenshots")` (the canonical artifact store), `DIFF_OUTPUT_DIR = join(process.cwd(), "tests", "e2e", ".visual-regression-output")` (the gitignored diff-output dir). `visual-regression.spec.ts` refactors to import the 4 constants + drops the inline definitions. 7 NEW hermetic tests cover the 7 surfaces) | #2 `visual-regression.spec.ts` (~220 lines) defines 3 module-level constants inline (`DIFF_THRESHOLD` + `VISUAL_REGRESSION_CASES` + `BASELINE_DIR`/`DIFF_OUTPUT_DIR`); a future maintainer who adds a 9th route must update 3 sites (the spec's cases + the screenshot script's PAGES + CONTRIBUTING.md); the 3 constants are the canonical "where the 8 routes are listed" source (DX, LOW) | S |
| 073 | [073-v0923-visual-regression-parallel-execution](./073-v0923-visual-regression-parallel-execution.md) | **pending** (`visual-regression.spec.ts::test.describe("visual regression (v0.8.9 plan/003)", () => { ... })` gains the `.parallel` modifier → `test.describe.parallel("visual regression (v0.8.9 plan/003)", () => { ... })`; the 8 cases (which are independent: per-test fresh `page` fixture, unique `.tmp-${baseline}` temp files, unique `${baseline}` diff-output filenames, no shared state between cases) are split across the 2-worker CI pool = ~50% wall-clock reduction in the visual-regression suite (2.8 s → 1.4 s per CI run); local dev loops get the equivalent reduction with the default Playwright worker pool. 5 NEW hermetic tests cover the 5 surfaces) | #3 `visual-regression.spec.ts` uses the default `test.describe(...)` (serial execution within the describe block); the 8 cases are independent (per-test fresh `page` + unique temp files + unique diff outputs) so serial execution is a missed wall-clock optimization (the `DIFF_OUTPUT_DIR` is shared but `mkdir` is idempotent + `writeFile` is atomic per call + the cleanup is best-effort — no race condition) (perf, LOW) | S |

### Recommended execution order (v0.9.23)

1. **Plan 071** (pageerror helper) — S effort, the smallest single fix. 1 NEW helper file + 3 spec refactors + 7 tests. Independent of 072/073.
2. **Plan 072** (visual-regression constants) — S effort, the second helper extraction. 1 NEW constants module + 1 spec refactor + 7 tests. Independent of 071/073.
3. **Plan 073** (parallel execution) — S effort, the perf win. 1-line change (`test.describe` → `test.describe.parallel`) + 5 tests. **Depends on plan 072** (the `.parallel` modifier references `VISUAL_REGRESSION_CASES` which plan 072 extracts to a shared module; the dependency is not strict — the `.parallel` change could land first — but the constants extraction makes the parallel-mode test setup cleaner).

All 3 are essentially independent. Could ship in any order. The recommended order is by clarity (helper extraction first, then constants extraction, then perf).

### Dependency graph (v0.9.23)

```
  plan 071 ─── INDEPENDENT ──── (web/tests/e2e/_helpers.ts + 3 spec refactors + tests)
  plan 072 ─── INDEPENDENT ──── (web/tests/e2e/_visual_regression.ts + 1 spec refactor + tests)
  plan 073 ─── INDEPENDENT ──── (web/tests/e2e/visual-regression.spec.ts + tests)
```

Plans 071 + 072 both create new files in `web/tests/e2e/` (the helper module + the constants module); they don't touch each other. Plan 073 modifies 1 line in the existing spec. Could be PR'd in any order or in parallel by 3 different engineers.

### Considered and rejected (v0.9.23)

- **Plan 071 alternative: put the helper in a global `web/tests/_setup.ts` file** (the vitest setup file): tempting (shared between vitest + Playwright). The helper is Playwright-specific (uses `Page` + `expect` from `@playwright/test`); mixing Playwright + vitest setup would force a conditional import.
- **Plan 071 alternative: add a `beforeEach` + `afterEach` global setup** in `playwright.config.ts`: tempting (auto-applies to all tests). The pattern is "per-test assertion, not per-suite" — the `afterEach` would assert the same thing for all tests, but the `fights.spec.ts` and `players.spec.ts` have tests that intentionally exercise error paths (e.g., a 404 page that doesn't throw but does render an upstream-error card). The global setup would false-positive those tests.
- **Plan 071 alternative: use a `playwright/test` fixture pattern** (declare a custom fixture in a `fixtures.ts` module): more idiomatic for Playwright. The fixture pattern requires the test to destructure the custom fixture in the test function signature. The closure-return pattern is simpler and matches the existing call sites with a 1-line change.
- **Plan 071 alternative: use `console.error` instead of `pageerror`** (the comment notes `pageerror` is more precise than `console.error` because the latter also fires on dev-mode React hydration warnings): tempting (simpler listener). The current `pageerror` is the correct signal; the docstring documents the choice. A future maintainer who reads the comment will not "fix" the choice to `console.error`.
- **Plan 072 alternative: move the constants to a `playwright.config.ts` export**: tempting (single source of truth). The Playwright config is the test runner's config; mixing test data (the 8 cases) with runner config (`testDir`, `use.baseURL`, etc.) is a separation of concerns violation.
- **Plan 072 alternative: generate the cases from a YAML / JSON file**: out of scope (the TypeScript array is the canonical representation; a future plan can add a YAML generator if the list grows).
- **Plan 072 alternative: add the CI drift check (against the screenshot script + CONTRIBUTING.md) as part of this plan**: out of scope (the drift check is a future plan; this plan is the shared-module extraction only).
- **Plan 072 alternative: move the `pixelmatch` + `pngjs` import + the diff computation logic to the shared module too**: tempting (the spec becomes a 1-page "for-loop tests"). The test body is logic (not just constants); the body is the canonical test code that future maintainers will read to understand the visual-regression flow. Moving the body to a helper would make the spec unreadable.
- **Plan 072 alternative: use `import.meta.dirname` (Node 20.11+) instead of `process.cwd()`**: tempting (the path is more portable). The current code uses `process.cwd()` for consistency with the existing `screenshots.mjs` + the existing Playwright config. A future plan can switch both to `import.meta.dirname` if portability becomes a concern.
- **Plan 073 alternative: use Playwright's `--workers=N` flag** to force more workers: tempting (more parallelism). The CI invocation is `pnpm exec playwright test --project=visual-regression` (per the CI workflow); the `--workers` flag is a global config that affects all specs, not just visual-regression. Increasing workers globally may cause port conflicts (the mock server runs on port 8080) + browser memory pressure. The `.parallel` modifier is per-spec, which is the canonical scoping.
- **Plan 073 alternative: move the 8 cases to separate spec files** (1 per case): tempting (independent `test.describe` blocks can be parallelized by Playwright's per-file model). The 8 separate spec files would be a maintenance burden (8 files to keep in sync instead of 1); the `.parallel` modifier achieves the same wall-clock reduction with a 1-line change.
- **Plan 073 alternative: skip the parallel mode** (status quo is fine): tempting (the 2.8 s is not catastrophic). The 50% wall-clock reduction is a free win (no risk, no behavior change). The plan ships the change.
- **Plan 073 alternative: add `test.describe.configure({ mode: "parallel" })` at the top of the spec**: equivalent to the `.parallel` modifier. The `.parallel` modifier is the per-describe-block scope; `.configure({ mode: ... })` is the file-scope (affects all `describe` blocks in the file). The visual-regression spec has 1 describe block; either approach is equivalent. The `.parallel` modifier is more explicit (per-describe intent).
- **Plan 073 alternative: add a CI `--retries=2` for the visual-regression suite** (catch flaky PNGs): tempting (anti-flake). The `.parallel` mode + the existing `retries: isCI ? 2 : 0` (per `playwright.config.ts`) already retries 2x on CI. The plan doesn't change the retry policy.

## v0.9.24 audit (closed)

**Author:** senior-advisor audit (improve skill, standard effort) — `README.md` + `CHANGELOG.md` deep pass (the user-facing root docs never audited in depth: v0.9.20 covered the design docs + the contributor guide, but the actual user-visible README + CHANGELOG — both gas pedals for users + contributors — never had a senior-advisor pass)
**Stamped at:** `44ea862` (origin/main HEAD at audit time — after the v0.9.23 web/tests/e2e deep pass landed: 3 plans 071/072/073 written + indexed)
**Recon scope:** `README.md` (the root project README with the 4 sections: hero + quickstart + phase history + status) + `CHANGELOG.md` (the Keep-a-Changelog format root CHANGELOG with sectioned entries per version)
**Audit mode:** standard effort; targeted deep pass on the user-facing root docs for drift vs current state + missing links + duplicate entries + canonical format conformance; 3 findings selected for planning (3 LOW docs hygiene)

### v0.9.24 status table

| # | Plan | Status | Addresses finding | Effort |
|---|---|---|---|---|
| 074 | [074-v0924-readme-v09x-doc-debt](./074-v0924-readme-v09x-doc-debt.md) | **pending** (3 sub-fixes in `README.md`: (a) NEW "Release Tags" table mapping each shipped tag (v0.8.0 → v0.9.2) to its headline ship summary (the per-version 1-line "shipped X + Y + Z"); (b) refresh the "Phase history" timeline representation so v0.9.x is not just a single block (the v0.7.x → v0.8.x entries are individually detailed per shipped tag); (c) correct the "Status" line that currently references `v0.9.0` as latest to point to `v0.9.2` + mention the 3 v0.9.x cycles' themes. 7 NEW hermetic tests cover the 7 surfaces + a "Last refreshed at v0.9.2" footer is added to the bottom of the README) | #1 `README.md` has 3 v0.9.x doc debt issues: the Status line is stale ("v0.9.0" latest — does not reference the v0.9.1 + v0.9.2 cycles), no canonical Release Tags table (per shipped tag), Phase history format is ambiguous for v0.9.x (the v0.7.x → v0.8.x entries are individually detailed but v0.9.x is single-paragraph covering 3 cycles) (docs hygiene, LOW) | S |
| 075 | [075-v0924-changelog-unreleased-link-hydration-dupe](./075-v0924-changelog-unreleased-link-hydration-dupe.md) | **pending** (3 sub-fixes in `CHANGELOG.md`: (a) the `[Unreleased]` reference link is added to the bottom of the file (`[Unreleased]: https://github.com/roddy/gw2analytics/compare/v0.9.2...HEAD`) — the canonical Keep-a-Changelog §11 invariant requires every "in-flight" label to be defined at the bottom; (b) the 2 duplicate `fix(api): idempotency under hydration` entries under v0.9.2 (one for "plan 009 Step 1+2 atomic", one for "plan 009 Step 5 test isolation conftest") are merged into a single entry with a footnote pointing to plan 009 step 5; (c) the per-version compare links are added to the bottom for the 3 most recent shipped versions (`[v0.9.0]:`, `[v0.9.1]:`, `[v0.9.2]:`) per Keep-a-Changelog §11. 4 NEW hermetic tests cover the 4 surfaces + a "Last refreshed at v0.9.2" footer is added to the bottom of the CHANGELOG) | #2 `CHANGELOG.md` has 3 hygiene issues: `[Unreleased]` is referenced at the top but NO link definition at the bottom (Keep-a-Changelog §11 invariant violation — the file fails the Markdown reference-link check), the v0.9.2 hydration idempotency fix is duplicated as 2 separate entries (Step 1+2 atomic + test isolation conftest) which confuses contributors ("which one is canonical?"), the per-version compare links are missing for v0.9.0/v0.9.1/v0.9.2 (docs hygiene, LOW) | S |
| 076 | [076-v0924-readme-test-count-breakdown-table](./076-v0924-readme-test-count-breakdown-table.md) | **pending** (NEW "Test count" section in `README.md` after the existing test count line: a Markdown table breaking down the count per surface (apps/api pytest | libs/gw2_core pytest | libs/gw2_analytics pytest | libs/gw2_api_client pytest | libs/gw2_evtc_parser pytest | web vitest component | web vitest page | web vitest lib | web Playwright specs). The numbers are sourced from a NEW `scripts/test_count_breakdown.py` script that runs `pytest --collect-only -q` for the 5 Python libs + `pnpm exec vitest list --json` for the 3 web vitest surfaces + `pnpm exec playwright test --list --json` for the e2e specs, then aggregates the totals. The script is also wired into the CI job so the README breakdown is auto-regenerated on every PR. The README test count placeholder "303+ retro-tested, 22 web tests..." is replaced with the canonical breakdown; 6 NEW hermetic tests cover the 6 surfaces: 1 per source-collection step + 1 totals check + 1 re-run idempotency + 1 Markdown table parse + 1 CI wiring + 1 README substitution) | #3 `README.md` has a stale "303 active tests, 22 web tests" placeholder — no canonical source for the current count; no breakdown per surface; an operator who wants to know "how is our test suite distributed" has to run `pytest --collect-only` + `vitest list` + `playwright test --list` + sum the results manually (DX, LOW) | S |

### Recommended execution order (v0.9.24)

1. **Plan 074** (README v0.9.x doc debt) — S effort, the highest-visibility win (the README is the first thing a new contributor/operator sees). 1 README.md edit + 7 tests. Independent of 075/076.
2. **Plan 076** (test count breakdown) — S effort, the DX win for new contributors + operators. 1 README.md edit + 1 NEW script + 6 tests. Independent of 075.
3. **Plan 075** (CHANGELOG hygiene) — S effort, the canonical Keep-a-Changelog §11 invariant enforcement. 1 CHANGELOG.md edit + 4 tests. Independent.

All 3 are independent. Could ship in any order. The recommended order is by user-impact (top-of-README first, then DX, then CHANGELOG hygiene).

### Dependency graph (v0.9.24)

```
  plan 074 ──┐                              (README.md + tests)
  plan 075 ──┼── INDEPENDENT ──────────     (CHANGELOG.md + tests)
  plan 076 ──┘                              (README.md + NEW script + tests)
```

Plans 074 + 076 both touch `README.md` (additive: each adds a new section, no overlapping edits) — they can be PR'd together as a single "README hardening" PR, or sequentially in separate PRs to keep each diff small. Plan 075 touches a different file. Could be PR'd in parallel by 3 different engineers.

### Considered and rejected (v0.9.24)

- **Bundle 074 + 076 into one "README hardening" plan**: tempting (both touch README.md). The 2 plans are independent at the content level (074 = Release Tags table + Status line + Phase history; 076 = Test count breakdown table); bundling would conflate the doc-debt invariant with the test-count-DX invariant, making either one harder to revert if regressed. The plan recommends PR'ing them in a single combined PR (both touch README.md additively — minimal merge conflict risk).
- **Plan 074 alternative: ship a MkDocs-based docs site** (replacing README.md as the canonical docs surface): out of scope (a v0.10.x effort; the README + design docs are the canonical written surface for v0.9.x).
- **Plan 074 alternative: refresh only the Status line + skip the Release Tags table**: tempting (smaller PR). The Release Tags table is the canonical "what shipped per tag" surface; skipping it means a future contributor has to dig into CHANGELOG.md to find the per-version headline.
- **Plan 074 alternative: ship a "What is GW2Analytics?" preamble above the Status line** (rebrand the README): out of scope (a v1.0 effort; the existing "what it does" preamble is sufficient).
- **Plan 074 alternative: drop the Phase history section entirely** (the table covers it): tempting (less code). The Phase history narrative is the canonical "what changed across cycles" surface that the per-tag table does not cover (the tags ship dates + cycle themes).
- **Plan 074 alternative: use a different format than Markdown** (e.g., HTML): out of scope (the project standardizes on Markdown for the README).
- **Plan 075 alternative: migrate to release-please / changesets** (auto-generate the CHANGELOG): out of scope (per the deferred list in v0.9.8 plan 028; canonical manual flow until the project scales to multi-release-per-week).
- **Plan 075 alternative: only fix the Unreleased link** (not the other 2): tempting (smaller PR). The duplicate hydration idempotency entries are an immediate readability problem that confuses contributors ("which one is canonical?").
- **Plan 075 alternative: rewrite the entire CHANGELOG.md from v0.x.0 forward**: out of scope (a v1.0 effort; the per-version entries are the canonical historical record).
- **Plan 075 alternative: drop the `[v0.9.X]: compare/v0.9.(X-1)...v0.9.X` links** (noted as "not required by Keep-a-Changelog"): out of scope (the canonical Keep-a-Changelog §11 invariant RECOMMENDS compare links; they make GitHub diffs 1-click).
- **Plan 076 alternative: keep the "303+ active tests" placeholder**: tempting (zero-effort). The canonical breakdown is a low-effort addition (1 script + 1 README section); the placeholder drifts on every commit.
- **Plan 076 alternative: hardcode the breakdown in Markdown** (no script): tempting (simpler). The hardcoded numbers drift on every commit; the script is the canonical source that the CI can re-run.
- **Plan 076 alternative: source the numbers from the CI artifact upload** (avoid running pytest/vitest in the README generator): out of scope (the canonical source IS pytest/vitest/playwright; the script just reads the same numbers CI sees).
- **Plan 076 alternative: include E2E test runtime as a second column** (helpful for spotting slow tests): out of scope (the canonical "test count" is just N; runtime tracking is a future observability pass).

## v0.9.25 audit (closed)

**Author:** senior-advisor audit (improve skill, standard effort) — `routes/webhooks.py` + 4 `__init__.py`/`__main__.py`/`health.py` + `ag-grid-setup.ts` deep pass (the untrodden surfaces discovered during the v0.9.24 docs hygiene check: the `routes/*` deep pass v0.9.15 missed `webhooks.py`; the 4 module-boundary `__init__.py` files + `__main__.py` startup logic + `health.py` summary helper had no senior-advisor pass; `ag-grid-setup.ts` is the side-effect registration shared by 6 grid components that was never audited for registration-ordering hazards)
**Stamped at:** `44ea862` (origin/main HEAD at audit time — after the v0.9.24 README + CHANGELOG pass landed: 3 plans 074/075/076 written + indexed)
**Recon scope:** `apps/api/src/gw2analytics_api/routes/webhooks.py` + `apps/api/src/gw2analytics_api/__init__.py` + `apps/api/src/gw2analytics_api/__main__.py` + `apps/api/src/gw2analytics_api/routes/__init__.py` + `apps/api/src/gw2analytics_api/scripts/__init__.py` + `apps/api/src/gw2analytics_api/health.py` + `web/src/components/ag-grid-setup.ts`
**Audit mode:** standard effort; targeted deep pass on the untrodden module-inits + the missing routes file (webhooks was missed in v0.9.15) + the side-effect registration; 3 findings selected for planning (1 MED reliability + 1 MED DX/correctness + 1 LOW-MED DX)

### v0.9.25 status table

| # | Plan | Status | Addresses finding | Effort |
|---|---|---|---|---|
| 077 | [077-v0925-api-init-version-importlib-metadata](./077-v0925-api-init-version-importlib-metadata.md) | **pending** (1-line edit in `apps/api/src/gw2analytics_api/__init__.py`: `__version__ = "0.8.6"` → `__version__ = _pkg_version("gw2analytics_api")` with `try/except PackageNotFoundError → "0.0.0+unknown"`. The `_pkg_version` symbol is `from importlib.metadata import version as _pkg_version`. Matches the canonical pattern from plan 042 (`main.py` OpenAPI version) + plan 054 (3 library `__init__.py` files). 5 NEW hermetic tests in NEW `apps/api/tests/test_init_version.py` cover the 5 surfaces: non-empty str, NOT equal `"0.8.6"`, PEP 440 parsable, `__all__` unchanged, fallback works) | #1 `apps/api/src/gw2analytics_api/__init__.py::__version__ = "0.8.6"` is hardcoded — drift vs the actual installed package (currently `0.9.2` per `pyproject.toml`); plans 042 + 054 introduced `importlib.metadata` for `main.py` + the 3 libraries but DIDN'T apply to the `apps/api` package (correctness + DX, LOW-MED) | S |
| 078 | [078-v0925-ag-grid-setup-layout-tsx-boot-import](./078-v0925-ag-grid-setup-layout-tsx-boot-import.md) | **pending** (1-line addition to `web/src/app/layout.tsx`: `import "@/components/ag-grid-setup"` placed after the CSS imports and before the component imports. The 6 existing per-grid-component imports stay (idempotent — `ModuleRegistry.registerModules` deduplicates by module identity, so multiple `registerModules([AllCommunityModule])` calls are safe). 1 NEW hermetic test case in `web/tests/app/layout.test.tsx` is AST-based: parses `web/src/app/layout.tsx` as a TS module and asserts an `ImportDeclaration` whose source contains `@/components/ag-grid-setup`) | #2 `web/src/components/ag-grid-setup.ts` (side-effect: registers `AllCommunityModule` from `ag-grid-community`) is imported by 6 grid consumers individually (`FightsGrid` + `PlayersGrid` + `SquadRollupsGrid` + `TargetRollupsGrid` + `EventWindowsTable` + `SkillUsageTable`); a future maintainer adding a 7th grid CAN forget the import and silently ship a grid with no built-in features (sort + filter + pagination). Importing from `app/layout.tsx` (the Next.js 16 App Router root layout that runs at server boot for every page) guarantees registration before any grid renders; the per-consumer imports remain as belt-and-braces idempotent redundancy. The future cleanup + removal of the 6 consumer-side imports is a follow-up plan once v0.9.x proves the layout.tsx-import alone is sufficient (reliability, MED) | S |
| 079 | [079-v0925-webhooks-routes-commit-failure-handling](./079-v0925-webhooks-routes-commit-failure-handling.md) | **pending** (3 surgical edits in `apps/api/src/gw2analytics_api/routes/webhooks.py`: each of the 3 routes (`create_webhook` + `revoke_webhook` + `replay_dlq_delivery`) wraps its bare `db.commit()` with `try/except SQLAlchemyError` + `logger.exception(...)` + `db.rollback()` + `raise HTTPException(503, {"code": "database_unavailable", "message": <canonical>, <route-specific discriminator>})`. The responses carry per-route discriminators (`subscription_id` for #1 + #2, `delivery_id`+`subscription_id` for #3) so the operator can replay deterministically. 3 NEW hermetic tests in NEW `apps/api/tests/test_webhooks_routes_e2e.py` monkeypatch `db.commit()` to raise `OperationalError` and assert the 503 response + the discriminator + the post-rollback DB state via `db.get(OrmWebhookSubscription/OrmWebhookDlq, ...)` after the rollback) | #3 `routes/webhooks.py` has 3 bare `db.commit()` calls (`create_webhook` + `revoke_webhook` + `replay_dlq_delivery`) — the same "commit-time silent failure" pattern flagged + fixed in plan 045 (`services.py::process_parse`) + plan 034 (`backfill.py::run_backfill`), but the route layer was missed in those sweeps because both prior fixes focused on a single file. A transient commit failure (Postgres connection drop, serialisation failure, pool timeout) → FastAPI returns a 500 with no logged context → operator believes the webhook was created/revoked/replayed but it wasn't. `503 Service Unavailable` (RFC 9110 §15.6.4) is the canonical HTTP code for transient unavailability; per-route discriminators make the operator's recovery deterministic (reliability, MED) | S |

### Recommended execution order (v0.9.25)

1. **Plan 078** (ag-grid-setup boot import) — S effort, the smallest single-line change. 1 file edit + 1 NEW test case. Independent of 077/079.
2. **Plan 077** (`__init__.py::__version__`) — S effort, the public-API drift fix. 1 file edit + 1 NEW test file. Independent of 078/079.
3. **Plan 079** (commit-failure handling) — S effort, the reliability fix. 1 file edit + 1 NEW test file. Independent of 077/078.

All 3 are independent. Could ship in any order. The recommended order is by lowest-risk first (1-line `layout.tsx` addition is the smallest diff), then DX (1-line `__init__.py` swap), then reliability (3 surgical edits in a hot path).

### Dependency graph (v0.9.25)

```
  plan 077 ──┐                              (apps/api/src/gw2analytics_api/__init__.py + apps/api/tests/test_init_version.py)
  plan 078 ──┼── INDEPENDENT ──────────     (web/src/app/layout.tsx + web/tests/app/layout.test.tsx)
  plan 079 ──┘                              (apps/api/src/gw2analytics_api/routes/webhooks.py + apps/api/tests/test_webhooks_routes_e2e.py)
```

No shared file paths across the 3 plans. Could be PR'd in parallel by 3 different engineers.

### Considered and rejected (v0.9.25)

- **Plan 077 alternative: bump the hard-coded `"0.8.6"` to the current value `"0.9.2"`** — drift returns on every release; requires a maintainer to update 2 files (`__init__.py` + `pyproject.toml`) in lockstep every release.
- **Plan 077 alternative: delete the `__version__` re-export** — breaks the public API; `python -c "import gw2analytics_api; print(gw2analytics_api.__version__)"` is a documented op-tool pattern in `CONTRIBUTING.md`.
- **Plan 077 alternative: derive from `pyproject.toml` via `tomllib`** — `importlib.metadata` is the canonical PEP 621 path; `tomllib` is for pyproject introspection only.
- **Plan 078 alternative: explicit `registerGrids()` per consumer** (Option B in the thinker validation) — 6 call sites + future grids need to remember the call = the same drift risk, just renamed.
- **Plan 078 alternative: keep status quo** (Option C) — the future-maintainer-can-forget risk is unaddressed; the plan ships the layout.tsx-import version (Option A).
- **Plan 078 alternative: DELETE the 6 consumer-side imports + keep only the layout.tsx import** — cleaner (1 import vs 7) but bigger diff (6 files changed vs 1). The belt-and-braces design is forward-compat: the future cleanup can happen as a follow-up plan once v0.9.x proves the layout.tsx-import alone is sufficient in production.
- **Plan 078 alternative: use Next.js 16's `instrumentation.ts`** (the server-startup hook) — `instrumentation.ts` runs only on the server; `ModuleRegistry.registerModules` must run on the client where AG Grid hydrates the grid component (the server-side registration has no effect on the client).
- **Plan 079 alternative: extract a `_commit_with_rollback_and_log(...)` helper for the 3 commit sites** — DRY win (3 sites share the same 5-line try/except boilerplate). The rollback semantics + the response shape differ per route (commit #1 builds a `WebhookSubscriptionCreatedOut`; commits #2 + #3 return None / a different response). The plan inlines the pattern with a docstring pointer to plans 045 + 034 + 079 as the canonical places to consult.
- **Plan 079 alternative: return 500 (the FastAPI default) instead of 503** — `503 Service Unavailable` is the canonical HTTP code for "the server is temporarily unable to handle the request" (RFC 9110 §15.6.4); `500 Internal Server Error` is for "the server encountered an unexpected condition" (RFC 9110 §15.6.1).
- **Plan 079 alternative: catch `SQLAlchemyError` in a FastAPI exception handler** (`app.add_exception_handler(SQLAlchemyError, ...)` per the plan 042 hardening posture) — the handler would need per-route context (the `subscription_id` for #1, the `delivery_id`+`subscription_id` for #3) to build the response detail; the context is only available inside the route function. The plan inlines the try/except per site.
- **Plan 079 alternative: re-raise `SQLAlchemyError` and rely on FastAPI's default 500** — restates the status quo; the user-visible 500 has no context for the operator to diagnose.

## v0.9.26 audit (closed)

**Author:** senior-advisor audit (improve skill, standard effort) — `apps/api/tests/*` + `apps/api/README.md` deep pass (the test-file layer never audited in depth: plans 043 + 044 covered the `conftest.py` + `_fixtures.py` + setup.ts + mock-server.mjs infra surface, but the 10 `test_*.py` files + the per-package README had no senior-advisor pass; v0.9.25 closed the missing `webhooks.py` + module-inits route + ag-grid-setup.ts surface) — the per-tests-file layer drifted from the conftest-refactor consolidation work done in plan 005 (v0.9.2 plan 009 Step 5) without a corresponding audit pass)
**Stamped at:** `44ea862` (origin/main HEAD at audit time — after the v0.9.25 routes/webhooks + module-inits + ag-grid-setup.ts pass landed: 3 plans 077/078/079 written + indexed)
**Recon scope:** `apps/api/tests/test_uploads_e2e.py` + `apps/api/tests/test_webhooks_e2e.py` + `apps/api/tests/test_webhooks_e2e_scheduler.py` + `apps/api/tests/test_healthz.py` + `apps/api/tests/test_health_summary.py` + `apps/api/tests/test_account.py` + `apps/api/tests/test_players.py` + `apps/api/tests/test_config.py` + `apps/api/tests/test_backfill.py` + `apps/api/tests/test_ci_health_gate.py` + `apps/api/README.md`
**Audit mode:** standard effort; targeted deep pass on the per-tests-file layer (test fixtures + test patterns + test cleanup) + the per-package README drift; 3 findings selected for planning (1 LOW DX + 1 LOW DX/cleanup + 1 LOW DX/cleanup)

### v0.9.26 status table

| # | Plan | Status | Addresses finding | Effort |
|---|---|---|---|---|
| 080 | [080-v0926-apps-api-readme-drift-fixup](./080-v0926-apps-api-readme-drift-fixup.md) | **pending** (1 file edit on `apps/api/README.md`: rewrite the "Layout" section to enumerate the actual 8 alembic migrations (`0001` through `0008_payload_bytes.py` per the file system truth) + the actual 10 test files (covering the 6 added since the README's v0.7.0 layout: `test_health_summary.py` + `test_backfill.py` + `test_ci_health_gate.py` + `test_webhooks_e2e.py` + `test_webhooks_e2e_scheduler.py` + `test_players.py` + `conftest.py`) + the actual 6 route modules (`uploads` + `fights` + `account` + `health` + `players` + `webhooks`). PLUS the Endpoints table at the top of the README is patched to add the 8 undocumented endpoints (`/api/v1/health/summary` + `/api/v1/players` + `/api/v1/players/{name}` + `/api/v1/players/{name}/timeline` + `POST/GET/DELETE /api/v1/webhooks` + `POST /api/v1/webhooks/dlq/{id}/replay`). 4 NEW hermetic tests in NEW `apps/api/tests/test_readme_drift.py` assert the 4 surfaces: 8 migrations listed + 10 test files listed + 6 route modules listed + 14 Endpoints table rows) | #1 `apps/api/README.md` "Layout" section is significantly STALE: written at v0.7.0, lists 3 alembic migrations but reality is 8 (0001-0008), lists 4 test files but reality is 10+ (the 7 added in v0.8.4-v0.9.1 cycles: `test_health_summary.py` + `test_backfill.py` + `test_ci_health_gate.py` + `test_webhooks_e2e.py` + `test_webhooks_e2e_scheduler.py` + `test_players.py` + `conftest.py`), lists 3 routes modules but reality is 6 (`health` + `players` + `webhooks` added in v0.8.6 + v0.9.0 + v0.8.0). The Endpoints table is missing the 8 routes that shipped in v0.8.x + v0.9.x. A new contributor trusts the README tree over the filesystem — drift here is wrong-finger-print budget (DX, LOW) | S |
| 081 | [081-v0926-test-fixtures-dry-consolidation](./081-v0926-test-fixtures-dry-consolidation.md) | **pending** (2 file edits: `apps/api/tests/test_uploads_e2e.py` drops its 2 local helpers (`_make_cbtevent` + `_make_minimal_zevtc`) + the 18 lines of struct format constants + adds 1 import line `from _fixtures import make_cbtevent, make_minimal_zevtc`. `apps/api/tests/test_players.py` drops its 2 local helpers (the `Local copy of :func:`test_uploads_e2e._make_cbtevent` to keep this test file self-contained` docstring-rationalized duplicates) + adds the same 1 import line. `apps/api/tests/_fixtures.py` GAINS the 2 missing low-level helpers (`make_minimal_zevtc` — a pure pack function with no side effects, complementing the existing high-level `post_minimal_fight`) + the 18 lines of struct format constants (now the canonical wire-format source). The `make_cbtevent` helper that already exists in `_fixtures.py` stays as-is — it was already exported to `test_backfill.py` + `test_health_summary.py`. 6 NEW hermetic tests in NEW `apps/api/tests/test_fixtures.py` cover the 6 surfaces: empty-agents round-trips + valid-zip-header + 64-byte record invariant + dual-emit record round-trip + uniqueness-uuid-non-determinism + AST-cross-reference) | #2 `apps/api/tests/test_players.py` byte-for-byte duplicates `_make_cbtevent` + `_make_minimal_zevtc` from `test_uploads_e2e.py` (the docstring explicitly admits: "Local copy" + "avoid an import dependency on the e2e module's private helpers"). A wire-format change (e.g., adding a field to the 64-byte cbtevent record per a future arcdps spec bump) requires updating 3 sites, not 1: `test_uploads_e2e.py::make_cbtevent` + `test_uploads_e2e.py::make_minimal_zevtc` + `test_players.py::make_cbtevent` + `test_players.py::make_minimal_zevtc`. The new `_fixtures.py` already exports `make_cbtevent` (the canonical name, no underscore prefix) for the v0.8.4 fail-test consumers (`test_backfill.py` + `test_health_summary.py`); the 2 helpers in `test_uploads_e2e.py` + `test_players.py` are exactly the wrong-name shadow re-definitions to consolidate into the existing canonical module (drift, LOW DX/cleanup) | S |
| 082 | [082-v0926-test-webhooks-stub-skip-removal](./082-v0926-test-webhooks-stub-skip-removal.md) | **pending** (2 file edits: (a) `apps/api/tests/test_webhooks_e2e.py` deletes the `test_retry_scheduler_failure_promotes_to_dlq_after_max_attempts` function (a 27-line function whose body is `pytest.skip("moved to test_webhooks_e2e_scheduler.py::...")`), replaces it with a 4-line historical comment referencing the relocation; (b) `apps/api/tests/test_webhooks_e2e_scheduler.py` flips the docstring's cross-reference from "stub-by-name pointer to this module" to "historical note on the relocation (post-plan-082 the stub has been removed; the canonical implementation lives here, exclusively)". Net code change is strongly negative (~22 lines deleted + 5 added). No NEW test files (the canonical test in `test_webhooks_e2e_scheduler.py` already exists) | #3 `apps/api/tests/test_webhooks_e2e.py::test_retry_scheduler_failure_promotes_to_dlq_after_max_attempts` is a `pytest.skip()` placeholder stub (a plan 007 commit-time convention to preserve the test name when the canonical implementation was relocated to `test_webhooks_e2e_scheduler.py`). The stub pollutes (a) `pytest --collect-only` output (a "skipped" test looks like an active test + confuses a future maintainer browsing the test inventory), (b) `pytest --collect-only --strict-markers` strictness checks (the function-body `pytest.skip()` is treated as a test marker), (c) `pytest -k test_retry_scheduler_failure_promotes_to_dlq_after_max_attempts` invocations (the SKIP response misleads a future maintainer who expects an ACTIVE test in `test_webhooks_e2e.py`); the canonical implementation lives in `test_webhooks_e2e_scheduler.py`. The right semantics for a TEST THAT HAS BEEN MOVED is "no test here" (a documentary comment), NOT a `pytest.skip()` stub (DX + cleanup, LOW) | S |

### Recommended execution order (v0.9.26)

1. **Plan 081** (test fixtures DRY) — S effort, the highest leverage per LOC deleted (the largest single diff: net ~100 lines deleted). 2 file edits + 1 NEW test file. Independent of 080/082.
2. **Plan 082** (stub skip removal) — S effort, the second largest diff in lines deleted (~22 lines deleted in `test_webhooks_e2e.py`). 2 file edits + 0 NEW test file. Independent of 080/081.
3. **Plan 080** (README drift fixup) — S effort, the DX win for new contributors. 1 file edit + 1 NEW test file. Independent of 081/082.

All 3 are independent. Could ship in any order. The recommended order is by leverage-first (delete-then-doc, since the deletions net the most code removed for the lowest risk).

### Dependency graph (v0.9.26)

```
  plan 080 ──┐                                  (apps/api/README.md + apps/api/tests/test_readme_drift.py)
  plan 081 ──┼── INDEPENDENT ──────────────       (apps/api/tests/_fixtures.py + test_uploads_e2e.py + test_players.py + apps/api/tests/test_fixtures.py)
  plan 082 ──┘                                  (apps/api/tests/test_webhooks_e2e.py + test_webhooks_e2e_scheduler.py)
```

No shared file paths across the 3 plans. Could be PR'd in parallel by 3 different engineers.

### Considered and rejected (v0.9.26)

- **Plan 080 alternative: delete the Layout section entirely** (the canonical source of truth is `find apps/api -type f`) — assumes every operator runs `find` to discover the layout; the README's tree is the canonical "first impression" for new contributors.
- **Plan 080 alternative: auto-generate the Layout section via a `scripts/gen_readme_layout.py`** — over-engineered for a 1-time drift fixup; a future maintainer who adds a new file can update the README in the same PR.
- **Plan 080 alternative: annotate the tree with audit-pass provenance** (the plan numbers for each file) — adds noise; the README is the canonical source of "what files exist", not "what audit cycle added them".
- **Plan 081 alternative: keep the duplicated copies + add a docstring cross-reference** (status quo + a TODO) — the cross-reference doesn't change the maintenance burden (3 sites to update on a wire-format change).
- **Plan 081 alternative: move ONLY `make_cbtevent` (the 64-byte struct pack) to `_fixtures.py` + keep `make_minimal_zevtc` per-file** — the per-file `make_minimal_zevtc` instances still duplicate the 18 lines of agent/skill/event-appending logic. The plan moves BOTH helpers atomically.
- **Plan 081 alternative: rename `_fixtures.py::make_cbtevent` to `_fixtures.py::_make_cbtevent` (underscore-prefix for "private")** — the existing `_fixtures.py::make_cbtevent` is exported without an underscore (used by `test_backfill.py` + `test_health_summary.py` + future tests); the new plan matches the existing naming convention.
- **Plan 081 alternative: extract the wire-format struct constants to a new `_evtc_layout.py` module** — over-engineered for 10-line constants; the existing `_fixtures.py` is the canonical "test helpers" module + the constants logically live with the functions they parameterize.
- **Plan 082 alternative: keep the stub + add a `pytest.skip(..., allow_module_level=True)` annotation** — the module-level allow is for SKIP-at-module-load (a missing optional dep); the function-body skip is the right pattern for a test that conditionally cannot run, but the new finding is that the skip pattern is the wrong choice for a TEST THAT HAS BEEN MOVED to a different module — the canonical pattern is to MOVE the test, not leave a stub.
- **Plan 082 alternative: keep the stub + rename it to `test_retry_scheduler_failure_promotes_to_dlq_after_max_attempts_RELOCATED`** — the renaming convention pollutes the pytest inventory (the symbol is no longer the original name); a future `pytest -k` user gets two candidates.
- **Plan 082 alternative: delete the stub + add a `conftest.py` assertion that the canonical location is reachable** — a future maintainer who moves the canonical test (for the same dedent footgun reason) gets an automatic fail signal from pytest collection. The canonical implementation is in a sibling module — no import-time guarantee of its existence is needed (pytest's import-failure semantics handle missing module names automatically).
- **Plan 082 alternative: keep the stub but change the body to `pytest.fail("relocated; see test_webhooks_e2e_scheduler.py")`** — flips the SKIP to a FAIL. Both are undesirable: the test was moved, not removed, so the right semantics is "the canonical location is `test_webhooks_e2e_scheduler.py`" — a comment, NOT a pytest skip / fail.

## v0.9.27 audit (closed)

**Author:** senior-advisor audit (improve skill, standard effort) — libs/gw2_analytics sibling-aggregators deep pass (the 9 sibling modules under the orchestrator aggregate.py had only limited coverage: v0.9.6 touched event_window.py only as part of a broader libs+web deep-pass; v0.9.17 covered aggregate.py orchestrator + the 3 __init__.py public surfaces but did NOT separately audit the 8 per-target/per-squad/per-skill/per-timeline siblings; the Phase 8 BuffRemovalEvent addition to gw2_core did not cascade to event_window.py per-bucket accumulator, and the 3 per-target siblings are byte-for-byte near-clones that drift independently)
**Stamped at:** 44ea862 (origin/main HEAD at audit time — after the v0.9.26 apps/api/tests/* + apps/api/README.md pass landed: 3 plans 080/081/082 written + indexed)
**Recon scope:** libs/gw2_analytics/src/gw2_analytics/multi_fight.py + target_dps.py + event_window.py + target_healing.py + target_buff_removal.py + squad_rollup.py (skill_usage.py + player_profile.py + per_fight_timeline.py covered by v0.9.6 deep-pass scope; not re-audited here)
**Audit mode:** standard effort; targeted deep pass on the 6 sibling modules; 3 findings selected for planning (1 MED correctness + 1 MED DX/perf + 1 LOW DX/cleanup)

### v0.9.27 status table

| # | Plan | Status | Addresses finding | Effort |
|---|---|---|---|---|
| 083 | [083-v0927-event-window-phase8-buff-removal-gap](./083-v0927-event-window-phase8-buff-removal-gap.md) | **pending** (3 surgical edits in libs/gw2_analytics/src/gw2_analytics/event_window.py: (a) EventBucket gains new buff_removal_total: int = Field(default=0, ge=0); (b) the aggregate() for-loop gains an `elif isinstance(e, BuffRemovalEvent): buff_removal_by_bucket[bucket_index] += e.buff_removal` branch + a buff_removal_by_bucket accumulator; (c) _check_invariants gains a total_strip sum check. default=0 keeps pre-Phase-8 fixtures compatible. 6 NEW hermetic tests appended to libs/gw2_analytics/tests/test_event_window.py cover: empty-input short-circuit + Damage-only path + BuffRemoval-only path + mixed-kinds same-bucket + multi-bucket strip accumulation + Pydantic field default+annotation introspection) | #1 libs/gw2_analytics/src/gw2_analytics/event_window.py was NOT updated when Phase 8 added BuffRemovalEvent to libs/gw2_core (v0.8.0). target_buff_removal.py was added in the same commit, but EventWindowAggregator's per-bucket accumulator only handles DamageEvent + HealingEvent. Result: the per-fight timeline chart (apps/web/src/app/fights/[id]/page.tsx PerFightTimelineChart) has no per-bucket buff-strip band — a researcher investigating "which 5s window saw the most corrupting concentration" has no timeline answer, only the per-target rollup which is blind to per-bucket chronology (correctness, MED) | S |
| 084 | [084-v0927-per-target-aggregators-template-duplication](./084-v0927-per-target-aggregators-template-duplication.md) | **pending** (1 NEW libs/gw2_analytics/src/gw2_analytics/_per_target_base.py: PerTargetRollupBase(Generic[TEvent, TRow]) abstract class implementing aggregate() + _check_invariants() once + a frozen PerTargetFields dataclass-config (event_attr_name + total_attr_name + count_attr_name + rate_attr_name + default_rate). 3 file edits: target_dps.py + target_healing.py + target_buff_removal.py each retain their PUBLIC TargetXxxRow Pydantic model (no API change) + shrink their TargetXxxAggregator body from ~120 lines to ~30 lines. Net diff: ~210 lines deleted across the 3 files + ~150 lines added in the new base = ~60 lines net removed. 8 NEW hermetic tests in NEW libs/gw2_analytics/tests/test_per_target_rollup_base.py cover: empty-list invariants + single-row happy path + multi-row ordering (descending + tie-break) + the 3 subclasses unchanged post-refactor regression tests) | #2 target_dps.py + target_healing.py + target_buff_removal.py are byte-for-byte near-clones that differ ONLY in 5 strings (event attr.name + row field names + rate sentinel). The duplicated parts (~350 lines across 3 files): duration guard + defaultdict accumulators + per-event accumulation + _check_invariants sum-check + pairwise ordering. A future wire-format change requires editing 3 sites in lockstep — drift risk (DX + perf, MED) | S |
| 085 | [085-v0927-squad-rollup-dual-stream-loop-extraction](./085-v0927-squad-rollup-dual-stream-loop-extraction.md) | **pending** (1 file edit in libs/gw2_analytics/src/gw2_analytics/squad_rollup.py: the 3 byte-identical for-loops (one per damage_events + healing_events + strip_events) collapse into 3 calls to a NEW private helper _accumulate_subgroup_totals(events, source_attr_name, contribution_attr_name, totals_dict, hits_dict) -> int that returns the per-stream grand total. 4 NEW hermetic tests in NEW libs/gw2_analytics/tests/test_squad_rollup_refactor.py cover: empty-input short-circuit + single-event happy path + map-driven subgroup rotation + 10-random-event identical-output regression) | #3 squad_rollup.py::SquadRollupAggregator.aggregate() has 3 byte-for-byte near-clone for-loops (for dmg in damage_events: + for heal in healing_events: + for strip in strip_events:). Each loop shares 5 of 6 lines verbatim — only the per-event contribution attribute differs (.damage vs .healing vs .buff_removal). The grand-total accumulators are also near-clones. A Phase 9 +4th event-type addition requires a 4th loop following the same template; a maintainer who forgets hit_count[subgroup] += 1 would silently under-count (DX/cleanup, LOW) | S |

### Recommended execution order (v0.9.27)

1. **Plan 083** (event_window Phase 8 cascade) — S effort, the ONLY correctness finding. 1 file edit + 6 new tests. Independent of 084/085.
2. **Plan 084** (per-target template DRY) — S effort, the largest LOC reduction (~210 lines net). 1 NEW module + 3 file edits + 1 NEW test file. Independent of 083/085.
3. **Plan 085** (squad_rollup 3-stream DRY) — S effort, the smallest finding. 1 file edit + 4 new tests. Independent of 083/084.

All 3 are independent. Could ship in any order. The recommended order is by severity (MED correctness first), then by leverage (DX/perf template), then LOW DX/cleanup.

### Dependency graph (v0.9.27)

```
  plan 083 ──┐                              (event_window.py + test_event_window.py)
  plan 084 ──┼── INDEPENDENT ──────────     (_per_target_base.py NEW + target_dps.py + target_healing.py + target_buff_removal.py + test_per_target_rollup_base.py)
  plan 085 ──┘                              (squad_rollup.py + test_squad_rollup_refactor.py)
```

All 3 plans touch DIFFERENT sibling modules. Plan 084 is a single multi-file PR (one feature, multiple files = canonical multi-file refactor). Plans 083 + 085 can be PR'd in parallel to plan 084.

### Considered and rejected (v0.9.27)

- **Plan 083 alternative: keep EventBucket unchanged + add EventBucketWithStrip schema** — schemas proliferate; additive-field approach is cleaner.
- **Plan 083 alternative: track buff-removal as separate stream + new aggregate_with_strip method** — 2 methods on same class is more surface to maintain.
- **Plan 083 alternative: use Pydantic v2 discriminated unions with explicit type tags** — gw2_core uses isinstance discrimination (existing pattern); plan matches it.
- **Plan 084 alternative: module-level function with 8+ keyword args** — dataclass-config + abstract class is more type-safe + self-documenting.
- **Plan 084 alternative: use Generic[TTotal, TRate] on 3 row types to consolidate schemas** — schemas are PUBLIC API (wire contract); changing row names breaks the wire. Plan keeps PUBLIC row types unchanged.
- **Plan 084 alternative: keep 3 files as-is + add ruff custom rule for byte-identical duplication** — ruff doesn't have such a rule; explicit refactor is canonical fix.
- **Plan 085 alternative: extract generator yielding (subgroup, contribution) tuples** — caller still writes 4-line accumulation; helper-function-returning-int is more direct.
- **Plan 085 alternative: use pyspark or pandas for the join** — out of scope (library is pure-Python aggregates; no pandas dep).
- **Plan 085 alternative: keep 3 loops + add ruff custom rule for for-loops with same body** — rule is hard to write; explicit extraction is canonical.
- **Plan 085 alternative: keep 3 loops but DRY only the per-subgroup assignment line** — extracting only the rotation doesn't capture the full duplication (grand-total accumulation line is also identical).

## v0.9.28 audit (closed)

**Author:** senior-advisor audit (improve skill, standard effort) — Phase 8 cascade-gaps deep pass (a follow-up to v0.9.27 plan 083's finding that ``event_window.py`` was NOT updated when Phase 8 added ``BuffRemovalEvent`` to ``gw2_core``: this pass audits the 2nd-order impact of the same Phase 8 commit on (a) the test-side cascade for ``event_window.py`` (the tests are frozen at Phase 7 despite the source gaining Phase 8 handling), (b) an unrelated streaming-friendly refactor in ``per_fight_timeline._check_invariants``, and (c) a low-leverage docstring cleanup in ``services.py``)
**Stamped at:** 44ea862 (origin/main HEAD at audit time — after the v0.9.27 libs/gw2_analytics sibling-aggregators pass landed: 3 plans 083/084/085 written + indexed)
**Recon scope:** ``libs/gw2_analytics/src/gw2_analytics/per_fight_timeline.py`` + ``libs/gw2_analytics/tests/test_event_window.py`` + ``apps/api/src/gw2analytics_api/services.py`` (``libs/gw2_analytics/tests/test_target_dps.py`` + ``test_target_healing.py`` + ``test_target_buff_removal.py`` + ``test_per_fight_timeline.py`` already validated for Phase 8 — no findings there)
**Audit mode:** standard effort; targeted deep pass on Phase 8 cascade gaps + 2 unrelated DX findings; 3 findings selected for planning (1 MED test reliability + 1 LOW perf + 1 LOW DX/docs hygiene)

### v0.9.28 status table

| # | Plan | Status | Addresses finding | Effort |
|---|---|---|---|---|
| 086 | [086-v0928-event-window-test-phase8-cascade](./086-v0928-event-window-test-phase8-cascade.md) | **pending** (1 file edit on ``libs/gw2_analytics/tests/test_event_window.py``: add 1 factory ``_strip(time_ms, buff_removal) -> BuffRemovalEvent`` + 6 NEW test methods to the existing ``TestEventWindowAggregator`` class — BuffRemoval-only path + DPS-only with default-zero + mixed-kinds same-bucket + multi-bucket strip accumulation + dual-emit precision + Pydantic field introspection. The 7 existing Phase 6+v1 tests are unchanged) | #1 ``libs/gw2_analytics/tests/test_event_window.py`` is frozen at Phase 7 — it tests only ``DamageEvent`` + ``HealingEvent`` (no ``BuffRemovalEvent``, no ``buff_removal_total`` assertion). After plan 083 adds the Phase 8 source-code path (``elif isinstance(e, BuffRemovalEvent):`` branch + a new ``buff_removal_total`` field on ``EventBucket``), the tests pass verbatim (the ``default=0`` keeps pre-Phase-8 fixtures validate-cleanly) but DO NOT exercise the new code path → a future regression (e.g., a ``ruff`` rename of ``e.buff_removal`` to ``e.strip_magnitude`` in the source) would NOT be caught by the test suite, because no test triggers the strip accumulator branch. Same diagnostic class as plan 083 (source side), but on the test side (test reliability, MED) | S |
| 087 | [087-v0928-per-fight-timeline-check-invariants-materialization-fix](./087-v0928-per-fight-timeline-check-invariants-materialization-fix.md) | **pending** (1 file edit on ``libs/gw2_analytics/src/gw2_analytics/per_fight_timeline.py``: refactor ``aggregate()`` + ``_check_invariants`` plumbing. The ``_check_invariants(rows, events)`` parameterised call is replaced by ``_check_invariants(rows, expected_damage, expected_healing, expected_strip)`` — the 3 expected totals are now computed inline in the ``aggregate()`` for-loop (single pass) instead of via a second-pass ``list(events)`` materialisation in ``_check_invariants``. Net code change: ~0 lines (replace 2-line ``events_list = list(events)`` block with 3-int param plumbing). 1 NEW test file ``libs/gw2_analytics/tests/test_per_fight_timeline_invariants_refactor.py`` with 4 hermetic tests: empty-input + damage-only happy path + mixed-kinds same-bucket + invariant-failure fires) | #2 ``libs/gw2_analytics/src/gw2_analytics/per_fight_timeline.py::PerFightTimelineAggregator._check_invariants`` parameterised as ``_check_invariants(rows, events: Iterable[Event])`` materialises the events stream a SECOND time via ``list(events)`` to compute the 3 sum-preservation invariants. For a canonical WvW raid event blob (~100k+ events), the materialisation is a real memory hit: the events were decoded once + walked once for the per-bucket accumulator (``aggregate()`` body), and ``_check_invariants`` drains them again for the invariant check. Plumbing the 3 expected totals as ints makes the canonical caller 1-pass (perf + memory, LOW) | S |
| 088 | [088-v0928-services-docstring-started-at-framing-update](./088-v0928-services-docstring-started-at-framing-update.md) | **pending** (1 file edit on ``apps/api/src/gw2analytics_api/services.py::_save_fight``: the 12-line inline comment on ``started_at = datetime.now(UTC)`` is reorganised into 2 cleaner paragraphs — (a) "current canonical behavior" (the v0.8.1 unconditional override + the pre-v0.8.1 guard bug it closed) + (b) "Future work" block (the v0.9+ plan could parse the EVTC build field ``yyyyMMdd`` as a date anchor). Net code change: ~5 lines shorter) | #3 ``apps/api/src/gw2analytics_api/services.py::_save_fight`` has a 12-line comment block on the canonical ``started_at = datetime.now(UTC)`` override that mixes 3 things: an historical-bug explanation (v0.8.0 → v0.8.1), the current canonical behavior, and an aspirational future ("a future v0.9 could parse the EVTC build field (``yyyymmdd``) to get a date anchor"). The aspirational line is in-inline, not in a clearly-labelled future-work block — a future maintainer reading the comment is misled to think the v0.9 build-field parsing is a current refactor target. The ``libs/gw2_evtc_parser`` ``EvtcHeader.build_version`` already carries the ``yyyyMMdd`` string; a future plan can add an opt-in "use EVTC build for date anchor" flag. The cleaner framing labels the aspirational line as a ``Future work:`` block so a maintainer can scan past it without ambiguity (DX/docs hygiene, LOW) | S |

### Recommended execution order (v0.9.28)

1. **Plan 086** (event_window Phase 8 test cascade) — S effort, the most-impactful reliability finding (closes the source-side plan 083's silent-regression risk). 1 file edit + 0 NEW test files (extend the existing). Independent of 087/088.
2. **Plan 087** (per_fight_timeline materialization) — S effort, the streaming-friendly perf win for large event blobs. 1 file edit + 1 NEW test file. Independent of 086/088.
3. **Plan 088** (services doc cleanup) — S effort, the lowest-leverage finding (docs hygiene only). 1 file edit + 0 tests. Independent of 086/087.

All 3 are independent. Could ship in any order. The recommended order is by severity (MED reliability first), then by leverage (perf for 100k-event fights = O(100k) saved per request), then docs hygiene.

### Dependency graph (v0.9.28)

```
  plan 086 ──┐                              (libs/gw2_analytics/tests/test_event_window.py)
  plan 087 ──┼── INDEPENDENT ──────────     (libs/gw2_analytics/src/gw2_analytics/per_fight_timeline.py + libs/gw2_analytics/tests/test_per_fight_timeline_invariants_refactor.py)
  plan 088 ──┘                              (apps/api/src/gw2analytics_api/services.py)
```

All 3 plans touch DIFFERENT files. Plan 086 + plan 087 both touch ``libs/gw2_analytics`` (test + source) — could be a single PR for the v0.9.27 plan 083 follow-ups (the canonical "Phase 8 cascade gap is a project-wide concern, close it in one go" pattern). Plan 088 is independent.

### Considered and rejected (v0.9.28)

- **Plan 086 alternative: split into a NEW test file ``test_event_window_phase8_cascade.py``** — duplicates the ``_damage`` + ``_healing`` factories; loses the test-matrix visual continuity. The 6 new tests fit naturally into the existing ``TestEventWindowAggregator`` class.
- **Plan 086 alternative: add a single "Phase 8 smoke test"** — 1 test is weaker than 6 discrete tests; the per-bucket accumulator + the multi-bucket invariants + the dual-emit path are SEPARATE concerns that should each have a test.
- **Plan 087 alternative: pass a callback ``expected_sum_fn: Callable[[Iterable[Event]], tuple[int, int, int]]``** — the callable can drain the stream once, but the canonical caller (``aggregate()``) already drains the stream once; passing the 3 ints directly is simpler and saves 1 callable layer.
- **Plan 087 alternative: skip the invariant check entirely** (rely on type-checking) — the sum-preservation invariants are the canonical tests for "did the aggregator drop / double-count any events"; removing them would regress test quality.
- **Plan 087 alternative: use ``functools.reduce`` for the per-bucket accumulator** — the canonical per-bucket accumulator IS a ``defaultdict(int)`` + a per-iteration accumulator; the ``functools.reduce`` approach is less idiomatic.
- **Plan 088 alternative: remove the comment entirely** — the historical context (the pre-v0.8.1 guard bug) is genuinely useful for a maintainer who needs to understand why the unconditional override is canonical. Removing the comment loses that context.
- **Plan 088 alternative: extract the aspirational line to a separate ``TODO`` docstring on ``_save_fight``** — ``TODO`` markers read as "incomplete"; the ``Future work:`` block reads as "intentionally future-planned".
- **Plan 088 alternative: move the aspirational line to a ``## Future work`` section in ``docs/ROADMAP.md``** — ROCMAP is the canonical home for aspirational items; moving the line out of the inline comment fully unlocks the inline comment for "current behavior" only.

## v0.9.37 audit (closed)

**Author:** senior-advisor read-only audit pass. **Status:** current cycle.

**Scope.** `apps/api/src/gw2analytics_api/workers/{__init__.py, webhook_dispatch.py, webhook_scheduler.py}` + `apps/api/src/gw2analytics_api/health.py` + `apps/api/src/gw2analytics_api/routes/health.py` -- the worker pool + the operational health probe (`/api/v1/health/summary`). The webhook routes were covered by v0.9.15 + the commit failure-handling pattern was tightened in v0.9.25 plan 079; the WORKER surfaces (the SQLAlchemy-session-bound retry + dispatch paths) plus the health probe were un-audited. Today's 5 files are the worker + health observability surface never deeply audited.

| Plan | File(s) touched | Risk | LOC delta |
| --- | --- | --- | --- |
| **113** | NEW `apps/api/src/gw2analytics_api/workers/_delivery_common.py` + 2 modified workers | low-medium -- consolidate duplicate HMAC + canonical headers builder between `webhook_dispatch.py` + `webhook_scheduler.py` (the literal `_USER_AGENT` currently diverges: `"0.9.0"` initial vs `"0.9.1"` retry). Adds a canonical single-source-of-truth. | +60, -30 |
| **114** | `apps/api/src/gw2analytics_api/workers/webhook_scheduler.py` | low -- dead-code: ``_BACKOFF_BY_ATTEMPT[1: 1]`` is unreachable (caller passes `attempt` AFTER ``delivery.attempt += 1`` -- only `attempt ∈ {2, 3}` ever reached). Plus the silent ``.get(attempt, _MAX_ATTEMPTS)`` fallback removed; ``KeyError`` is the right surface on a future addition. | +6, -4 |
| **115** | `apps/api/src/gw2analytics_api/routes/health.py` + `health.py` | low-medium -- add NEW `GET /api/v1/health/db` route (cheap `SELECT 1` liveness probe that distinguishes "DB unreachable" from "drift detected"); DRY the duplicated drift-semantics docstring (currently in 3 places) into the canonical ``SummaryDrift``TypedDict. | +50, -25 |

**Dependency graph.** All three plans touch DISJOINT file regions: 113 affects the 2 worker files + a NEW private shared module; 114 affects `webhook_scheduler.py` only; 115 affects the 2 health files + NEW tests. PRs can land concurrently.

**Cross-cutting thematics**:

- **Single-source-of-truth for worker-side request envelope (Plan 113)**: the canonical HMAC + header builder + the workspace-level ``REQUEST_TIMEOUT_S`` + the canonical ``USER_AGENT`` (the v0.9.x-series release-string) consolidate the divergent literals across the 2 worker files into the ONE set of constants in `_delivery_common.py`.
- **Dead-code elimination + documented post-increment semantics (Plan 114)**: the `_BACKOFF_BY_ATTEMPT[1: 1]` entry was unreachable by virtue of caller discipline (the `_attempt_retry` caller increments BEFORE consulting the backoff). The plan eliminates the dead entry + removes the silent `.get(attempt, _MAX_ATTEMPTS)` fallback so future additions fail loudly with `KeyError`.
- **Health-probe granularity (Plan 115)**: the existing `/api/v1/health/summary` endpoint mixes 3 distinct operational signals (DB reachability + dataset size + drift count). A monitoring system polling for liveness cannot distinguish "DB unreachable" from "0 fights yet" from "drift detected". The new `GET /api/v1/health/db` (cheap `SELECT 1` probe) isolates liveness; the existing `/summary` stays focused on drift. Plus the drift-semantics docstring DRYs across 3 surfaces into the canonical `SummaryDrift` TypedDict.

**Rejected alternatives (15 total across the 3 plans).** Highlights:

- **Plan 113 alternative: inline the canonical builder into BOTH files via a shared `_helpers.py` module** -- convention drift here would re-create the divergence. The single canonical module is the right pattern. REJECTED.
- **Plan 113 alternative: keep the `_USER_AGENT` divergence ("initial=0.9.0, retry=0.9.1") as a forensic signal** -- the integrator's User-Agent parsing is the canonical contract for version-detection; a divergence is a bug-class surface. REJECTED.
- **Plan 114 alternative: keep the `_BACKOFF_BY_ATTEMPT[1: 1]` entry as documentation** -- dead entry is a maintenance hazard (catches no errors, includes dead-code). The TODO comment on the schedule is a better doc surface. REJECTED.
- **Plan 114 alternative: add a runtime warning when `_compute_next_attempt_at` is called with `attempt=0`** -- adds runtime surface for a purely defensive concern (the dead-key elimination test pins the invariant). The test-layer pin is cheaper. REJECTED.
- **Plan 115 alternative: add `latency_ms` to `SummaryDrift` (combining the 2 probes)** -- couples 2 distinct operational signals; a `drift_pct` of `0.0` doesn't mean "DB ok" if there's no Postgres round-trip at all. The split is canonical. REJECTED.
- **Plan 115 alternative: reuse the existing `/healthz` root-level endpoint** -- that's in `main.py` (`@app.get("/healthz", include_in_schema=False)`); the routes group is `/api/v1/health/*` for OpenAPI discovery. REJECTED.

**Test count.** 5 + 5 + 5 = **15 new hermetic tests** across the 3 plans.

**Conventions for the executor.** All 3 plans:
- Touch **only** the listed files; no incidental edits.
- 113 introduces a NEW ``_delivery_common.py`` private shared module adjacent to its 2 workers (the v0.9.x workspace convention: private (``_`` prefix) shared modules for cross-cutting helpers).
- 114 is documentation + dead-code elimination: a 2-line + 4-line tweak; the runtime behaviour is unchanged (the unreachable entry was never called).
- 115 introduces a NEW ``DbHealth`` TypedDict as the schema-of-truth for the liveness probe; the route layer cross-references ``SummaryDrift`` for the drift docstring.

## v0.9.36 audit (closed)

**Author:** senior-advisor read-only audit pass. **Status:** current cycle.

**Scope.** `libs/gw2_analytics/src/gw2_analytics/aggregate.py` (the orchestrator) + `libs/gw2_analytics/tests/test_*.py` (the 10 test files in the ``libs/gw2_analytics/tests`` package, including the orchestrator's test + the 9 sibling aggregator tests). Per v0.9.17 plan 055 + v0.9.27 plans 083-085, the orchestrator + 2 of the 9 sibling aggregators + 3 sibling tests were touched at the surface level. The deeper DRY + invariant-enforcement surfaces (test fixture factories + cross-field pydantic v2 validators) were never audited.

| Plan | File(s) touched | Risk | LOC delta |
| --- | --- | --- | --- |
| **110** | NEW `libs/gw2_analytics/tests/_fixtures.py` + 2 modified test files | low — extract `_player` + `_npc` + `_fight` + `_FIXED_FIGHT_ID` to a shared `_fixtures` module. Local aliases preserve every call site; runtime byte-identical. | +90, -45 |
| **111** | NEW `libs/gw2_analytics/tests/_event_fixtures.py` + 5 modified test files | low-medium — consolidate `_damage` + `_heal` + `_strip` factories with 4 divergent parameter-naming conventions. Canonical-42-44 skill_id default + domain-named parameter style. Future ripple reductions for event-field additions. | +120, -55 |
| **112** | `libs/gw2_analytics/src/gw2_analytics/aggregate.py` | low — migrate `SingleFightAggregator._check_invariants` static method to ``@model_validator(mode="after")`` on the ``FightAggregate`` Pydantic model. Self-validating schema; closes the documented direct-construct defense-in-depth gap. | +30, -18 |

**Dependency graph.** All three plans touch DISJOINT file regions: 110 introduces a NEW `tests/_fixtures.py` + imports in 2 test files; 111 introduces a NEW `tests/_event_fixtures.py` + imports in 5 test files; 112 touches `aggregate.py` only. PRs can land concurrently.

**Cross-cutting thematics**:

- **Test fixture DRY (Plans 110 + 111)**: the synthetic ``_player``+``_npc``+``_fight`` triple was duplicated near-bytely across ``test_aggregate.py`` + ``test_multi_fight.py`` (Plan 110); the synthetic ``_damage``+``_heal``+``_strip`` events were duplicated with 4 divergent parameter-naming conventions (Plan 111) across ``test_target_dps.py`` + ``test_target_healing.py`` + ``test_target_buff_removal.py`` + ``test_squad_rollup.py`` + ``test_per_fight_timeline.py``.
- **Schema self-validation (Plan 112)**: a documented defense-in-depth test (``test_aggregate_rejects_empty_fight_id_via_model_construct``) already proves the schema is under-defended for direct ``model_construct(...)`` / ``model_validate(...)`` paths. The migration to ``@model_validator(mode="after")`` closes that documented gap AT THE SCHEMA level (the canonical pydantic v2 hook), not in the aggregator.

**Rejected alternatives (14 total across the 3 plans).** Highlights:

- **Plan 110 alternative: drop the `_player` / `_npc` / `_fight` aliases and rename every call site** — invasive (12-15 test call sites per file). The aliases preserve the call sites; the import block is the single change. REJECTED.
- **Plan 111 alternative: keep divergent skill_id defaults — "42 / 43 / 44 is arbitrary anyway"** — true, but the divergent values across files (``1/2/3`` in squad_rollup vs ``42/43/44`` in timeline) ARE the maintenance hazard. The canonical-42-44 is a defensible arbitrary that survives the consolidation. REJECTED.
- **Plan 111 alternative: use the `value` parameter-naming convention everywhere** — `value` is the cbtevent-layer name (the raw integer payload); the aggregator surfaces it as `damage` / `healing` / `buff_removal`. The canonical helper picks the DOMAIN convention. REJECTED.
- **Plan 112 alternative: keep the static method AND add a `@model_validator`** — dual enforcement is DRY violation (3 invariants declared twice). REJECTED.
- **Plan 112 alternative: move invariants to `MultiFightAggregator` (per plan 055 architecture)** — wrong location. The invariants are about the OUTPUT ``FightAggregate`` schema, not the cross-fight rollup. REJECTED.

**Test count.** 4 + 6 + 4 = **14 new hermetic tests** across the 3 plans.

**Conventions for the executor.** All 3 plans:
- Touch **only** the listed files; no incidental edits.
- 110 + 111 introduce private (``_`` prefix) helper modules; the test consumer keeps the canonical pattern (no `@pytest.fixture` decorator; module-level pure functions).
- 112 is a metadata-only-validated migration: the schema now self-validates; future direct ``FightAggregate.model_validate(...)`` paths (e.g. a future ORM-to-schema mapper) inherit the invariants automatically. Zero test strictly fails on the migration (the 3 invariants are still enforced; the surface that enforces them changed).

## v0.9.35 audit (closed)

**Author:** senior-advisor read-only audit pass. **Status:** current cycle.

**Scope.** Root-level operability files: `.github/workflows/ci.yml` + `Caddyfile` + `docker-compose.yml` + (cross-cutting) `.gitignore` NEW additions + NEW `docs/self-host.md`. The 3 files in scope are the deployment-CI surface never deeply audited (the codegen-scripts `web/scripts/dump_openapi.py` + `web/scripts/screenshots.mjs` were covered by plan 058 v0.9.18).

| Plan | File(s) touched | Risk | LOC delta |
| --- | --- | --- | --- |
| **107** | `docker-compose.yml` + NEW `docker-compose.override.yml.example` + `.gitignore` | low-medium — env_file mechanism + restart policy + production override split. Resolves the production-misconfig foot-gun (currently `MINIO_ROOT_PASSWORD: gw2analytics-secret` is a literal in source). | +35, -10 |
| **108** | `Caddyfile` + NEW `docs/self-host.md` | low — 5 canonical security headers (HSTS + X-Frame-Options + X-Content-Type-Options + Referrer-Policy + Permissions-Policy) + cross-link with the `next.config.ts::headers()` belt-and-braces layer (per plan 056 v0.9.18). | +45, -2 |
| **109** | `.github/workflows/ci.yml` | low — single-line addition `if: success()` to the post-e2e health-probe gate; fixes the false-negative surface when pytest fails before the e2e suite runs. | +1, -0 |

**Dependency graph.** All three plans touch DISJOINT file regions: 107 affects `docker-compose.yml` + a gitignored NEW override; 108 affects `Caddyfile` + a NEW docs file; 109 affects `.github/workflows/ci.yml` only. PRs can land concurrently.

**Cross-cutting thematics**:

- **Production hardening (Plan 107)**: dev-friendly compose defaults → operator-authored override file pattern (the canonical docker-compose hybrid pattern for self-hosting).
- **Belt-and-braces security headers (Plan 108)**: adds 5 canonical security headers at the Caddy TLS-termination boundary. The `next.config.ts::headers()` layer (per plan 056) added 4 of these on web responses; the Caddy layer adds them on ALL responses (including the FastAPI gateway responses that bypass the Next.js proxy).
- **CI false-negative guard (Plan 109)**: the existing post-e2e health probe gate runs unconditionally; if pytest errors out before the e2e suite runs (a common failure mode for import-time fixture errors), the gate sees baseline-vs-baseline (drift = 0) and reports success. The `if: success()` guard restricts the step to run only when pytest actually executed.

**Rejected alternatives (10 total across the 3 plans).** Highlights:

- **Plan 107 alternative: inline the production values in `docker-compose.yml` via git-ignored env-var substitution** — works but eliminates the merge pattern; operators can't add extra service overrides (e.g. adding the `apps-api` + `web/` services to the prod compose). The two-file split is the canonical pattern. REJECTED.
- **Plan 107 alternative: use Docker Swarm / k8s secrets** — the project doesn't run on Swarm / k8s today; the platform is bare-bones docker compose. The override pattern is the closest analogue. REJECTED.
- **Plan 108 alternative: skip the Caddy-side headers and rely solely on the `next.config.ts::headers()` layer** — works for web responses but not for the FastAPI gateway responses (the analytics bulk-download endpoints, the player profile JSON endpoint). The Caddy layer is the canonical reverse-proxy. REJECTED.
- **Plan 109 alternative: wrap the post-e2e gate in `if: always()` (= failure OR success)** — same as the current pattern; runs even on failure. The fix requires `success()` ONLY. REJECTED.
- **Plan 109 alternative: move the post-e2e health gate to a SEPARATE job** (`if: needs.lint-and-test.result == 'success'`) — adds another job's-worth of CI minutes for the same effect. The `if: success()` step-level guard is the cheaper fix. REJECTED.

**Test count.** 4 + 3 + 3 = **10 new hermetic tests** across the 3 plans (1 Caddy-derived test skipped in CI if `caddy` binary absent).

**Conventions for the executor.** All 3 plans:
- Touch **only** the listed files; no incidental edits.
- 107 introduces a NEW `docker-compose.override.yml.example` template file; the resolved `docker-compose.override.yml` is gitignored (operator-authored, secret-bearing).
- 108 introduces a NEW `docs/self-host.md` operational doc; cross-references with `plan 056 v0.9.18` for the Next.js-side belt-and-braces.
- 109 is the smallest change (1 line); the test (`test_post_e2e_health_gate_step_has_if_success_guard`) pins the guard's presence so a future refactor doesn't drop it.

## v0.9.34 audit (closed)

**Author:** senior-advisor read-only audit pass. **Status:** current cycle.

**Scope.** `apps/api/alembic/env.py` + `apps/api/alembic/versions/{0001..0008}*.py` + `apps/api/src/gw2analytics_api/scripts/{backfill_player_summaries.py, health_gate.py}` — the alembic migration surface + the two CLI scripts (one-shot backfill + CI health gate). Routes (`uploads/fights/players/account/health/webhooks`) covered in v0.9.15/v0.9.25; ORM models + SQLAlchemy infrastructure covered in v0.9.31. The 11 files in this scope are the operability-migration surface never deeply audited.

| Plan | File(s) touched | Risk | LOC delta |
| --- | --- | --- | --- |
| **104** | `apps/api/alembic/versions/0003_fight_skills.py` + `0007_webhook_retry.py` + `0005_fight_player_summaries.py` | low — annotation consistency (untyped `revision = "..."` -> typed `revision: str = "..."`) + docstring typo fix (`0004` -> `0005` in 0005's docstring). Migration identifiers preserved (no alembic-hash churn). | +4, -4 |
| **105** | `apps/api/alembic/env.py` | low — add `compare_type=True` + `compare_server_default=True` kwargs to both `run_migrations_offline::context.configure()` AND `run_migrations_online::context.configure()`. Plan 061 v0.9.19 documented this fix but the env.py change never landed. | +16, -0 |
| **106** | `apps/api/src/gw2analytics_api/scripts/health_gate.py` | low-medium — add `_validate_drift_shape` helper for baseline + live-probe shape validation (currently bare `KeyError` on shape mismatch); add `--max-drift-delta` CLI flag (currently hardcoded module-level `MAX_DRIFT_DELTA = 2` constant). | +35, -4 |

**Dependency graph.** All three plans touch DISJOINT file regions: 104 affects 3 version files (metadata-only); 105 affects `env.py` only; 106 affects `health_gate.py` only. PRs can land concurrently.

**Cross-cutting thematics**:

- **DRY (Plan 104)**: same alembic revision-identifier shape was declared in 2 styles across the 8 migrations (typed annotation in 0001/0002/0004/0005/0006/0008; bare literal in 0003/0007). Standardized.
- **Autogen correctness (Plan 105)**: alembic `context.configure()` is type-blind + server-default-blind by default; the 2 kwargs enable future `--autogenerate` to detect the column-type + server-default changes that the historical 0002 + 0006 migrations did BY HAND.
- **Operator ergonomics (Plan 106)**: hardcoded `MAX_DRIFT_DELTA = 2` constant moves to a CLI flag; baseline-shape validation catches opaque `KeyError` failures at CI time with explicit "re-capture baseline" guidance.

**Rejected alternatives (12 total across the 3 plans).** Highlights:

- **Plan 104 alternative: move the annotations to a shared `_migration_template.py` and import from each** — alembic scripts MUST be standalone modules (no shared imports allowed in the `versions/` directory per alembic's design); each script is the unit of version control. The in-file pattern is mandatory. REJECTED.
- **Plan 105 alternative: set the flags globally in `alembic.ini`** — works but is less discoverable than the in-file kwargs. A future contributor looking at `env.py` would miss the global setting. The kwargs pattern is the alembic-recommended approach. REJECTED.
- **Plan 105 alternative: add `compare_type=True` only (skip `compare_server_default=True`)** — leaves the second drift hazard in place. Both are needed.
- **Plan 106 alternative: use Pydantic v2 `SummaryDrift.model_validate(baseline)` for shape validation** — the `SummaryDrift` TypedDict is a static-only annotation, NOT a runtime validator. The minimal-fix shape check (3 lines) is the right scoped fix. REJECTED.
- **Plan 106 alternative: drop the `MAX_DRIFT_DELTA` constant entirely; require the CLI flag** — breaks the canonical-script invocation. The constant-as-default pattern preserves the canonical invocation while enabling operator tuning.

**Test count.** 4 + 4 + 5 = **13 new hermetic tests** across the 3 plans.

**Conventions for the executor.** All 3 plans:
- Touch **only** the listed files; no incidental edits.
- 104 is metadata-only — alembic hash unchanged, runtime schema unchanged.
- 105 enables future autogen correctness; historical migrations (0002 + 0006) remain valid because they were hand-authored.
- 106 stays hermetic: the script does NOT import `gw2_analytics_api.health`'s Pydantic models (which would couple it to the FastAPI app); the inline `_validate_drift_shape` is the canonical Lite pattern.

## v0.9.33 audit (closed)

**Author:** senior-advisor read-only audit pass. **Status:** current cycle.

**Scope.** `web/src/components/*` (PlayerTimelineLegend, CsvDownloadButton, PlayerSearchBar, FightsGrid, PlayersGrid, SkillUsageTable, SquadRollupsGrid, EventWindowsChart, PerFightTimelineSection) + `web/src/lib/*` (env.ts, csv.ts, api.ts) — the shared React components + the lib utility surface never audited in depth. v0.9.7 covered the 7 page.tsx; v0.9.22 covered layout.tsx + CSS; v0.9.25 peripherally touched ag-grid-setup.ts via plan 078; v0.9.13 covered the test infrastructure (vitest + playwright + setup.ts + mock-server.mjs). The 12 files in this scope are the shared runtime surface consumed by every page.

| Plan | File(s) touched | Risk | LOC delta |
| --- | --- | --- | --- |
| **101** | `web/src/lib/csv.ts` + 4 components | low — interface merge from `SquadRollupColumn` + `CsvColumn` to unified `RollupColumn<TRow>` (with backward-compat `CsvColumn` type alias); no runtime behaviour change | +20, -12 |
| **102** | `web/src/app/globals.css` + 2 components | low — extract `#f59e0b` warm-orange strip colour from `PlayerTimelineLegend.tsx` into the canonical `--strip` CSS token; add the matching third legend swatch in `EventWindowsChart.tsx` (documentation-only, no data change) | +5, -2 |
| **103** | `web/src/lib/env.ts` + `web/.env.example` | low-medium — rename env var to Next.js-canonical `NEXT_PUBLIC_API_BASE_URL` (works BOTH server + client) + add production fail-fast guard for the previously-silent `"http://localhost:8000"` fallback | +25, -8 |

**Dependency graph.** All three plans touch DISJOINT file regions: 101 affects type definitions (lib/csv.ts) + 4 consumers; 102 affects the global CSS colour tokens + 2 inline-styled components; 103 affects the env-resolution module + the .env.example doc. PRs can land concurrently.

**Cross-cutting thematics**:

- **DRY (Plan 101)**: same column-spec concept was duplicated across `lib/csv.ts::CsvColumn` + `components/SquadRollupsGrid.tsx::SquadRollupColumn` (only `width` and AG-Grid-rendering defaults differ). Merged into `RollupColumn<TRow>`.
- **Canonical tokens (Plan 102)**: extracted the hardcoded `#f59e0b` hex literal into the global `--strip` CSS var, following the `plan 070 v0.9.22` DRY utility extraction pattern.
- **Canonical conventions (Plan 103)**: aligns env var resolution with the Next.js convention (`NEXT_PUBLIC_*` prefix for client-bundled vars) + adds a production fail-fast guard for the silent localhost fallback. Closes the gap `plan 033 v0.9.7` documented but never wired.

**Rejected alternatives (11 total across the 3 plans).** Highlights:

- **Plan 101 alternative: keep the two interfaces distinct, add a `csvOf(gridColumn)` adapter** — adds a runtime adapter without removing the duplication. The two surfaces ARE the same concept. REJECTED.
- **Plan 101 alternative: hoist `RollupColumn` to a new `web/src/lib/columns.ts` module** — adds a new file for a 4-field interface; the console pulse is to keep this adjacent to its primary consumer (`lib/csv.ts`). REJECTED.
- **Plan 102 alternative: replace the THREE colours with a single `Palette` object** — overengineering for 3 hex literals; the canonical token system (CSS vars) is the lower-cost fix. REJECTED.
- **Plan 103 alternative: drop the silent `"http://localhost:8000"` fallback entirely (require the env var in dev too)** — breaks local-dev DX (every contributor would need to create a `.env.local` just to run `pnpm dev`). The dev fallback + production fail-fast is the canonical Next.js pattern. REJECTED.
- **Plan 103 alternative: add a runtime warning instead of throwing in production** — silent warnings vs loud throws; the production-misconfig foot-gun deserves the loud fail. Runtime warning would be silently logged in the operator's hosting platform, often ignored. REJECTED.

**Test count.** 5 + 4 + 5 = **14 new hermetic tests** across the 3 plans.

**Conventions for the executor.** All 3 plans:
- Touch **only** the listed files; no incidental edits.
- 101 ends with a backward-compat `CsvColumn<TRow> = RollupColumn<TRow>` type alias so existing imports keep working.
- 102 adds the `--strip` token to the current `:root { ... }` block in `globals.css`; the third `<span>` legend entry in `EventWindowsChart.tsx` is documentation-only (the chart's bars don't render strip data today because `EventBucket.buff_removal_total` doesn't exist yet per plan 083).
- 103 changes the env resolution at module load time — the `lib/api.ts` consumer sees a unified canonical export name `API_BASE_URL`, no import-path changes required.

## v0.9.32 audit (closed)

**Author:** senior-advisor read-only audit pass. **Status:** current cycle.

**Scope.** `libs/gw2_evtc_parser/src/gw2_evtc_parser/{interface.py, __main__.py, exceptions.py, __init__.py}` + `libs/gw2_evtc_parser/pyproject.toml` — the CLI surface + the Parser Protocol surface + the exception tree + the package-level `__version__`. `parser.py` is the corpus per v0.9.21; the 4 files listed were the holdouts.

| Plan | File(s) touched | Risk | LOC delta |
| --- | --- | --- | --- |
| **098** | `libs/gw2_evtc_parser/src/gw2_evtc_parser/__init__.py` + `libs/gw2_evtc_parser/pyproject.toml` | low — `importlib.metadata` pattern (matches the 4 sibling libs via plans 042 / 054 / 077 / 089 / 092); includes a `pyproject.toml` bump `0.1.0` -> `0.5.0` (closing the WORST drift in the 5-library workspace). Note: plan 042 supposedly migrated this lib but did not ship; plan 098 closes the document-but-not-implemented gap. | +7, -1 |
| **099** | `libs/gw2_evtc_parser/src/gw2_evtc_parser/interface.py` | low — pure docstring update adding `BuffRemovalEvent` + the Phase 8 yields-BOTH-events explanation. No signature change; no behaviour change; no import change. | +30, -10 |
| **100** | `libs/gw2_evtc_parser/src/gw2_evtc_parser/__main__.py` | low-medium — `inspect-zip` OOM fix (`zf.read(name)[:16]` -> `zf.open(name).read(16)`); for 50-200 MB EVTC entries the CLI currently decompresses the entire entry into RAM just to display 16 head bytes. | +5, -2 |

**Dependency graph.** All three plans touch DISJOINT file regions: 098 touches `__init__.py` + `pyproject.toml`; 099 touches `interface.py` docstring; 100 touches `__main__.py` line ~92. PRs can land concurrently.

**Plan 042 reconciliation**: The historical commit log claims "v0.9.x plan 042 shipped gw2_evtc_parser migration to importlib.metadata". Reviewing the current `__init__.py` shows the migration NEVER SHIPPED — the literal `"0.5.0"` is still there. Plan 098 closes this gap retroactively. Recommended CHANGELOG entry (not required by this plan): one line noting "v0.9.32 plan 098 closes the v0.9.x plan-042 promised-but-never-shipped migration".

**Rejected alternatives (14 total across the 3 plans).** Highlights:

- **Plan 098 alternative: leave the drift; bump only the `__init__.py` literal to "0.1.0" to match pyproject** — the runtime literal `"0.5.0"` was someone's attempt to reflect the actual code state (Phase 8 events, etc.); reverting it to `0.1.0` reverses the documentation effort. REJECTED.
- **Plan 098 alternative: leave the drift; bump only `pyproject.toml` to "0.5.0" without touching `__init__.py`** — works for the next release but loses the test-layer invariant. REJECTED.
- **Plan 099 alternative: also update the implementation `parse_events` docstring in `parser.py` to match (DRY)** — cross-file dedup is a separate concern, recommended as a v0.9.x follow-up. Out of scope for this audit. REJECTED.
- **Plan 099 alternative: add a separate `parse_buff_strips(self, source) -> Iterator[BuffRemovalEvent]` method to the Protocol** — splits the API surface; legacy callers would have to switch method calls. The Phase 8 discriminated-union design is the cleaner single-method abstraction. REJECTED.
- **Plan 100 alternative: cap the head peek to N bytes via a `MAX_HEAD_BYTES` constant** — `read(16)` already caps; the issue is the underlying `zf.read()` call that pulls the FULL entry. The streaming `zf.open` is the right fix. REJECTED.
- **Plan 100 alternative: skip the head peek entirely; show only entry metadata** — removes a useful debugging affordance (the head peek is for "does this look like a real EVTC?"). The streaming fix keeps the affordance. REJECTED.

**Test count.** 5 + 3 + 4 = **12 new hermetic tests** across the 3 plans.

**Conventions for the executor.** All 3 plans:
- Touch **only** the listed files; no incidental edits.
- 098 matches the `importlib.metadata` import block pattern from the 4 sibling libs.
- 099 is documentation-only; the next person who reads `parse_events` will see the Phase 8 contract documented in the Protocol.
- 100 is a one-line streaming fix; the only behaviour change is that `inspect-zip <large>.zevtc` no longer OOMs.

## v0.9.31 audit (closed)

**Author:** senior-advisor read-only audit pass. **Status:** current cycle.

**Scope.** `apps/api/src/gw2analytics_api/{storage.py, database.py, models.py, schemas.py, main.py, config.py}` — the FastAPI infrastructure (MinIO wrapper + SQLAlchemy engine/sessionmaker + Base + 7 ORM models + Pydantic schemas + FastAPI app + CORS + lifespan + Settings) never audited in depth. Routes (`uploads/fights/players/account/health/webhooks`) were covered via v0.9.15 + v0.9.25 + v0.9.26; the 6 INFRA files listed were the holdouts.

| Plan | File(s) touched | Risk | LOC delta |
| --- | --- | --- | --- |
| **095** | NEW `apps/api/src/gw2analytics_api/_cache_reset.py` + `apps/api/tests/conftest.py` (autouse fixture) | low — pure helper consolidation; production code (config/database/storage) UNCHANGED | +35, -0 |
| **096** | `apps/api/src/gw2analytics_api/storage.py` + `models.py` | low — zero-migration docstring clarification; column name retained for historical alignment with design-doc schema. Alembic rename to `events_blob_key` is a flagged v0.9.x+ follow-up. | +20, -10 |
| **097** | NEW `apps/api/tests/_settings_factory.py` + `apps/api/tests/_fixtures.py` (1-line import) | low — activates the configured-but-unused `populate_by_name=True` flag on `Settings`. No production-source change. | +50, -0 |

**Dependency graph.** All three plans touch DISJOINT file regions: 095 introduces a new `_cache_reset.py` helper (reaches into the 3 production modules but does NOT modify them) + autouse fixture in conftest; 096 touches `storage.py` docstrings + `models.py::OrmFight.events_blob_uri` field-docstring; 097 lives entirely under `apps/api/tests/_settings_factory.py`. PRs can land concurrently.

Plan 095 ↔ Plan 097 COMPOSITION: tests that mutate env vars use `reset_infrastructure_caches()` (plan 095) to clear the cache AFTER the mutation so the next call sees the change; tests that want a self-contained Settings override use `make_settings(**overrides)` (plan 097) to construct an isolated instance. A test that wants BOTH calls `reset_infrastructure_caches()` first, then `make_settings(**overrides)` for the kwarg layer.

**Rejected alternatives (15 total across the 3 plans).** Highlights:

- **Plan 095 alternative: add a `reset_*` helper per module** (`config.reset_settings_cache`, `database.reset_engine`, `storage.reset_minio_client`) and let each test call each in turn — same fragmented problem at a different layer. The single helper consolidates the 4 paths.
- **Plan 095 alternative: use `functools.cache` (thread-safe at init time) instead of manual `_engine = None` resets** — would simplify `database.py` but introduce 2 more `functools.cache`-decorated globals WITH their own `.cache_clear()` paths. Net LOC change is a wash. REJECTED.
- **Plan 096 alternative: alembic-migration rename `events_blob_uri` -> `events_blob_key`** — invasive (one-shot migration script + backward-compat shim + ORM attr rename + every route/service/model reference). The minimal fix is the docstring + parameter rename; the migration is a separate v0.9.x+ pass.
- **Plan 096 alternative: rewrite the column to store full s3://bucket/key URIs** — bigger migration (write path + read path both changed; existing rows need a backfill UPDATE to prepend `s3://{bucket}/`). Operator benefit is high but the payload is too big for this audit pass.
- **Plan 096 alternative: don't rename the `get_events(key)` parameter to `get_events(blob_key)`** — keeps parameter unchanged so existing callers compile; but the parameter rename is the single biggest signal that "the value is a relative key, not a URI". Leaving it as `key` propagates the docstring burden.
- **Plan 097 alternative: drop `populate_by_name=True` from the Settings config** — the flag is dead code today; removing it makes the cleanup. But the flag was added with the explicit comment "Settings(kw=...)" intentionally, and removing it would close the door on the future test factory. The factory is the activation, not the removal. REJECTED.
- **Plan 097 alternative: inline `get_settings.cache_clear() + Settings(**overrides)` boilerplate in every test** — exactly what the factory replaces; the factory IS the DRY hoist.

**Test count.** 5 + 4 + 4 + 3 demonstrations = **16 new hermetic tests** across the 3 plans.

**Conventions for the executor.** All 3 plans:
- Touch **only** the listed files; no incidental edits.
- 095 + 097 both leave production SOURCE code untouched (095 reaches into 3 production globals via the helper; 097 reads the configured `populate_by_name=True` flag).
- 096 is the one plan that touches production source (storage.py + models.py) but is deliberately LOW-RISK — docstring + parameter-name renames; no behaviour change, no migration.

## v0.9.30 audit (closed)

**Author:** senior-advisor read-only audit pass. **Status:** current cycle.

**Scope.** `libs/gw2_api_client/src/gw2_api_client/{__init__.py, client.py, exceptions.py}` + `libs/gw2_api_client/pyproject.toml` — the 5th and last workspace library (HTTP client wrapping the GW2 v2 REST API) never audited in depth. The 4 sibling libraries (`gw2_core`, `gw2_evtc_parser`, `gw2_analytics`, `gw2analytics_api`) were all covered by earlier passes; `gw2_api_client` was the holdout.

| Plan | File(s) touched | Risk | LOC delta |
| --- | --- | --- | --- |
| **092** | `libs/gw2_api_client/src/gw2_api_client/__init__.py` | low — `importlib.metadata` pattern (replicated across the other 4 libs via plans 042 / 054 / 077 / 089); no `pyproject.toml` change because there's no drift today | +7, -1 |
| **093** | `libs/gw2_api_client/src/gw2_api_client/client.py` + `exceptions.py` | low — semantic rename of `_MAX_RATE_LIMIT_RETRIES` -> `_MAX_RATE_LIMIT_ATTEMPTS` (off-by-one footgun prevention) + removal of soft-dead `auth_required` flag in private `_get_with_retries` helper. PUBLIC Protocol surface unchanged. | +12, -16 |
| **094** | `libs/gw2_api_client/src/gw2_api_client/client.py` | medium — strip `/v2` from `_BASE_URL` (single-source-of-truth) + attach Authorization header per-request (closes the API-key-leak hazard on the public `/v2/worlds` endpoint). PUBLIC Protocol signatures unchanged. | +14, -5 |

**Dependency graph.** All three plans touch disjoint file regions: 092 touches `__init__.py`; 093 + 094 both touch `client.py` BUT touch disjoint regions (093 = `_get_with_retries` + `_MAX_RATE_LIMIT_ATTEMPTS` rename; 094 = `_BASE_URL` constant + `__init__` constructor + `_auth_headers` helper + call-sites in `account_get` / `worlds_get`). Pair-suggested ordering: 092 alone; 093 + 094 as ONE single-PR on `client.py` to avoid two PRs editing the same file in the same release window.

**Rejected alternatives (15 total across the 3 plans).** Highlights:

- **Plan 092 alternative: leave the literal at `"0.1.0"` since there's no drift today** — fine today, but releases drift without a test-layer invariant. The 4 sibling libs all moved to dynamic for the same reason; leaving `gw2_api_client` static would be the ONE library in the workspace that breaks the 5-library pattern.
- **Plan 092 alternative: bump the literal to `"1.0.0"` without touching `pyproject.toml`** — introduces drift that the future test can't catch (no test fixture). The dynamic lookup is what enforces the invariant.
- **Plan 093 alternative: keep `_MAX_RATE_LIMIT_RETRIES` with a longer docstring explaining the off-by-one hazard** — idiomatic Python (PEP 8: short, meaningful names) prefers the rename to the LLM-eating docstring. The replacement name `_MAX_RATE_LIMIT_ATTEMPTS` is self-explanatory.
- **Plan 093 alternative: add a typed `GuildWars2AuthError` exception subclass to make the `auth_required` distinction meaningful** — bigger design change (new public exception surface, cross-library impact on `apps/api` `except` clauses). Out of scope for this audit pass; the minimal fix is to drop the soft-dead flag.
- **Plan 094 alternative: build two httpx clients (one with Authorization, one without) and pick per-request** — doubles the connection pool, complicates the `aclose` lifecycle, and adds memory overhead per client instance. Per-request header attachment is the simpler fix.
- **Plan 094 alternative: hoist the API version (`/v2`) into a NEW constant `_API_VERSION = "v2"` used in BOTH `_BASE_URL` AND per-call URLs** — doubles up the constant surface without changing the fragility. The single-source-of-truth fix is to put the version in ONE place (the per-call URL is the more discoverable one).
- **Plan 094 alternative: leave `_BASE_URL` + per-call URLs with the duplicated `/v2`** — fine today but tech debt; the moment someone adds a v3 endpoint or a parameterized URL helper, the duplication bites. The strip is a 1-line fix with a 6-line test payoff.
- **Plan 094 alternative: add `httpx.Transport` middleware to strip the Authorization header at the wire layer** — invisible-to-the-caller; surprising for future contributors reading the code. The per-request dictionary kwarg is the standard httpx pattern.

**Test count.** 5 + 6 + 7 = **18 new hermetic tests** across the 3 plans.

**Conventions for the executor.** All 3 plans:
- Touch **only** the listed files; no incidental edits.
- Re-use the canonical `importlib.metadata` import style applied by plans 042 / 054 / 077 / 089; no new top-level deps.
- Match the 5-library workspace convention via the 18 new hermetic tests below.
- Plan 094's per-request Authorization pattern propagates as the recommended idiom for any future endpoint additions in the same library.

## v0.9.29 audit (closed)

**Author:** senior-advisor read-only audit pass. **Status:** current cycle.

**Scope.** `libs/gw2_core/src/gw2_core/__init__.py` + `libs/gw2_core/src/gw2_core/models.py` + `libs/gw2_core/pyproject.toml` — the foundational data-model library, never audited in depth (plan 037 referenced `gw2_core` as the source-of-truth for `disambiguate_elite_spec` but that function wasn't shipped; plan 042 migrated 3 sibling libs to `importlib.metadata.version()`; `gw2_core` is the only library still doing the literal `__version__ = "0.X.Y"` thing).

| Plan | File(s) touched | Risk | LOC delta |
| --- | --- | --- | --- |
| **089** | `libs/gw2_core/src/gw2_core/__init__.py` + `libs/gw2_core/pyproject.toml` | low — canonical `importlib.metadata` pattern (replicated across 4 sibling libs via plans 042 / 054 / 077) | +7, -1 |
| **090** | `libs/gw2_core/src/gw2_core/models.py` | medium — new public surface (`disambiguate_elite_spec`) + dispatch table; closes the "import fails" hazard for plan 065 parser call-site | +54, -2 |
| **091** | `libs/gw2_core/src/gw2_core/models.py` | low — `AliasChoices` adds a 2nd accepted wire key, doesn't drop the first | +8, -2 |

**Dependency graph.** All three plans touch disjoint file regions:
089 touches `__init__.py` + `pyproject.toml`; 090 touches the `EliteSpec` enum block in `models.py`; 091 touches the `AccountInfo` model field. PRs can land in any order or concurrently. Plan 090 is the only OUTBOUND edge: it's REQUIRED-BY plan 065 v0.9.21 (the parser call-site fix that imports `disambiguate_elite_spec`) — without 090, plan 065 ships an import that resolves to `ImportError`.

**Rejected alternatives (15 total across the 3 plans).** Highlights:

- **Plan 089 alternative: edit the literal `__version__` to "0.5.0" and forget about it** — defeats the entire point of dynamic resolution and re-opens the drift on the next release. The 4 sibling libs all moved to dynamic for this exact reason. REJECTED.
- **Plan 090 alternative: bake the disambiguation into `EliteSpec.from_raw(raw, profession)` as a classmethod** — awkward (enums don't take external params in their constructor) and hides the dispatch table from `repr(EliteSpec)`.
- **Plan 090 alternative: move the dispatch table to `libs/gw2_evtc_parser` instead of `gw2_core`** — conceptually backwards: the parser imports game data FROM `gw2_core` (per `__init__.py`'s module docstring); the dispatch IS game data.
- **Plan 090 alternative: forbid the bare `EliteSpec(raw)` cast at runtime** (raise `TypeError`) — breaks the parser's read path BEFORE the helper is called; the docstring + parser-side plan 065 enforcement are the right layer.
- **Plan 091 alternative: drop the alias entirely and rename the field back to plain `world_id` (no wire alias)** — breaking change for all callers sending `{"world": ...}`. Today the library offers a compatibility shim; removing it is a regression. REJECTED.
- **Plan 091 alternative: use `model_config[populate_by_name] = True` instead of `AliasChoices`** — `populate_by_name` lets you use the Python-name as input but DOES NOT support accepting MULTIPLE wire keys. The dual-key requirement is exactly what `AliasChoices` is for.
- **Plan 091 alternative: leave as-is — "the API hasn't broken yet"** — fine today, but tech debt. The 2023-2024 v2 API modernisation wave ArenaNet ran on other endpoints (e.g. `worlds` schema consolidation) sets the precedent; `accounts.world` → `accounts.world_id` is a guaranteed-future schema change.
- **Plan 091 alternative: use `Field(alias=AliasChoices(...))` (the old combined `alias` parameter)** — `validation_alias` + `serialization_alias` are more explicit; latest Pydantic v2 emits a `DeprecationWarning` when a dict is passed to the combined `alias=` slot with two keys.

**Test count.** 5 + 6 + 4 = **15 new hermetic tests** across the 3 plans.

**Conventions for the executor.** All 3 plans:
- Touch **only** the listed files; no incidental edits.
- Are additive-only except plan 089 which RETIRES the stale literal `__version__ = "0.5.0"` (the dynamic lookup replaces it, not augments it).
- Re-use the canonical `gw2_core` import style (`from pydantic import ...`, `from __future__ import annotations`); no new top-level deps.
- Match the docstring ↔ implementation ↔ test invariant via the 15 new hermetic tests below.

## v0.9.22 audit (closed)



**Author:** senior-advisor audit (improve skill, standard effort) — web/app layout + CSS deep pass (the styling layer of the frontend never audited: the 7 `page.tsx` files were covered by v0.9.7 but the root `layout.tsx` + the 3 CSS files (`globals.css` + `page.module.css` + `upload/page.module.css`) never had a senior-advisor pass)
**Stamped at:** `44ea862` (origin/main HEAD at audit time — after the v0.9.21 core parser pass landed: 3 plans 065/066/067 written + indexed)
**Recon scope:** `web/src/app/layout.tsx` (the root layout with the sticky header + the metadata export) + `web/src/app/globals.css` (the design tokens + the body styles + the prefers-color-scheme media query) + `web/src/app/page.module.css` (the landing-page styles with the gradient title + the card grid + the hover transitions) + `web/src/app/upload/page.module.css` (the upload-page styles with the visually-hidden file input + the form layout + the error + the result card)
**Audit mode:** standard effort; targeted deep pass on the web/app layout + CSS surfaces for the patterns not covered by v0.9.7 (page-layer defensive code) or v0.9.6 (component-level CSS); 3 findings selected for planning (1 LOW-MED prod-readiness + 1 LOW a11y + 1 LOW DX)

### v0.9.22 status table

| # | Plan | Status | Addresses finding | Effort |
|---|---|---|---|---|
| 068 | [068-v0922-layout-tsx-polish](./068-v0922-layout-tsx-polish.md) | **pending** (NEW `web/src/app/layout.module.css` extracts the header's inline `style={{}}` block (sticky position + z-index + padding + background + border + gap + flex-wrap + the brand link's font-size + font-weight + color) into 2 named CSS module classes (`.header` + `.brand`); `layout.tsx` switches to `className={styles.header}` + `className={styles.brand}`. PLUS the `metadata` export gains 9 new fields: `metadataBase: new URL(SITE_URL)` (where `SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://gw2analytics.example.com"`), `title: { default, template }` (template-aware per-page titles), `applicationName` + `keywords` + `authors` + `creator` + `publisher` + `robots` + `alternates.canonical` + `icons` (favicon.ico + icon.svg + apple-touch-icon.png) + `manifest: "/manifest.webmanifest"` + `openGraph: { type, locale, url, siteName, title, description }` + `twitter: { card, title, description }` + `viewport: { width, initialScale, themeColor }`. 3 NEW asset files: `app/icon.svg` (1 KB SVG), `app/apple-touch-icon.png` (256x256 PNG), `app/manifest.webmanifest` (minimal PWA manifest with name + short_name + start_url + display + background_color + theme_color). 8 NEW hermetic tests cover the 8 surfaces) | #1 `web/src/app/layout.tsx` has 2 polish issues: (a) the `<header>` uses inline `style={{}}` for all visual properties (breaks the design-token abstraction + is inconsistent with the rest of the codebase which uses CSS modules); (b) the `metadata` export is minimal (only `title` + `description`) — missing `metadataBase` (required for absolute URL construction in OG images), `viewport` (explicit mobile rendering), `themeColor` (browser chrome color matching `--accent`), `openGraph` + `twitter` (rich previews on Discord/Slack/X), `icons` (canonical favicon + apple-touch-icon path), `manifest` (PWA manifest path), `alternates.canonical` (canonical URL of the site), `robots` (explicit `index, follow`) (DX + prod-readiness, LOW-MED) | S |
| 069 | [069-v0922-a11y-prefers-reduced-motion-focus-visible](./069-v0922-a11y-prefers-reduced-motion-focus-visible.md) | **pending** (`web/src/app/globals.css` gains 2 new a11y blocks: (a) `@media (prefers-reduced-motion: reduce)` with the `*, *::before, *::after { animation-duration: 0.01ms !important; animation-iteration-count: 1 !important; transition-duration: 0.01ms !important; scroll-behavior: auto !important; }` override (closes the gap that `page.module.css::.card` has `transition: transform 0.15s ease-in-out` + `:hover { transform: translateY(-2px); }` + `upload/page.module.css::.fileChip` + `.submit` have similar transitions — none gated on `prefers-reduced-motion`); (b) `:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }` + `a:focus-visible { opacity: 1; }` (the canonical `:focus-visible` pattern — keyboard users see the ring on Tab; mouse users don't). The `.fileChip:focus-within` rule in `upload/page.module.css` is preserved (no regression). 6 NEW hermetic tests cover the 6 surfaces) | #2 The CSS has motion effects (`.card` transform + `.fileChip`/`.submit` transitions + `a` opacity transition) not gated on `prefers-reduced-motion: reduce` (WCAG 2.1 §2.3.3 Animation from Interactions recommends disabling non-essential motion for users who prefer reduced motion — the canonical CSS Media Queries Level 5 `prefers-reduced-motion` media query is the fix); no explicit `:focus-visible` outline (the browser default is preserved but inconsistent across browsers — the design system cannot control the focus indicator without an explicit rule; WCAG 2.1 §2.4.7 Focus Visible AA requires the focus indicator to be visible) (a11y, LOW) | S |
| 070 | [070-v0922-dry-brand-title-card-utilities](./070-v0922-dry-brand-title-card-utilities.md) | **pending** (`web/src/app/globals.css` gains 3 new utility classes: `.brand` (the 11-property brand-pill block duplicated byte-for-byte in `page.module.css` + `upload/page.module.css`), `.title` (the 7-property gradient-text block duplicated in both files, with `font-size` left as a per-page override), `.card-surface` (the 3-property `border + border-radius + background` base duplicated in both files' `.card` blocks). `page.module.css` + `upload/page.module.css` drop their per-page `.brand` + `.title` + `.card-surface` properties; the page components (`app/page.tsx` + `app/upload/page.tsx`) update their `className` props to use the global utility names alongside the per-page layout class. 8 NEW hermetic tests cover the 8 surfaces (3 globals present + 2 page modules don't redefine + 2 page components use the utilities + 2 page modules keep the per-page `font-size` override) | #3 `web/src/app/page.module.css` + `web/src/app/upload/page.module.css` duplicate the 11-property `.brand` block + the 7-property `.title` gradient block + the 3-property `.card-surface` base (a future maintainer who changes one without the other creates a silent drift — a real risk as the project grows to 5+ page-level CSS modules) (DX, LOW) | S |

### Recommended execution order (v0.9.22)

1. **Plan 069** (a11y) — S effort, the highest-clarity win (a11y improvements are forward-compat; no visual change for users without the `prefers-reduced-motion` preference). 1 file edit (globals.css) + 6 tests. Independent of 068/070.
2. **Plan 070** (DRY utility classes) — S effort, the DX win. 1 globals.css edit + 2 page module refactors + 2 page component edits + 8 tests. Independent.
3. **Plan 068** (layout polish) — S effort, the largest single change (layout.tsx + 3 new asset files + 8 metadata fields). Spans 1 layout.tsx + 1 NEW layout.module.css + 3 NEW asset files + 8 tests. Independent.

All 3 are independent. Could ship in any order. The recommended order is by clarity (a11y first, then DRY, then layout polish).

### Dependency graph (v0.9.22)

```
  plan 069 ─── INDEPENDENT ──── (web/src/app/globals.css + tests)
  plan 070 ─── INDEPENDENT ──── (web/src/app/globals.css + web/src/app/{page,upload/page}.module.css + web/src/app/{page,upload/page}.tsx + tests)
  plan 068 ─── INDEPENDENT ──── (web/src/app/layout.tsx + web/src/app/layout.module.css + 3 NEW asset files + tests)
```

No shared file paths across the 3 plans. Could be PR'd in parallel by 3 different engineers.

### Considered and rejected (v0.9.22)

- **Plan 068 alternative: move the metadata to a separate `app/metadata.ts` file**: tempting (separation of concerns). The Next.js 16 App Router auto-discovers `metadata` exports from `layout.tsx` + `page.tsx`; moving to a separate file would break the convention. The metadata stays in `layout.tsx`.
- **Plan 068 alternative: use a Next.js 15 `generateMetadata` function** instead of a static `metadata` export: tempting (more flexible). The current metadata is static (no per-request computation). A future plan can add `generateMetadata` if per-request metadata is needed (e.g., a per-account player profile title).
- **Plan 068 alternative: skip the OG / Twitter cards** (no social sharing): tempting (the project is a personal analytics tool, not a marketing site). The OG / Twitter cards are informational; a future share of a fight URL on Discord shows a rich preview (the screenshot + the player name). The 5 lines of metadata are a low-cost forward-compat win.
- **Plan 068 alternative: skip the `manifest.webmanifest`** (PWA support): the PWA is not a v0.9.x goal. The manifest is a forward-compat knob (a future plan can ship a Service Worker + the manifest becomes useful).
- **Plan 068 alternative: use a `useEffect` + `document.head` injection for the metadata**: out of scope (the Next.js metadata API is the canonical pattern).
- **Plan 069 alternative: add `prefers-reduced-motion` per-component** (not global): tempting (more granular). The MDN-canonical pattern is the global `*` selector override. Per-component rules are easy to miss (a future component author forgets to add the rule).
- **Plan 069 alternative: use `prefers-reduced-motion: no-preference`** (gate the motion ON for users WITHOUT the preference, instead of OFF for users WITH the preference): tempting (preserves the default). The `reduce` media query is the canonical pattern per the WCAG 2.1 §2.3.3 recommendation + the MDN docs.
- **Plan 069 alternative: use JS to detect the `prefers-reduced-motion` media query and disable CSS transitions imperatively**: out of scope (the CSS media query is the canonical pattern; a JS-based approach is a fallback for legacy browsers that don't support the media query — not a v0.9.x concern).
- **Plan 069 alternative: skip the `*:focus-visible` rule** (rely on browser defaults): tempting (less code). The browser default is inconsistent across browsers; the explicit rule ensures a consistent focus indicator.
- **Plan 069 alternative: use `outline: 3px solid var(--accent)`** (thicker ring): the `2px` is the canonical Tailwind + Material UI default; the `3px` is heavier without a corresponding legibility win.
- **Plan 070 alternative: move all CSS modules to global stylesheets** (no CSS modules): out of scope (the per-page CSS modules are the canonical Next.js 16 pattern for per-page styles; the global utility classes are an additive layer for shared styles).
- **Plan 070 alternative: use a CSS-in-JS library** (e.g., `styled-components`): out of scope (the project standardizes on CSS modules; the CSS-in-JS migration is a future cycle).
- **Plan 070 alternative: drop the `card-surface` utility class** (let the per-page `.card` define the full surface): tempting (simpler). The 3 lines of `border + border-radius + background` are duplicated in 2 files (and will be duplicated in 3+ files as the project grows). The utility class is the canonical DRY fix.
- **Plan 070 alternative: use CSS `@layer`** to control the cascade order: out of scope (the `@layer` system is a modern CSS feature with limited browser support for the `!important` interaction; the current code's cascade order is fine).
- **Plan 070 alternative: use Tailwind CSS** instead of CSS modules: out of scope (the project standardizes on CSS modules; the Tailwind migration is a future cycle).

## v0.9.21 audit (closed)

**Author:** senior-advisor audit (improve skill, standard effort) — core parser deep pass (the surface never audited in depth: only the zip-bomb part was covered by plan 020 v0.9.6; the rest of the EVTC binary parsing, the agent/skill extraction, the build_version detection, the per-event discrimination, the .zevtc archive unwrapping all never had a senior-advisor pass)
**Stamped at:** `44ea862` (origin/main HEAD at audit time — after the v0.9.20 design docs pass landed: 3 plans 062/063/064 written + indexed)
**Recon scope:** `libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py` (the full ~520-line core parser, including the module-level binary layout constants, the `PythonEvtcParser` class, the `_iter_fights` + `_iter_agents` + `_iter_skills` + `_compute_post_skills_offset` + `_decode_agent` + `_read_all` helpers, the `read_zevtc_archive` + `read_zevtc_bytes` public API, and the `__all__` re-exports)
**Audit mode:** standard effort; targeted deep pass on the core parser for the surfaces not covered by v0.9.6 plan 020 (zip-bomb) or v0.9.11 plan 037 (EliteSpec disambiguation function only — the parser call site is a separate finding); 3 findings selected for planning (1 LOW-MED correctness + 1 LOW DX + 1 LOW defense-in-depth)

### v0.9.21 status table

| # | Plan | Status | Addresses finding | Effort |
|---|---|---|---|---|
| 065 | [065-v0921-parser-elitespec-disambiguation](./065-v0921-parser-elitespec-disambiguation.md) | **pending** (`parser.py::_decode_agent` calls `EliteSpec(elite_raw)` to resolve the agent's elite specialization — but the `EliteSpec` IntEnum has 2 value collisions (SOULBEAST=55 collides with DAREDEVIL=55; WEAVER=63 collides with RENEGADE=63) so a Ranger/Soulbeast is misclassified as DAREDEVIL + an Elementalist/Weaver is misclassified as RENEGADE. Plan 037 (v0.9.11) introduces the `disambiguate_elite_spec(raw_value, profession) -> EliteSpec` function in `gw2_core` that uses the agent's profession to pick the right member; the parser's call site is the missing piece. Fix: 1-line edit `EliteSpec(elite_raw)` → `disambiguate_elite_spec(elite_raw, profession)` + import the function from `gw2_core` + drop the now-dead `try/except ValueError` (the new function never raises). 6 NEW hermetic tests cover the 4 disambiguated cases (Soulbeast vs Daredevil + Weaver vs Renegade) + the non-collision fallback (Dragonhunter from Guardian) + the unknown-elite fallback) | #1 `parser.py::_decode_agent` calls `EliteSpec(elite_raw)` directly which resolves the 2 value-collision cases to the wrong member (Soulbeast→Daredevil, Weaver→Renegade); plan 037 introduced the `disambiguate_elite_spec` function but the parser's call site was not updated (correctness, LOW-MED — affects ~30% of WvW raid players) | S |
| 066 | [066-v0921-parser-skill-offset-dedup](./066-v0921-parser-skill-offset-dedup.md) | **pending** (NEW private helper `_iter_skill_records(data, offset, count) -> Iterator[tuple[int, int, str]]` yields `(skill_id, name_len, name)` for each skill record with the truncation + `name_len > MAX_SKILL_NAME_BYTES` checks at one site; both `_iter_skills` and `_compute_post_skills_offset` refactored to consume the helper. `_iter_skills` is reduced to a 2-line wrapper; `_compute_post_skills_offset` re-uses the same record walk with a `cursor` accumulator (1-line re-computation of `record_size` from `name_len`). 6 NEW hermetic tests cover the 6 surfaces: yields the same triples as the original `_iter_skills`, stops on truncation, stops on oversized name, the byte-offset is identical pre/post refactor, returns `end` on truncation, `parse_events` first event is past the skill table) | #2 `parser.py` has 2 functions (`_iter_skills` + `_compute_post_skills_offset`) that walk the skill table with the same 7-step logic (truncation check, name_len unpack, oversized check, record_size compute, body truncation check, cursor advance); a bug fix in one (e.g., a new safety bound) would need to be mirrored in the other — drift risk (DX, LOW) | S |
| 067 | [067-v0921-parser-max-evtc-bytes-cap](./067-v0921-parser-max-evtc-bytes-cap.md) | **pending** (NEW module-level `MAX_EVTC_BYTES: Final[int] = 100 * 1024 * 1024` (100 MB) constant alongside the existing `MAX_AGENTS` + `MAX_SKILLS` + `MAX_SKILL_NAME_BYTES`; `_read_all(source)` gains a post-materialisation size check that raises `EvtcParseError` if `len(data) > MAX_EVTC_BYTES`; the error message includes the actual size + the bound + a remediation hint ("split the blob or use the streaming parse_events API for larger archives"). The 100 MB cap is a defense-in-depth backstop for direct library consumers (CLI tools, Jupyter notebooks, FaaS workers) that bypass the API layer's 30 MB cap (per plan 048). 6 NEW hermetic tests cover: under cap passes, over cap raises, at cap passes (inclusive), `BinaryIO` over cap raises, `parse()` propagates the cap, `parse_events()` propagates the cap) | #3 `parser.py::_read_all` materialises the entire input `bytes` / `BinaryIO.read()` without any upper bound; a 1 GB .zevtc OOMs the parser because the existing `MAX_AGENTS` + `MAX_SKILLS` + `MAX_SKILL_NAME_BYTES` bounds protect the structure of the data, not the size of the input; the API layer's 30 MB cap (plan 048) protects the API surface but is bypassed by direct library consumers (defense-in-depth, LOW) | S |

### Recommended execution order (v0.9.21)

1. **Plan 065** (parser call site) — S effort, the highest-leverage single fix (real bug closure for Soulbeast + Weaver players). 1 file edit + 6 tests. Independent of 066/067.
2. **Plan 067** (MAX_EVTC_BYTES cap) — S effort, the defense-in-depth win. 1 file edit + 6 tests. Independent.
3. **Plan 066** (skill offset dedup) — S effort, the DX win. 1 file refactor (extract `_iter_skill_records` + 2 consumers) + 6 tests. Independent.

All 3 are independent. Could ship in any order. The recommended order is by leverage (correctness bug > defense-in-depth > DX).

### Dependency graph (v0.9.21)

```
  plan 065 ─── INDEPENDENT ──── (libs/gw2_evtc_parser/parser.py + tests)
  plan 066 ─── INDEPENDENT ──── (libs/gw2_evtc_parser/parser.py + tests)
  plan 067 ─── INDEPENDENT ──── (libs/gw2_evtc_parser/parser.py + tests)
```

All 3 plans touch `parser.py` (additive: each adds a new block, no overlapping edits) + each adds 1 new test case to `test_parser.py` (additive: each adds a new test, no overlapping edits). Could be PR'd in any order or in parallel by 3 different engineers (the additive nature means the merge conflicts are minor — each PR adds a distinct section).

### Considered and rejected (v0.9.21)

- **Plan 065 alternative: drop plan 037's parser sub-step + rely on this plan**: tempting (the parser call site is the bug surface; the function is a means to an end). Plan 037's value is the function + the 6 tests; this plan's value is the call-site wiring. Both are needed.
- **Plan 065 alternative: inline the disambiguation table in the parser** (instead of importing the function from `gw2_core`): out of scope (the table is the canonical disambiguation contract; it belongs in `gw2_core` alongside the enum).
- **Plan 065 alternative: add a `profession` keyword to `EvtcParser.parse()`** so the disambiguation can be deferred to the consumer: out of scope (the parser has the profession at the agent decode step; deferring would force every consumer to duplicate the disambiguation logic).
- **Plan 065 alternative: validate the disambiguation via a CI grep** that asserts `EliteSpec(elite_raw)` does NOT appear in the parser's source: out of scope (a future regression could re-introduce the bug; the 6 hermetic tests catch it at runtime).
- **Plan 066 alternative: inline `_compute_post_skills_offset` into `parse_events`**: tempting (the function is only used in one place). The offset computation is non-trivial (the skill table walk); inlining would clutter `parse_events` (already a 100-line function).
- **Plan 066 alternative: add a `next_offset` field to the helper's yield tuple**: tempting (eliminates the re-computation in `_compute_post_skills_offset`). The `name_len + 1` is O(1) per skill; the re-computation cost is negligible. The 3-tuple yield is more Pythonic than a 4-tuple.
- **Plan 066 alternative: use `functools.partial` to bind `data, offset, count` to the helper**: out of scope (the helper needs the consumer's loop body; partial doesn't help).
- **Plan 066 alternative: switch to a dataclass `_SkillRecord`** instead of a 3-tuple: out of scope (the helper is private; the 3-tuple is the canonical Python "internal record" idiom for a function-private helper).
- **Plan 066 alternative: move `_iter_skill_records` to a new `libs/gw2_evtc_parser/_skill_table.py` module**: out of scope (the helper is private to the parser; the module is small enough that 1 file is appropriate).
- **Plan 067 alternative: check in `parse()` and `parse_events()` separately (not in `_read_all`)**: out of scope (the check is duplicated in 2 places; `_read_all` is the single chokepoint).
- **Plan 067 alternative: check via `os.environ.get("GW2_PARSER_MAX_BYTES")`** (operator-overridable cap): out of scope. The 100 MB cap is a safety bound, not a tunable. A future plan can add an env-var override if an operator requests it (similar to plan 040's `db_pool_size` env var).
- **Plan 067 alternative: check via a pre-allocation size hint** (e.g., `BinaryIO.seek(0, 2); tell()`): tempting (prevents the allocation). The `tell()` is not reliable for non-seekable streams; the post-allocation check is the canonical pattern.
- **Plan 067 alternative: drop the cap entirely** (rely on the API's 30 MB cap): tempting (the API is the canonical entry point). Direct library consumers (CLI tools, Jupyter notebooks) bypass the API; the cap is the defense-in-depth backstop.
- **Plan 067 alternative: set the cap to 1 GB** (accommodate very large archives): out of scope (1 GB is 2.5× the 4 GB container's memory budget for the parser; OOM risk).
- **Plan 067 alternative: stream the event records** (per `docs/ROADMAP.md` §2 "Rust + PyO3 parser binding"): out of scope (the streaming parser is a future Rust binding; the Python parser is memory-bound).

## v0.9.20 audit (closed)

**Author:** senior-advisor audit (improve skill, standard effort) — design docs + contributor guide deep pass (the surfaces never audited: backend webhook spec doc + combat-readout design doc + statechange-ids table + ROADMAP + CONTRIBUTING — for drift vs current code + stale current state)
**Stamped at:** `44ea862` (origin/main HEAD at audit time — after the v0.9.19 API/build/CI/lint config pass landed: 3 plans 059/060/061 written + indexed)
**Recon scope:** `docs/v0.8.0-backend-design.md` + `docs/v0.9.0-combat-readout-design.md` + `docs/statechange-ids.md` + `docs/ROADMAP.md` + `CONTRIBUTING.md`
**Audit mode:** standard effort; targeted deep pass on the design docs + contributor guide for drift vs v0.9.2 code; 3 findings selected for planning (3 LOW docs hygiene)

### v0.9.20 status table

| # | Plan | Status | Addresses finding | Effort |
|---|---|---|---|---|
| 062 | [062-v0920-v080-backend-design-doc-drift](./062-v0920-v080-backend-design-doc-drift.md) | **pending** (4 sub-fixes in `docs/v0.8.0-backend-design.md`: (a) §3.4 outbound POST User-Agent `Gw2Analytics-Webhook/0.8.0` → `Gw2Analytics-Webhook/0.9.2` (matches the post-plan-052 canonical value); (b) §4 schema gains 2 v0.9.1 columns (`next_attempt_at` indexed for polling + `payload` LargeBinary for HMAC fidelity) + `delivered_at` is now NULLable (no NOT NULL DEFAULT) + a footnote pointing to migration 0007; (c) §5 worker design splits the failure-path bullet into 2 sub-bullets (attempt increment + `next_attempt_at` schedule) and adds the explicit "leaves `delivered_at` NULL until success" semantic; (d) §6 future-work list marks the 2 shipped items ("Webhook replay / redelivery UI" + "Per-event-kind filtering") with "✅ shipped in v0.9.1" annotations; 7 NEW hermetic tests assert the 7 surfaces + a "Last refreshed at v0.9.2" footer) | #1 `docs/v0.8.0-backend-design.md` has 4 drift sub-issues vs v0.9.2 code: User-Agent is `0.8.0` (should be `0.9.2`), §4 schema is missing the v0.9.1 `next_attempt_at` + `payload` columns, `delivered_at` is documented as NOT NULL DEFAULT but is actually NULLable, §5 worker design conflates success vs failure state transitions, §6 future-work lists items that have shipped in v0.9.1 + v0.9.2 (docs hygiene, LOW) | S |
| 063 | [063-v0920-roadmap-stale-current-state](./063-v0920-roadmap-stale-current-state.md) | **pending** (3 sub-fixes in `docs/ROADMAP.md`: (a) "Current state" header refreshed to "Last refreshed at v0.9.2" + "Latest shipped tag: v0.9.2" + test count placeholder ("TBD — see CI badge for the current count"); (b) §1.1 "Items removed since v0.8.0/v0.8.9 release cycle" gains a new "shipped in v0.9.1" entry for the webhook retry + DLQ + replay (mirrors the §2.1 archival note per the doc's intentional dual-listing); (c) §1.2 "Ready to implement" shortlist removes the now-shipped retry+DLQ+replay item; 4 NEW hermetic tests assert the 4 surfaces + a "Last refreshed at v0.9.2" footer) | #2 `docs/ROADMAP.md` "Current state" header is stale ("v0.8.9" tag, "303 active tests", "v0.9.0 close-out" refresh) and §1.1/§1.2 don't reconcile the v0.9.1 retry+DLQ+replay ship (docs hygiene, LOW) | S |
| 064 | [064-v0920-combat-readout-deferred-banner](./064-v0920-combat-readout-deferred-banner.md) | **pending** (`docs/v0.9.0-combat-readout-design.md` gains a "⚠️ DEFERRED TO v1.0+" banner at the top of the doc (between the heading and the Status line) that explains: (a) the v0.9.0 cycle shipped higher-priority items (shared timeline chart, filter by profession, visual regression), (b) the combat readout is the longest-cycle v1.0 candidate blocked on a v1.4+ parser + a new `libs/gw2_skills` library + the role classifier heuristic, (c) the canonical shortlist is in `docs/ROADMAP.md` §1.2, (d) the §9 build sequence is the design-AS-WRITTEN, not the current implementation plan; the `**Status:**` line gains a "(see banner above; not scheduled for v0.9.x; canonical shortlist in `docs/ROADMAP.md` §1.2)" annotation; 3 NEW hermetic tests assert the 3 surfaces) | #3 `docs/v0.9.0-combat-readout-design.md` header says "Target: v0.9.0" but the v0.9.0 cycle shipped higher-priority items; the doc looks like an upcoming-cycle spec to a new reader (the actual shortlist is in `docs/ROADMAP.md` §1.2) (docs hygiene, LOW) | S |

### Recommended execution order (v0.9.20)

1. **Plan 064** (combat-readout banner) — S effort, the smallest + highest-clarity win. 1 banner + 1 status annotation + 3 tests. Independent of 062/063.
2. **Plan 063** (ROADMAP refresh) — S effort, the current-state hygiene. 1 doc refresh + 4 tests. Independent.
3. **Plan 062** (webhook spec doc refresh) — S effort, the spec-sync work (4 sub-fixes in 1 doc). Independent.

All 3 are independent. Could ship in any order. The recommended order is by clarity (single banner first, then full doc refreshes).

### Dependency graph (v0.9.20)

```
  plan 064 ─── INDEPENDENT ──── (docs/v0.9.0-combat-readout-design.md + tests)
  plan 063 ─── INDEPENDENT ──── (docs/ROADMAP.md + tests)
  plan 062 ─── INDEPENDENT ──── (docs/v0.8.0-backend-design.md + tests)
```

No shared file paths. Could be PR'd in parallel by 3 different engineers.

### Considered and rejected (v0.9.20)

- **Plan 062 alternative: freeze the doc as "v0.8.0 design AS-WRITTEN"** with a banner saying "see current code for v0.9.x additions": tempting (preserves history). The doc is a SPEC doc (§3 API + §4 schema + §5 worker); freezing it would force new implementers to read both the doc + the CHANGELOG to understand the current behavior. The refresh option is the canonical fix.
- **Plan 062 alternative: delete the doc + consolidate into CHANGELOG**: out of scope (the CHANGELOG is a release log, not a spec). The spec doc has independent value (API contract + schema + worker design in one place).
- **Plan 062 alternative: move the schema doc to a separate `docs/v0.9.x-webhook-schema.md`** + add a "see also" pointer: out of scope. The schema is tightly coupled to the API contract (§3) + the worker design (§5); a split would scatter the related material.
- **Plan 062 alternative: document the `next_attempt_at` + `payload` columns in the CHANGELOG only (no doc update)**: the CHANGELOG entry already exists (per the ROADMAP §2.1 archival note). The spec doc is the canonical reference for new implementers; the CHANGELOG is for historical context. Both are needed.
- **Plan 063 alternative: drop the test count from the ROADMAP entirely** (let the CI badge be the sole source): tempting (the placeholder is a temporary degradation). The test count is a useful at-a-glance signal in the doc itself; the CI badge is a separate surface. A future plan can add a CI-injected value to make the count dynamic.
- **Plan 063 alternative: drop the "Latest shipped tag" from the ROADMAP** (let the git tag be the sole source): same reasoning as above. The tag is a useful at-a-glance signal.
- **Plan 063 alternative: move the ROADMAP to a CI-rendered page** (e.g., a GitHub Pages site): out of scope (the doc is a markdown file in the repo; a CI-rendered page is a future refactor).
- **Plan 063 alternative: consolidate §1.1 + §2.1 "shipped" lists into a single "archive" section**: out of scope (the doc's structure is intentional: §1 is "v1.0 candidates", §2 is "tech debt"; the shipped items in each section have different contexts).
- **Plan 064 alternative: delete the doc + re-derive from the brainstorming sessions**: out of scope (the doc is the canonical specification; deleting it would force the maintainer to re-derive the column definitions + the role classifier heuristic + the default sort).
- **Plan 064 alternative: move the doc to a `docs/deferred/` subdirectory + add a top-level "see also" in `docs/README.md`**: out of scope (the docs directory does not have a `README.md`; the `CONTRIBUTING.md` mentions the design docs implicitly via the "Regenerating the web TypeScript client" section + the ROADMAP §6 "open questions" references). A future plan can add a `docs/README.md` if the doc count grows.
- **Plan 064 alternative: update the §9 build sequence to reflect the v0.9.2 codebase** (i.e., drop the "statechange parser" + "skills DB" prerequisites that have not landed): out of scope. The build sequence is a forward-looking plan; the prerequisites are the canonical blockers. Refreshing the build sequence would require re-estimating the effort + re-deriving the dependency graph, which is a future maintainer's responsibility when they pick up the work.
- **Plan 064 alternative: add a CI drift check that asserts the banner is present**: out of scope (the banner is a human-curated marker; a CI check would force a regex match on the banner text, which is fragile).

## v0.9.19 audit (closed)

**Author:** senior-advisor audit (improve skill, standard effort) — API/build/CI/lint config + tooling deep pass (the surfaces never audited: API package deps + alembic env + root + ruff + mypy + pytest configs + pre-commit + editorconfig + python-version)
**Stamped at:** `44ea862` (origin/main HEAD at audit time — after the v0.9.18 web/* build/CI/test config pass landed: 3 plans 056/057/058 written + indexed)
**Recon scope:** `apps/api/pyproject.toml` + `apps/api/alembic/env.py` + `apps/api/alembic.ini` + `apps/api/README.md` + `pyproject.toml` (root) + `ruff.toml` + `mypy.ini` + `pytest.ini` + `.pre-commit-config.yaml` + `.editorconfig` + `.python-version`
**Audit mode:** standard effort; targeted deep pass on the API/build/CI/lint config surfaces; 3 findings selected for planning (1 HIGH-LOW bug + 2 LOW DX)

### v0.9.19 status table

| # | Plan | Status | Addresses finding | Effort |
|---|---|---|---|---|
| 059 | [059-v0919-duplicate-fastapi-mcp-dep](./059-v0919-duplicate-fastapi-mcp-dep.md) | **pending** (`apps/api/pyproject.toml` `dependencies` array has 2 issues: (a) duplicate `fastapi-mcp` entry with conflicting minimums (`fastapi-mcp>=0.4` on line 12 + `fastapi-mcp>=0.1` on line 22 -- both kept by TOML parser, `uv` resolves the union to `>=0.4` so functionally correct but syntactically sloppy + drift risk); (b) `"httpx>=0.27",    "gw2_core",` shared line (valid TOML but unreadable). Fix: remove the second `fastapi-mcp>=0.1` line + split the shared line + re-sort the `dependencies` list alphabetically for readability (the canonical Python community convention per PEP 8 for `__all__` + the pip-tools default). 5 NEW hermetic tests in NEW `apps/api/tests/test_pyproject_toml.py` cover the 5 surfaces: no duplicate dep, canonical minimum is `>=0.4`, one item per line, alphabetical order, `uv lock --check` is clean) | #1 `apps/api/pyproject.toml::dependencies` has 2 sloppy entries: duplicate `fastapi-mcp` with conflicting minimums + shared line `"httpx>=0.27",    "gw2_core",` (DX + drift, HIGH-LOW -- the duplicate is functionally correct because `uv` resolves the union, but sloppy authoring + drift risk) | S |
| 060 | [060-v0919-root-pyproject-config-dedup](./060-v0919-root-pyproject-config-dedup.md) | **pending** (root `pyproject.toml` has 3 dead/partial config blocks that conflict with the canonical files: `[tool.ruff]` (root has 7 `select` categories; `ruff.toml` has 19; the ruff.toml wins per ruff's config discovery), `[tool.mypy]` (root has 5 per-flag settings; `mypy.ini` has `strict = True` umbrella + `plugins = pydantic.mypy` + `exclude` + per-module overrides; the mypy.ini wins for shared keys), `[tool.pytest.ini_options]` (root has `asyncio_mode = "strict"`; `pytest.ini` has `asyncio_mode = auto`; CRITICAL semantic drift -- `auto` auto-applies `@pytest.mark.asyncio` to all async tests; `strict` requires explicit decorators; the two disagree). Fix: remove all 3 dead blocks from root `pyproject.toml`; move the `fastapi_mcp` ignore-missing-imports override from `[tool.mypy.overrides]` to `mypy.ini` as `[mypy-fastapi_mcp]`; keep `[tool.uv.workspace]` + `[tool.uv.sources]` + `[tool.uv]` + `[tool.pytest_env]` (the canonical uv/pytest-env blocks). NEW `scripts/check_pyproject_drift.py` CI drift detector parses root `pyproject.toml` with `tomllib` + asserts no `[tool.ruff]`, `[tool.mypy]`, or `[tool.pytest.ini_options]` keys are present. 8 NEW hermetic tests cover the 8 surfaces) | #2 Root `pyproject.toml` has 3 dead/partial config blocks that conflict with the canonical `ruff.toml` / `mypy.ini` / `pytest.ini` files; the CRITICAL drift is `asyncio_mode = "strict"` (root) vs `asyncio_mode = auto` (pytest.ini) -- a semantic difference in how pytest handles async test functions (DX + drift, LOW; the pytest.ini wins so the practical impact is "root's value is invisible") | S |
| 061 | [061-v0919-alembic-compare-flags-workspace-source](./061-v0919-alembic-compare-flags-workspace-source.md) | **pending** (`apps/api/alembic/env.py::context.configure()` gains `compare_type=True` + `compare_server_default=True` at BOTH the offline + online call sites; alembic 1.13+ auto-detects column type changes (e.g., `Integer` → `BigInteger`) + server-side default changes (e.g., `'pending'` → `'parsing'`) only with these flags; the current migrations 0001-0008 are hand-written so the gap hasn't surfaced, but the next autogenerated migration will. PLUS: `apps/api/pyproject.toml` changes `"gw2_api_client>=0.1.0"` to bare `"gw2_api_client"` + root `pyproject.toml`'s `[tool.uv.sources]` gains `gw2_api_client = { workspace = true }` (matching the pattern of the other 3 libs: gw2_core, gw2_evtc_parser, gw2_analytics); a developer's local edit to `libs/gw2_api_client/` is now picked up by `uv sync` without a manual rebuild. 7 NEW hermetic tests cover the 7 surfaces: both `compare_*` flags in both call sites, workspace source present, no version pin on the apps/api dep, `uv sync` resolves to workspace, autogenerate detects type change, autogenerate detects server default change) | #3 `apps/api/alembic/env.py::context.configure()` is missing `compare_type=True` + `compare_server_default=True` -- alembic 1.13+ autogenerate mode silently misses column type + server-default changes; `apps/api/pyproject.toml` pins `gw2_api_client>=0.1.0` from PyPI while the same library is also a workspace member under `libs/gw2_api_client/` (the other 3 libs are consumed from the workspace, this one is the odd one out) (DX + dev-experience, LOW) | S |

### Recommended execution order (v0.9.19)

1. **Plan 059** (duplicate fastapi-mcp) — S effort, the highest-leverage single fix (1-file cleanup + 5 tests). Independent of 060/061.
2. **Plan 060** (config dedup) — S effort, the DX + drift fix. Spans 1 root pyproject.toml edit + 1 mypy.ini edit + 1 NEW drift detector + 8 tests. Independent.
3. **Plan 061** (alembic + workspace) — S effort, the lowest-leverage (forward-compat for future migrations + dev-experience). Spans 1 env.py edit + 1 apps/api/pyproject.toml edit + 1 root pyproject.toml edit + 7 tests. Independent.

All 3 are independent. Could ship in any order. The recommended order is by leverage (HIGH-LOW bug fix > DX dedup > forward-compat).

### Dependency graph (v0.9.19)

```
  plan 059 ─── INDEPENDENT ──── (apps/api/pyproject.toml + test_pyproject_toml.py)
  plan 060 ─── INDEPENDENT ──── (pyproject.toml + mypy.ini + scripts/check_pyproject_drift.py + tests)
  plan 061 ─── INDEPENDENT ──── (apps/api/alembic/env.py + apps/api/pyproject.toml + pyproject.toml + tests)
```

No shared file paths across the 3 plans (each touches a different set of files). Could be PR'd in parallel by 3 different engineers.

### Considered and rejected (v0.9.19)

- **Plan 059 alternative: sort the list by purpose (web framework, ORM, MCP, storage, ...)** : tempting (groups related deps). The alphabetical sort is the canonical Python community convention (per PEP 8 for `__all__` + the pip-tools default); a purpose-based sort is a future customisation.
- **Plan 059 alternative: drop `fastapi-mcp` from `[project].dependencies` and add it to a `mcp` dependency group**: out of scope. The package is a production runtime dep (the `mount()` runs at import time per plan 042's `_build_app()` factory). A future plan can move it to an optional group if the MCP integration becomes opt-in (per plan 042's `ENABLE_MCP` flag).
- **Plan 059 alternative: pin `fastapi-mcp` to an exact version** (e.g., `fastapi-mcp==0.4.2`): out of scope. The `>=0.4` minimum is the canonical "minimum compatible" pin; an exact pin forces every release to bump the dep.
- **Plan 059 alternative: add a CI test that fails on duplicate dep entries**: tempting (prevents future drift). A `toml` parser-based test is a 1-time-write; the canonical pattern is to enforce the rule via a `ruff` custom rule (out of scope -- the v0.9.x audit pass doesn't introduce custom ruff rules).
- **Plan 060 alternative: keep the root blocks but mark them as "legacy / do not use" with a comment**: tempting (preserves history). The dead config is still parsed by tools that don't know to skip it (e.g., a future IDE that merges both configs). Removal is the canonical fix.
- **Plan 060 alternative: move the canonical config INTO root `pyproject.toml`** (delete `ruff.toml` / `mypy.ini` / `pytest.ini`): tempting (single source of truth). The canonical files exist for a reason: `pytest.ini` and `mypy.ini` are the pytest/mypy-native config paths (per their docs), and the pre-commit `mypy` local hook is a self-contained unit that reads `mypy.ini` directly. Centralizing in `pyproject.toml` is a future refactor; the v0.9.19 minimum is to remove the dead blocks.
- **Plan 060 alternative: add a `pre-commit` hook for the drift detector**: the detector runs in CI (the canonical "drift gate" pattern). A pre-commit hook adds local-rerun overhead for a 1-second script; the CI-only placement is sufficient.
- **Plan 060 alternative: use `ruff check --no-cache --config ruff.toml` to detect the dead blocks**: out of scope. The dead blocks are at the TOML level (before ruff even reads them); the drift detector parses `pyproject.toml` with `tomllib` and checks for the keys.
- **Plan 061 alternative: add `compare_type=True` only (not `compare_server_default`)**: tempting (the current migrations don't have `server_default=`). `compare_server_default=True` is needed for future migrations that add a `server_default=` (e.g., the CHECK constraints in plan 029 have `server_default='pending'`). Adding both flags now is the v0.9.19 minimum.
- **Plan 061 alternative: switch `gw2_api_client` to a path dep** (`gw2_api_client = { path = "libs/gw2_api_client" }`): out of scope. The `path` dep is for non-workspace packages; the `workspace = true` source is the canonical pattern for workspace members.
- **Plan 061 alternative: pin `gw2_api_client` to an exact version** (`==0.1.0`) instead of the bare name: out of scope. The workspace source resolves the version from the member's pyproject.toml; an exact pin is redundant.
- **Plan 061 alternative: move `gw2_api_client` to a private index** (e.g., a self-hosted devpi): out of scope. The workspace source is the v0.9.x canonical pattern.
- **Plan 061 alternative: drop the `compare_server_default` flag and rely on the operator's manual review**: out of scope. The flag is the canonical auto-detection mechanism per the alembic docs.

## v0.9.18 audit (closed)

**Author:** senior-advisor audit (improve skill, standard effort) — web/* build/CI/test config + tooling deep pass (the surfaces never audited: Next.js config + vitest + Playwright configs + the .env.example contract + the codegen script + the screenshot script + the package.json deps)
**Stamped at:** `44ea862` (origin/main HEAD at audit time — after the v0.9.17 libs/* public surfaces pass landed: 2 plans 054/055 written + indexed)
**Recon scope:** `web/next.config.ts` + `web/vitest.config.ts` + `web/playwright.config.ts` + `web/.env.example` + `web/scripts/dump_openapi.py` + `web/scripts/screenshots.mjs` + `web/package.json`
**Audit mode:** standard effort; targeted deep pass on the web build/test/tooling config surfaces; 3 findings selected for planning (1 MED security + 2 LOW DX)

### v0.9.18 status table

| # | Plan | Status | Addresses finding | Effort |
|---|---|---|---|---|
| 056 | [056-v0918-nextjs-config-hardening](./056-v0918-nextjs-config-hardening.md) | **pending** (the 3-line placeholder `{ /* config options here */ }` is replaced with the canonical Next.js 16 production config: `poweredByHeader: false` (drops the `X-Powered-By: Next.js` info-leak), `compress: true` (explicit bandwidth), `output: "standalone"` (Docker forward-compat — the canonical Next.js 16 build output that copies only the required `node_modules` subset), `images.remotePatterns: []` (forward-compat for `<Image>` from external URLs), `eslint.ignoreDuringBuilds: false` (build must not skip lint), `typescript.ignoreBuildErrors: false` (build must not skip TS), and the `async headers()` function returning the 4 canonical stateless security headers — HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy — as a belt-and-braces second line of defence behind the Caddy reverse proxy from plan 027; CSP + Permissions-Policy stay in Caddy because they need per-request nonces the Next.js `headers()` function cannot inject; 7 NEW hermetic tests cover the 7 hardening surfaces + a sync test that asserts the Next.js `headers()` values match the Caddy config) | #1 `web/next.config.ts` is a 3-line placeholder `{ /* config options here */ }` — `poweredByHeader` defaults to true (info-leak), `compress` is implicit, `output` is undefined (no Docker-friendly standalone build), `images.remotePatterns` is empty, `headers()` function absent; the Caddy layer from plan 027 is the primary defence but Next.js-level defaults leak framework version + lack a Docker-friendly build output (security + prod-readiness, MED) | S |
| 057 | [057-v0918-env-contract-env-example](./057-v0918-env-contract-env-example.md) | **pending** (`web/.env.example` rewritten to document the full env contract: the `API_BASE_URL` section with local-dev + production examples, the `NODE_ENV` semantics ("set by Next.js automatically; do not override"), the optional `NEXT_PUBLIC_API_BASE_URL` client-side alias (per plan 033), the production fail-fast contract (per plan 033's `_resolveApiBaseUrl`), and a `[TEMPLATE]` header line to distinguish the template from the per-developer `web/.env.local` (gitignored); the `?tz=` per-request param is noted as out-of-env-scope; 5 NEW hermetic tests assert the 5 contract surfaces are present) | #2 `web/.env.example` only documents `API_BASE_URL` — the production fail-fast contract (plan 033) + the `NEXT_PUBLIC_API_BASE_URL` client-side alias (plan 033) + the `NODE_ENV` semantics are all undocumented; an operator copying the template verbatim into production sees no warning that a missing `API_BASE_URL` in production crashes the app at boot (DX, LOW) | S |
| 058 | [058-v0918-web-scripts-dx](./058-v0918-web-scripts-dx.md) | **pending** (`web/scripts/dump_openapi.py`: the hard-coded `_REQUIRED_ENV` tuple is augmented with a runtime introspection check that WARNS (does NOT auto-sync) on drift between the static list and `Settings.model_fields`'s required fields; the warning includes the diff (sorted static list vs sorted runtime list) and points to the line to update; `web/scripts/screenshots.mjs`: `chromium.launch({ headless: true })` gains `args: ["--no-sandbox"]` for the canonical CI container environments (older GitHub Actions runners, the project's own Playwright Docker image); 4 NEW hermetic tests cover: tuple matches Settings at import time, warning fires on drift (monkeypatched), `--no-sandbox` is passed to chromium (subprocess capture), `mkdir(DOCS_DIR, { recursive: true })` runs even if the directory is missing) | #3 `web/scripts/dump_openapi.py::_REQUIRED_ENV` is a hard-coded tuple that must be manually kept in sync with `Settings` required fields (drift = silent codegen break in CI); `web/scripts/screenshots.mjs::chromium.launch` does not pass `args: ["--no-sandbox"]` (the canonical workaround for running chromium as root in containers — older GitHub Actions runners + the project's own Playwright Docker image need it) (DX + reliability, LOW) | S |

### Recommended execution order (v0.9.18)

1. **Plan 057** (env contract) — S effort, the smallest + highest-clarity win. Self-contained (1 .env.example rewrite + 5 tests). Independent of 056/058.
2. **Plan 058** (web/scripts DX) — S effort, the codegen + CI portability fix. Self-contained (1 dump_openapi.py edit + 1 screenshots.mjs edit + 4 tests). Independent.
3. **Plan 056** (Next.js config) — S effort, the highest-leverage single fix (the security + Docker-forward-compat win). Spans 1 next.config.ts edit + 7 tests. Independent.

All 3 are independent. Could ship in any order. The recommended order is by surface (documentation first, then tooling, then framework config).

### Dependency graph (v0.9.18)

```
  plan 057 ─── INDEPENDENT ──── (web/.env.example + tests)
  plan 058 ─── INDEPENDENT ──── (web/scripts/dump_openapi.py + web/scripts/screenshots.mjs + tests)
  plan 056 ─── INDEPENDENT ──── (web/next.config.ts + tests)
```

No shared file paths. Could be PR'd in parallel by 3 different engineers.

### Considered and rejected (v0.9.18)

- **Plan 056 alternative: set all 7+ security headers in Next.js (HSTS + CSP + X-Frame-Options + X-Content-Type-Options + Referrer-Policy + Permissions-Policy + COOP/COEP)**: tempting (defence-in-depth on every header). The CSP header requires per-request nonces for `script-src` which the Next.js `headers()` async function does not have access to. Caddy is the only layer that can inject the nonce. The 4 "stateless" headers (HSTS + X-Frame-Options + X-Content-Type-Options + Referrer-Policy) are safe to duplicate in Next.js.
- **Plan 056 alternative: drop the Next.js `headers()` function (rely on Caddy alone)**: tempting (less duplication). A self-hosted deployment without Caddy (e.g., a Cloudflare worker in front of Next.js) loses the canonical 4 headers. The duplication is the canonical defence-in-depth pattern.
- **Plan 056 alternative: use `experimental.serverActions.allowedOrigins` for Server Actions CSRF**: out of scope. The current pages don't use Server Actions (all data fetching is via the FastAPI gateway + AG Grid client-side calls). A future plan can add the config when Server Actions are introduced.
- **Plan 056 alternative: use Next.js's `middleware.ts` to inject headers**: tempting (more flexible). But `middleware.ts` runs on every request (a performance cost); the `headers()` function in `next.config.ts` is the canonical performance-friendly path.
- **Plan 057 alternative: add a runtime check that `.env.local` was generated from `.env.example`**: out of scope. The `.env.local` is the canonical "local override" file; its content is per-developer, not a contract.
- **Plan 057 alternative: add a `web/.env.production` (committed) with the production defaults**: tempting (defines the production contract in the repo). But the production values are operator-specific (the production domain + the cert paths); a committed file would either be a template (same as `.env.example`) or a leak (committed real values). The current `.env.example` is the canonical template.
- **Plan 057 alternative: move the contract to a `web/docs/env.md`**: out of scope. The README's `## Quick start` section + `.env.example` itself is the canonical discovery path for the env contract. A separate doc adds a discovery step.
- **Plan 057 alternative: generate `.env.example` from a Zod schema at build time**: over-engineered. The `.env.example` is a 30-line file maintained by hand; a Zod schema would add a build-time dep for a 1-time-per-release update.
- **Plan 058 alternative: auto-sync `_REQUIRED_ENV` from `Settings.model_fields`** (no warning, no static list): tempting (the script becomes self-maintaining). But the operator who adds a new required field to `Settings` should also update the script's static list (for documentation purposes); the auto-sync would silently change behaviour. The warning approach is the canonical "detect drift" pattern.
- **Plan 058 alternative: move the `_REQUIRED_ENV` list to a shared `apps/api/scripts/_ci_env.py` module**: out of scope. The list is a codegen-script concern, not a production-runtime concern. A shared module would create a false sense of "single source of truth" (the runtime Settings and the codegen script have different requirements).
- **Plan 058 alternative: use `pydantic-settings` to declare the env vars in a shared schema**: out of scope. `pydantic-settings` is what `Settings` already uses; the codegen script's `_REQUIRED_ENV` is a subset of the schema's required fields, maintained manually.
- **Plan 058 alternative: drop the `chromium.launch` `--no-sandbox` change** (rely on the operator's CI environment): tempting (don't add a security trade-off). But the `--no-sandbox` is required for the canonical CI environments (older GitHub Actions runners, the project's own Playwright Docker image). The plan ships the change.
- **Plan 058 alternative: use `puppeteer` instead of `playwright`**: out of scope. The project standardizes on `playwright` (per `web/package.json`'s `@playwright/test` dep); the script's choice of `chromium` from `@playwright/test` is consistent.
- **Plan 058 alternative: add a `--screenshot-dir=` flag to the script**: out of scope. The hard-coded `OUT_DIR` anchors to the repo root (per the script's invariant comment); an env-var override would break the README-discovery invariant.

## v0.9.17 audit (closed)

**Author:** senior-advisor audit (improve skill, standard effort) — `libs/*` deep pass on the surfaces not covered by v0.9.6 (the 9 sibling aggregators) or v0.9.11 (gw2_core models + gw2_api_client): `aggregate.py` orchestrator + 3 `__init__.py` public surfaces + `interface.py` Protocol + 2 `exceptions.py` files
**Stamped at:** `44ea862` (origin/main HEAD at audit time — after the v0.9.16 models + schemas + workers pass landed: 3 plans 051/052/053 written + indexed)
**Recon scope:** `libs/gw2_analytics/src/gw2_analytics/aggregate.py` + `libs/gw2_analytics/src/gw2_analytics/__init__.py` + `libs/gw2_evtc_parser/src/gw2_evtc_parser/interface.py` + `libs/gw2_evtc_parser/src/gw2_evtc_parser/exceptions.py` + `libs/gw2_evtc_parser/src/gw2_evtc_parser/__init__.py` + `libs/gw2_core/src/gw2_core/__init__.py`
**Audit mode:** standard effort; targeted deep pass on the library public surfaces + the `aggregate.py` orchestrator; 2 findings selected for planning (1 LOW DX + 1 LOW perf)

### v0.9.17 status table

| # | Plan | Status | Addresses finding | Effort |
|---|---|---|---|---|
| 054 | [054-v0917-library-version-from-importlib-metadata](./054-v0917-library-version-from-importlib-metadata.md) | **pending** (3 `__init__.py` files (`gw2_core` + `gw2_analytics` + `gw2_evtc_parser`) replace the hard-coded `__version__ = "X.Y.Z"` literal with `importlib.metadata.version("<dist-name>")` wrapped in a `try/except PackageNotFoundError` that falls back to the PEP 440 sentinel `"0.0.0+unknown"` for editable-mode installs; bundles the `EVENT_SIZE` re-export cleanup in `gw2_evtc_parser/__init__.py` (the parser-internal constant is removed from `__all__` + from the `from .parser import ...` line, but stays accessible to the parser internals via the fully-qualified `from gw2_evtc_parser.parser import EVENT_SIZE` path); 7 NEW hermetic tests in a new `libs/_versions_test/` shim assert: each `__version__` equals `importlib.metadata.version(...)`, the fallback is the sentinel, `EVENT_SIZE` is not in `gw2_evtc_parser.__all__`, `EVENT_SIZE` is not in the `gw2_evtc_parser` namespace, `EVENT_SIZE` is still importable via the qualified path) | #1 All 3 `libs/*/__init__.py` files hard-code `__version__` as a string literal that drifts from `pyproject.toml` on every release; `EVENT_SIZE` (a parser-internal struct-size constant) is re-exported in `__all__` and leaks the parser's internal struct shape to downstream consumers (DX + forensics, LOW) | S |
| 055 | [055-v0917-aggregator-invariant-check-opt-in](./055-v0917-aggregator-invariant-check-opt-in.md) | **pending** (NEW `AggregatorSettings(BaseModel)` in `apps/api/src/gw2analytics_api/config.py` with `validate_invariants: bool = False` (prod-safe default); `SingleFightAggregator.__init__` gains an optional `settings: AggregatorSettings \| None = None` parameter; `aggregate()` end-of-method becomes `if self._settings is not None and self._settings.validate_invariants: self._check_invariants(aggregate); return aggregate`; `routes/fights.py::get_fight_events` plumbs the flag from `Settings.aggregator.validate_invariants`; `apps/api/.env.example` documents the new env var; the library's default is OFF (no settings → no check), CI runs with the flag ON; 5 NEW hermetic tests in `libs/gw2_analytics/tests/test_aggregate.py` + 1 route plumbing test) | #2 `SingleFightAggregator.aggregate` calls `_check_invariants(aggregate)` unconditionally on every invocation -- the O(groups × combatants) `GroupSummary` consistency walk is on the production hot path even though the invariants are constructed by the aggregator itself (the only way to violate them is a programming bug, which CI catches) (perf, LOW) | S |

### Recommended execution order (v0.9.17)

1. **Plan 054** (library versions) — S effort, the highest-leverage DX fix. 1 file each across 3 `libs/*` packages + 1 `EVENT_SIZE` cleanup + 7 tests. Independent of 055.
2. **Plan 055** (invariant check opt-in) — S effort, the LOW perf fix. Touches `aggregate.py` + `config.py` + `routes/fights.py` + `.env.example` + 6 NEW tests. Independent of 054.

All 2 are independent. Could ship in any order. The recommended order is by surface (3 library files first, then the API + library integration).

### Dependency graph (v0.9.17)

```
  plan 054 ─── INDEPENDENT ──── (libs/{gw2_core,gw2_analytics,gw2_evtc_parser}/__init__.py + tests)
  plan 055 ─── INDEPENDENT ──── (libs/gw2_analytics/aggregate.py + apps/api/src/gw2analytics_api/{config.py,routes/fights.py} + .env.example + tests)
```

No shared file paths. Could be PR'd in parallel by 2 different engineers.

### Considered and rejected (v0.9.17)

- **Plan 054 alternative: drop `__version__` entirely from the 3 packages**: the library consumers (apps/api in `services.py`, future external integrators) use `__version__` for forensic logging. PEP 396 is informational, not mandatory, but the pattern is canonical in the Python ecosystem.
- **Plan 054 alternative: read the version from `pyproject.toml` at import time via `tomllib`**: requires `pyproject.toml` to be in the import path (it isn't at runtime) + adds a `tomllib` dep (Python 3.11+). `importlib.metadata` is the canonical, no-dep pattern.
- **Plan 054 alternative: bundle the version into a single `_version.py` file**: a PEP 440-compliant single-source-of-truth pattern but requires the build system (`hatch` / `setuptools-scm`) to write the file at build time. The current `pyproject.toml` is plain static-version (no `dynamic = ["version"]`); the `importlib.metadata.version()` approach is the v0.9.17 minimum.
- **Plan 054 alternative: keep `EVENT_SIZE` in `__all__` with a `# public-API` docstring**: the constant is genuinely internal; documenting it as public doesn't change the implementation coupling. The plan drops it from the re-export.
- **Plan 054 alternative: add `EVENT_SIZE` to a new `gw2_evtc_parser._internals` submodule**: the parser already has full access via the qualified import. Adding a new submodule is over-engineering for a 1-line cleanup.
- **Plan 055 alternative: run the check always but use a `Counter` for O(1) per-group lookup**: keeps the check on the hot path. The cost of the check is not the bottleneck (the O(N×M) walk is fast for N=100); the value of the check is dev-time. Opt-in is the right tradeoff.
- **Plan 055 alternative: run the check only in `__debug__` mode** (Python's `-O` flag): tempting (the check is a dev-time guard). But the `__debug__` flag is global; the operator can't enable the check for a single endpoint. The per-aggregator `settings` flag is more granular.
- **Plan 055 alternative: make the check a `@staticmethod` and require callers to call it explicitly after `aggregate()`**: too easy to forget; the opt-in flag ensures the check is consistent across callers.
- **Plan 055 alternative: move the check to the consumer (route layer)**: the route layer doesn't have visibility into the invariant semantics; the check belongs with the writer.
- **Plan 055 alternative: drop the check entirely**: the check is cheap on the dev-time path; removing it loses the safety net. The opt-in flag preserves the net for dev/CI.
- **Plan 055 alternative: add a `validate_invariants: bool = True` keyword arg to `aggregate()` (not the constructor)**: a per-call flag is too easy to forget on a per-call site; the constructor flag is set once per `SingleFightAggregator` instance.
- **Rename `npc_count` to `non_player_count` in `FightAggregate`**: the field includes both true NPCs AND `is_player=True` rows with `account_name=None` (per the documented design). Renaming is more honest but is API-breaking. Tracked as a v0.10+ additive field with a deprecation note on `npc_count`.
- **Drop the `npc_count` semantic + filter accountless players to `untracked_count`**: same as above, additive, deferred to v0.10.

## v0.9.16 audit (closed)

**Author:** senior-advisor audit (improve skill, standard effort) — `apps/api/src/gw2analytics_api/{models,schemas,workers}/*.py` deep pass (the 3 `apps/api/*` surfaces never audited: ORM data layer, Pydantic API contract, webhook dispatch + retry workers)
**Stamped at:** `44ea862` (origin/main HEAD at audit time — after the v0.9.15 routes/* pass landed: 3 plans 048/049/050 written + indexed)
**Recon scope:** `apps/api/src/gw2analytics_api/models.py` + `apps/api/src/gw2analytics_api/schemas.py` + `apps/api/src/gw2analytics_api/workers/__init__.py` + `apps/api/src/gw2analytics_api/workers/webhook_dispatch.py` + `apps/api/src/gw2analytics_api/workers/webhook_scheduler.py` + `apps/api/src/gw2analytics_api/main.py` (for the lifespan shutdown hook)
**Audit mode:** standard effort; targeted deep pass on the data + wire + worker surfaces; 3 findings selected for planning (2 MED perf + 1 LOW DX)

### v0.9.16 status table

| # | Plan | Status | Addresses finding | Effort |
|---|---|---|---|---|
| 051 | [051-v0916-webhook-dispatch-fan-out](./051-v0916-webhook-dispatch-fan-out.md) | **pending** (NEW module-level `_DISPATCH_MAX_WORKERS = 4` constant + NEW private `_fire_post(client, url, body, headers) -> dict[str, object]` pure-network worker (NO SQLAlchemy access — main thread retains sole ownership of the `Session` to avoid `db.add()` UoW races, per thinker refinement rejecting shared-Session + per-thread-Session options); the per-sub `for sub in active_subs` loop is wrapped in `concurrent.futures.ThreadPoolExecutor(max_workers=_DISPATCH_MAX_WORKERS)`; the main thread pre-computes the `delivery_id` + signature + headers + collects `concurrent.futures.as_completed(futures)` outcomes + builds the `OrmWebhookDelivery` rows in the main thread + does the single atomic `db.commit()`; the `httpx.Client` is the post-plan-052 module-level singleton (thread-safe per `httpx` 0.27+ docs); 6 NEW hermetic tests in `apps/api/tests/test_webhooks_e2e_dispatch.py` cover the 6 scenarios: fan-out uses ThreadPoolExecutor, all-success atomic commit (1 commit for N deliveries), partial failure (2 of 4 succeed), worker exception triggers rollback, fire_post returns outcome dict, N=10 bounded) | #1 `webhook_dispatch.dispatch_for_upload` serially POSTs N subscriptions with a single `httpx.Client` -- for N=20 subs × 10s timeout = 200s blocking the FastAPI `BackgroundTasks` slot; a 10s timeout is a design contract (cannot shorten), so wall-clock reduction requires parallel POSTs (perf, MED) | S |
| 052 | [052-v0916-shared-httpx-client-constants](./052-v0916-shared-httpx-client-constants.md) | **pending** (NEW `apps/api/src/gw2analytics_api/workers/_pool.py` module houses the module-level `_shared_client: httpx.Client \| None` singleton + `get_shared_client()` lazy-init helper guarded by `threading.Lock` + `async close_shared_client()` for lifespan shutdown; the 3 cross-worker constants (`REQUEST_TIMEOUT_S = 10.0` + canonical `USER_AGENT = "Gw2Analytics-Webhook/0.9.1"` + `utcnow()` helper) are hoisted to `_pool.py`; `webhook_dispatch.py` + `webhook_scheduler.py` drop their local `with httpx.Client(...)` blocks + the duplicated `_utcnow` / `_REQUEST_TIMEOUT_S` / `_USER_AGENT` constants; `models.py` drops its local `_utcnow`; `main.py` lifespan shutdown gains `await close_shared_client()`; `workers/__init__.py` re-exports the 3 symbols for test monkeypatching; 6 NEW hermetic tests in NEW `apps/api/tests/test_workers_pool.py` cover: singleton identity, idempotent close, client is_closed after close, dispatch uses shared client, scheduler uses shared client, models.utcnow is _pool.utcnow) | #2 `webhook_dispatch.py` + `webhook_scheduler.py` both create fresh `httpx.Client()` per call (per-upload dispatch, per-5s-tick scheduler) — connection-pool thrash on busy installations; the same `_utcnow()` is duplicated in `models.py` + `webhook_dispatch.py` + `webhook_scheduler.py` (3 copies) (perf + DX, LOW-MED) | S |
| 053 | [053-v0916-upload-parser-version-default](./053-v0916-upload-parser-version-default.md) | **pending** (NEW module-level `_resolve_parser_version() -> str` helper in `models.py` that uses `importlib.metadata.version("gw2_analytics")` (the parser library, NOT the API package) to get the canonical version; `@functools.lru_cache(maxsize=1)` wraps the helper to avoid the 5-10 ms pkg_resources scan per upload; `Upload.parser_version` default switched from `"0"` magic literal to the new helper; `PackageNotFoundError` fallback to the string `"unknown"` with a one-time WARNING log so the operator notices editable-mode deployments; 4 NEW hermetic tests cover: default is package version, fallback on missing package, cache hit on second call, explicit-value preservation) | #3 `Upload.parser_version` defaults to the magic literal `"0"` — every row in the table surfaces as `"0"` regardless of which `gw2_evtc_parser` build wrote it; the column is supposed to support re-parse decisions + operator forensics (DX + forensics, LOW) | S |

### Recommended execution order (v0.9.16)

1. **Plan 052** (shared httpx.Client + constants) — S effort, the foundational change. Plan 051's `ThreadPoolExecutor` reuses the `_shared_client` singleton from plan 052. **MUST ship first** (plan 051 documents the dependency).
2. **Plan 051** (webhook dispatch fan-out) — S effort, the highest-leverage perf win. 200s BG-task block for N=20 subs collapses to ~50s (4× parallel). Depends on plan 052.
3. **Plan 053** (parser_version default) — S effort, the lowest-leverage DX fix. Self-contained. Independent of 051/052.

### Dependency graph (v0.9.16)

```
  plan 052 ──▶ plan 051                 (052 = module-level httpx.Client singleton; 051 = ThreadPoolExecutor that reuses it)
  plan 053 ─── INDEPENDENT ──── (models.py + test_models.py)
```

Plan 052 must land first. Plans 052 + 051 should be PR'd sequentially in the same release branch (the dispatcher diff is minimal once the singleton is in place). Plan 053 is independent and can be PR'd in parallel with either.

### Considered and rejected (v0.9.16)

- **Share the `Session` across worker threads in plan 051**: tempting (one less layer of complexity). `db.add()` is NOT thread-safe (SQLAlchemy 2.0's Unit-of-Work mutates internal `_new` / `_dirty` / `_deleted` dicts without locks); concurrent `db.add()` from 4 worker threads corrupts the identity map and produces nondeterministic INSERTs. Rejected by the thinker refinement.
- **Per-thread `Session` in plan 051 with manual flush per worker**: cleaner SQLAlchemy story but breaks the per-upload atomic-commit semantic — 2 of 4 threads succeeding would force the main thread to either commit both (losing atomicity) or roll back the successes (over-rolling back). The "network-only workers + main-thread atomic commit" design preserves the canonical atomicity invariant. Rejected by the thinker refinement.
- **`asyncio.gather` + `httpx.AsyncClient` for plan 051**: would require making `dispatch_for_upload` async, which propagates to the FastAPI `BackgroundTasks` registration site (sync `BackgroundTasks.add_task(dispatch_for_upload, ...)`). Adding `asyncio.to_thread` at the registration site adds a second concurrency layer for marginal benefit. Rejected.
- **Cap `_DISPATCH_MAX_WORKERS` at 8 instead of 4**: doubles the wall-clock improvement but doubles the `httpcore.RLock` contention. 4 is the sweet spot for typical N=10-50 fan-out. The `Settings` field allows operator tuning without a code change. Rejected as a default.
- **Module-level `lru_cache(maxsize=1)` on `get_shared_client()`**: works but the closure + lazy-init `threading.Lock` are easier to reason about with a module-level `None` sentinel + an explicit `threading.Lock`. The pattern is the canonical Python singleton idiom. Rejected.
- **Per-call `httpx.Client` (status quo)**: leaves the connection pool thrash + the duplicated `_utcnow` in place. Rejected.
- **Hard-code `parser_version="0.9.6"` in the model**: drifts on every release; the next release forgets to bump it. Rejected.
- **Read `parser_version` from `os.environ.get("GW2_ANALYTICS_PARSER_VERSION")`**: adds a deployment-time config knob; the version is intrinsic to the installed package, not to the deployment. Rejected.
- **Backfill the historical `parser_version="0"` rows** (UPDATE all to the current version): lies about history (the historical rows were parsed by older versions; we don't know which). The additive-migration approach (new rows use the package version, historical rows keep `"0"`) is honest. Rejected.
- **Drop the `parser_version` column**: the plan-015 re-parse logic uses `parser_version != current_version` as the trigger; dropping the column would force a full-table scan for the re-parse gate. Rejected.

## v0.9.15 audit (closed)

**Author:** senior-advisor audit (improve skill, standard effort) — `apps/api/src/gw2analytics_api/routes/*` deep pass (the 5 route modules: ``uploads`` + ``fights`` + ``players`` + ``account`` + ``health`` -- the public API surface never deeply audited in a single pass)
**Stamped at:** `44ea862` (origin/main HEAD at audit time — after the v0.9.14 services.py pass landed: 2 plans 045 + 047 written + indexed)
**Recon scope:** `apps/api/src/gw2analytics_api/routes/uploads.py` + `routes/fights.py` + `routes/players.py` + `routes/account.py` + `routes/health.py`
**Audit mode:** standard effort; targeted deep pass on the route surface (validation gaps, exception handling, const dedup); 3 findings selected for planning (2 MED reliability + 1 LOW DX)

### v0.9.15 status table

| # | Plan | Status | Addresses finding | Effort |
|---|---|---|---|---|
| 048 | [048-v0915-uploads-validation](./048-v0915-uploads-validation.md) | **pending** (2 NEW `Settings` fields: `max_upload_bytes` (default 30 MB, env-overridable via ``MAX_UPLOAD_BYTES``) + ``zevtc_magic_bytes`` (default ``b"PK\\x03\\x04"`` the canonical PKZip local file header signature); ``create_upload`` uses ``UploadFile(..., max_size=settings.max_upload_bytes)`` so FastAPI's request parser raises 413 ``Request Entity Too Large`` BEFORE the file is read into memory + a 4-byte magic-bytes check raises 415 ``Unsupported Media Type`` BEFORE the SHA-256 is computed + the ``OrmUpload`` row is inserted; 3 NEW hermetic tests in `apps/api/tests/test_uploads_e2e.py` cover the 3 validation paths) | #1 `routes/uploads.py::create_upload` calls ``file.file.read()`` with no size cap -- a 1 GB chunked upload OOMs the uvicorn worker; with 8 workers, 8 concurrent uploads halt the entire server (DoS amplification, MED). No MIME / magic bytes check -- a non-zip file (e.g. a ``.txt`` with binary content) is accepted + the SHA-256 is stored + the ``OrmUpload`` row is committed BEFORE the parser rejects it (correctness, LOW) | S |
| 049 | [049-v0915-account-401-exception-attr](./049-v0915-account-401-exception-attr.md) | **pending** (`GuildWars2HttpError.__init__` gains a `status_code: int \| None` keyword argument; the 2 `GuildWars2HttpError` raise sites in ``client.py`` pass the response status code; ``account.py`` dispatches on ``exc.status_code == 401`` (attribute-based) with a string-based fallback (``"401 unauthorized" in str(exc) or "HTTP 401:" in str(exc)``) preserved for backwards compat with callers that raise ``GuildWars2HttpError`` without a status code; 2 NEW hermetic tests: the exception's ``status_code`` attribute is set correctly + the route dispatches to 401 on ``exc.status_code == 401`` regardless of the error message string) | #2 `routes/account.py::get_account_enriched` detects an upstream 401 (invalid API key) by parsing the error message string: ``if "401 unauthorized" in msg or "HTTP 401:" in msg`` -- a future refactor of the gw2_api_client error message format would silently break the 401 detection; a 5xx response whose body happens to contain the literal "401" would also be misrouted (reliability, MED) | S |
| 050 | [050-v0915-fights-dedupe-window-constants](./050-v0915-fights-dedupe-window-constants.md) | **pending** (4 module-level constants removed: ``_TIMELINE_DEFAULT_WINDOW_S`` + ``_TIMELINE_MAX_WINDOW_S`` + ``_EVENTS_DEFAULT_WINDOW_S`` + ``_EVENTS_MAX_WINDOW_S``; replaced with 2 deduped constants: ``_DEFAULT_WINDOW_S = 5`` + ``_MAX_WINDOW_S = 600``; the 2 endpoint signatures (``get_fight_timeline`` + ``get_fight_events``) use the deduped constants; 4 NEW hermetic tests cover the deduped constants + the 2 endpoint usages) | #3 `routes/fights.py` has 4 module-level constants (``_TIMELINE_DEFAULT_WINDOW_S`` + ``_TIMELINE_MAX_WINDOW_S`` + ``_EVENTS_DEFAULT_WINDOW_S`` + ``_EVENTS_MAX_WINDOW_S``) with identical values (5 + 600); the 2 pairs are separated for historical reasons (the timeline endpoint was added in v0.8.9 as a sibling of the events endpoint; the original pair was not refactored to be shared); a future change to the bounds would have to update BOTH pairs to keep them in sync, with subtle inconsistency risk (DX, LOW) | S |

### Recommended execution order (v0.9.15)

1. **Plan 048** (uploads validation) — S effort, the MED DoS fix. Closes the per-upload size cap + MIME check gaps. Self-contained (1 routes/uploads.py + 1 config.py + 1 .env.example + 3 NEW tests). Independent of 049/050.
2. **Plan 049** (account 401 detection) — S effort, the MED reliability fix. Closes the brittle string-dispatch gap. Spans 4 files (libs/gw2_api_client/{exceptions,client}.py + routes/account.py + 2 test files). Independent of 048/050.
3. **Plan 050** (fights dedupe constants) — S effort, the LOW DX fix. Self-contained (1 routes/fights.py + 4 NEW tests). Independent.

All 3 are independent. Could ship in any order. The recommended order is by severity (MED DoS > MED reliability > LOW DX).

### Dependency graph (v0.9.15)

```
  plan 048 ─┐                          (routes/uploads.py + config.py + .env.example + test_uploads_e2e.py)
  plan 049 ─┼── INDEPENDENT ────────── (libs/gw2_api_client/{exceptions,client}.py + routes/account.py + test_account.py + test_client.py)
  plan 050 ─┘                          (routes/fights.py + test_fights.py)
```

No shared file paths across the 3 plans. Could be PR'd in parallel by 3 different engineers.

### Considered and rejected (v0.9.15)

- **Plan 048 alternative: adding per-user rate limiting** (e.g. "1 upload per user per hour"): out of scope -- the ``MAX_UPLOAD_BYTES`` cap is the per-request DoS surface; rate limiting is a v0.9.16+ future enhancement.
- **Plan 048 alternative: streaming the file to MinIO** (avoiding the in-memory ``file.file.read()``): out of scope -- the current MinIO client uses ``BytesIO(data)``; switching to streaming PUT is a larger refactor of ``storage.py``.
- **Plan 048 alternative: adding a ``.zevtc`` extension check on the ``file.filename``**: out of scope -- the web frontend already validates the extension; the API's canonical trust boundary is the content (magic bytes), not the filename.
- **Plan 049 alternative: refactoring the gw2_api_client's error message format**: out of scope -- the message format stays as-is; the canonical addition is the ``status_code`` attribute.
- **Plan 049 alternative: adding a ``status_code`` attribute to ``GuildWars2RateLimitError``**: out of scope -- the rate-limit path is always 429; no need for a per-instance attribute.
- **Plan 049 alternative: removing the string-based dispatch as a defence-in-depth fallback**: out of scope -- the fallback is preserved for backwards compat with callers that raise ``GuildWars2HttpError`` without a ``status_code`` attribute.
- **Plan 050 alternative: changing the canonical bounds**: out of scope -- the plan preserves the existing values (5 + 600) and only deduplicates the constants. A future plan can change the bounds using the deduped constants.
- **Plan 050 alternative: adding a per-endpoint override** (e.g. the timeline endpoint allows 1200, the events endpoint allows 600): out of scope -- the current code uses the same bounds for both endpoints; the per-endpoint override is a future enhancement.

## v0.9.6 audit (deep audit libs+web)

**Author:** senior-advisor audit (improve skill, standard effort) — deep audit of libs/* + web/* (the surfaces explicitly excluded from the v0.9.3 + v0.9.4 + v0.9.5 passes)
**Stamped at:** `44ea862` (origin/main HEAD at audit time — after the v0.9.5 cleanup pass landed: 3 plans 017/018/019 written + indexed)
**Recon scope:** `libs/gw2_core/src/gw2_core/models.py` + `libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py` + `libs/gw2_analytics/src/gw2_analytics/*.py` (target_dps, target_healing, target_buff_removal, event_window, per_fight_timeline, player_profile, squad_rollup, skill_usage, multi_fight, aggregate) + `libs/gw2_api_client/src/gw2_api_client/client.py` + `web/src/lib/api.ts` + `web/src/components/*.tsx` + `web/src/app/**/*.tsx`
**Audit mode:** standard effort; full-scope deep pass on the previously-excluded surfaces; 6 HIGH-confidence findings selected for planning

### v0.9.6 status table

| # | Plan | Status | Addresses finding | Effort |
|---|---|---|---|---|
| 020 | [020-v096-parser-zip-bomb-protection](./020-v096-parser-zip-bomb-protection.md) | **pending** (NEW `_MAX_ZIP_ENTRY_UNCOMPRESSED_SIZE = 500 MB` constant + pre-check via `ZipFile.getinfo(name).file_size` BEFORE `zf.read(name)` in `_first_entry`; defends against zip-bomb DoS where a 42-byte zip header claims a 4 GB uncompressed payload; 1 hermetic test asserts the parser raises before extraction) | #1 `_first_entry` calls `zf.read` with no uncompressed-size pre-check (security, HIGH) | S |
| 021 | [021-v096-per-fight-timeline-iterator-fix](./021-v096-per-fight-timeline-iterator-fix.md) | **pending** (refactor `PerFightTimelineAggregator.aggregate` to pre-compute `expected_damage` / `expected_healing` / `expected_strip` in the first loop + pass them to `_check_invariants` instead of the (drained) iterator; CRITICAL fix — every call site passing a generator currently crashes on the sum-preservation check; 1 hermetic test passes a generator and asserts no `ValueError`) | #2 `PerFightTimelineAggregator` drains the events iterator before `_check_invariants` (correctness, HIGH) | S |
| 022 | [022-v096-multi-fight-attendance-dedup](./022-v096-multi-fight-attendance-dedup.md) | **pending** (add `seen_accounts_this_fight: set[str]` per-fight dedup BEFORE incrementing `player_attendance[acct]`; reconnects / class swaps / squad moves within a single fight now count as ONE attendance not N; 1 hermetic test seeds 2 agents with the same `account_name` in 1 fight + asserts `player_attendance == 1`) | #3 `MultiFightAggregator` double-counts reconnecting players (correctness, HIGH) | S |
| 023 | [023-v096-player-profile-dedup](./023-v096-player-profile-dedup.md) | **pending** (drop the `if key in seen_pairs: continue` early-skip in `PlayerProfileAggregator.aggregate`; always accumulate `total_damage` / `total_healing` / `total_buff_removal`; `attended_fight_ids` set handles dedup via set semantics; 1 hermetic test seeds 2 characters in 1 fight + asserts `total_damage == sum of both contributions`) | #4 `PlayerProfileAggregator` drops damage for multi-character encounters (correctness, HIGH) | S |
| 024 | [024-v096-player-timeline-chart-utc-timezone](./024-v096-player-timeline-chart-utc-timezone.md) | **pending** (add `timeZone: "UTC"` to BOTH `X_AXIS_LABEL_FORMAT` + `X_AXIS_DAY_LABEL_FORMAT` `Intl.DateTimeFormat` calls in `PlayerTimelineChart.tsx`; server (Node) defaults to UTC but client (browser) uses local TZ — without the explicit option, React hydration fires on every page load; 1 vitest test asserts format determinism under non-UTC `process.env.TZ`) | #5 `PlayerTimelineChart` causes React hydration mismatch via `Intl.DateTimeFormat` without explicit `timeZone` (ux + correctness, HIGH) | S |
| 025 | [025-v096-window-size-selector-urlsearchparams](./025-v096-window-size-selector-urlsearchparams.md) | **pending** (refactor `WindowSizeSelector.onChange` to use Next.js `useSearchParams` + `new URLSearchParams(searchParams.toString())` + update only the `window_s` key; preserves any other active query params (e.g. the `?target=123` sub-filter on the fight drilldown); 1 new vitest test asserts the `?target=123` filter survives a `window_s` change) | #6 `WindowSizeSelector` clobbers other URL query params on `window_s` change (ux, HIGH) | S |

### Recommended execution order (v0.9.6)

1. **Plan 020** (zip-bomb protection) — S effort, the security fix. Closes a DoS vector. Self-contained.
2. **Plan 024** + **Plan 025** (web UX fixes) — S effort each, the only 2 web-tier changes. Independent of the libs/* plans.
3. **Plan 021** + **Plan 022** + **Plan 023** (libs/* correctness fixes) — S effort each. Independent of each other; pick any order.

All 6 are independent. Could ship in any order. The recommended order is by tier (security → web UX → libs/* correctness) so a CI run picks up the most-impactful issues first.

### Considered and rejected (v0.9.6)

- **Bundle 021 + 022 + 023 into a single "libs/* correctness" plan**: tempting (all 3 are aggregator correctness fixes in `libs/gw2_analytics/`). The 3 plans are independent at the test fixture level (021 fixes an iterator drain; 022 fixes a per-fight dedup; 023 fixes a per-character dedup); bundling would conflate 3 separate invariants, making any one of them harder to revert if regressed in CI.
- **Plan 020 alternative: streaming zip extraction via `ZipFile.open(name)` + chunked read**: out of scope (the 500 MB bound is sufficient for realistic `.zevtc` files; streaming is a v0.9.7+ concern if the bound ever proves too tight).
- **Plan 021 alternative: cache the events list before the invariant check**: less surgical than passing pre-computed sums; same correctness outcome, more memory.
- **Plan 022 alternative: dedup at the `SingleFightAggregator` layer (per-fight rollup) instead of the multi-fight layer**: tempting (the per-fight aggregator already filters NPCs). The multi-fight layer is the correct place for cross-fight dedup; the per-fight layer doesn't have a "reconnect" concept.
- **Plan 023 alternative: surface `character_count` as a per-profile field**: out of scope (would require a schema change; this plan's minimal fix is the right v0.9.6 step).
- **Plan 024 alternative: lift `timeZone: "UTC"` to a `formatTimeZone: string` prop with default `"UTC"`**: out of scope (the prop would be unused; future plans can add a per-chart TZ preference if a user requests it).
- **Plan 025 alternative: DRY the `new URLSearchParams(searchParams.toString())` pattern into a `useFilteredQueryParam` hook**: tempting (the same pattern likely applies to `ProfessionFilter` + `TargetFilter` + `PlayerSearchBar`). Out of scope here; tracked as a v0.9.7+ plan after the 3 components are audited for the same bug.

## v0.9.5 audit (cleanup pass)

**Author:** senior-advisor audit (improve skill, standard effort) — v0.9.5 cleanup pass on the 3 lowest-leverage deferred v0.9.3 findings
**Stamped at:** `44ea862` (origin/main HEAD at audit time)
**Recon scope:** `apps/api/src/gw2analytics_api/schemas.py` + `apps/api/src/gw2analytics_api/services.py` + `apps/api/src/gw2analytics_api/workers/webhook_dispatch.py` + existing `apps/api/tests/`
**Audit mode:** standard effort; third pass on the 3 lowest-leverage v0.9.3 deferred findings (all 3 selected for planning as bounded cleanup)

### v0.9.5 status table

| # | Plan | Status | Addresses finding | Effort |
|---|---|---|---|---|
| 017 | [017-v095-webhook-delivery-payload-shape](./017-v095-webhook-delivery-payload-shape.md) | **pending** (1-line `WebhookDeliveryOut.payload: bytes | None` schema fix to match post-migration 0008 `LargeBinary` column; closes pre-emptive bug for the future GET-deliveries route; 1 hermetic test guards against regression) | #6 `WebhookDeliveryOut.payload` schema declares `dict` vs column is `bytes` (correctness, LOW) | S |
| 018 | [018-v095-filter-kind-validator](./018-v095-filter-kind-validator.md) | **pending** (NEW `_WEBHOOK_KNOWN_KINDS` frozenset + `_validate_filter_kind` `field_validator` on `WebhookSubscriptionCreate.filter`; closes the dead-on-arrival subscription pattern (201 + secret + never-fires); 3 hermetic tests: known kind accepted, unknown kind 422, missing kind 422) | #7 `WebhookSubscriptionCreate.filter.kind` not validated at creation (correctness, LOW) | S |
| 019 | [019-v095-narrow-persist-event-blob-except](./019-v095-narrow-persist-event-blob-except.md) | **pending** (1-line `except (EvtcParseError, S3Error, OSError, gzip.BadGzipFile, ValidationError)` instead of `except Exception`; programming bugs now surface to `uploads.error_message` + FAILED status; 2 hermetic tests: S3Error swallowed + `AttributeError` propagates) | #10 `_persist_event_blob except Exception` swallows programming bugs (correctness, LOW) | S |

### Recommended execution order (v0.9.5)

1. **Plan 017** (WebhookDeliveryOut payload shape) — S effort, the smallest. 1-line schema fix in `schemas.py`. Independent of 018/019.
2. **Plan 018** (filter.kind validator) — S effort, ~12-line `field_validator` addition. Independent.
3. **Plan 019** (narrow `_persist_event_blob` except) — S effort, 1-line `except` clause change + 1-2 import additions. Independent.

All 3 are independent. Could ship in any order. The recommended order is by file-locality (`schemas.py` for 017+018, then `services.py` for 019), but any order is fine.

### Considered and rejected (v0.9.5)

- **Bundle 017 + 018 into a single webhook-schemas-cleanup plan**: tempting (both touch `schemas.py`). The 2 plans are independent at the test fixture level (017 fixes a contract type; 018 adds a runtime validator); bundling would conflate the contract-fix invariant with the validator invariant, making them harder to revert if regressed in CI.
- **Plan 017 alternative: add a `payload_dict: dict[str, object] | None` field that hydrates from `payload` via `json.loads`**: out of scope (future feature, not cleanup). Documented as an escape hatch in plan 017.
- **Plan 018 alternative: per-key validation of `upload_status` / `fight_result`**: out of scope; the kind-membership check is the v0.9.5 minimum. Future plans can extend `_validate_filter_kind` into `_validate_filter` if the spec locks the contract.
- **Plan 019 alternative: catch + retry the MinIO PUT 3 times before degrading**: out of scope; the best-effort contract is documented; a future plan can add retry inside the try block. The narrowed catch stays narrow either way.

## v0.9.4 audit (perf+security second pass)

**Author:** senior-advisor audit (improve skill, standard effort) — second pass on the deferred v0.9.3 audit findings
**Stamped at:** `44ea862` (origin/main HEAD at audit time — after the v0.9.3 close-out landed: 3 plans 010/011/012 written + indexed; the user requested a follow-up pass on the 7 deferred findings)
**Recon scope:** apps/api routes/* (player + fights + webhooks) + workers/webhook_scheduler.py + tests/test_players.py + tests/test_webhooks_e2e_scheduler.py + tests/test_uploads_e2e.py
**Audit mode:** standard effort; second pass on the 7 deferred v0.9.3 findings (top-4 by leverage selected for planning; 3 lowest-leverage explicitly deferred to v0.9.5)

### v0.9.4 status table

| # | Plan | Status | Addresses finding | Effort |
|---|---|---|---|---|
| 013 | [013-v094-getaddrinfo-timeout](./013-v094-getaddrinfo-timeout.md) | **pending** (NEW module-level `_DNS_EXECUTOR` singleton + `_DNS_RESOLVE_TIMEOUT_S = 2.0` bounds the `getaddrinfo` call in `_resolved_address_is_blocked` via `concurrent.futures.ThreadPoolExecutor` + `.result(timeout=...)`; REJECTS `socket.setdefaulttimeout` (process-global state hazard — per thinker refinement); 3 new tests assert 422 within <0.5 s + no `setdefaulttimeout` mutation; refines the route-level error to use the shared `assert_url_safe_for_dispatch` from plan 010) | #4 `socket.getaddrinfo` in webhook URL validation has no timeout (security+perf, MED) | S |
| 014 | [014-v094-fight-blob-cache](./014-v094-fight-blob-cache.md) | **pending** (NEW `@functools.lru_cache(maxsize=8)` wraps `get_events(blob_uri)` in `routes/fights.py::_load_fight_events`; REJECTS `contextvars.ContextVar` (per-async-task only — does NOT cross requests, per thinker refinement); caches GZIPPED BYTES not parsed events (10x memory savings); 4 new tests assert 1 MinIO GET per `/fights/{id}` 4-endpoint visit, LRU eviction at 9th call, invalidation on new `blob_uri`) | #5 `_load_fight_events` re-downloads the events blob 4× per `/fights/{id}` visit (perf, MED) | S |
| 015 | [015-v094-player-routes-fastpath](./015-v094-player-routes-fastpath.md) | **pending** (refactor `_compute_contributions` to a single SQL `OrmFightPlayerSummary JOIN OrmFight` for `started_at`; drop the per-fight dispatch + the `selectinload(OrmFight.agents)` full-table pre-load; returns `(contributions, fight_id_to_started)` tuple; delete 3 orphan helpers (`_fast_path_fight_ids` + `_contributions_from_summary` + `_contributions_from_blob_walk`); 4 new tests: 3 regression + 1 perf at 1000 fights <100 ms) | #8 `list_players` + `get_player` + `get_player_timeline` all load ALL fights + agents (perf, LOW-MED) | M |
| 016 | [016-v094-webhook-scheduler-parallel](./016-v094-webhook-scheduler-parallel.md) | **pending** (NEW `_attempt_retry_independent` thread-safe worker opens its OWN session via `session_factory` — NEVER share across threads, per plan 012 escaping-by-thread rule; `concurrent.futures.ThreadPoolExecutor(max_workers=min(N, 4))` fans out retry rows; FIFO per-subscription invariant via the OS scheduler (small N=4 + sorted submission); accepts loss of "all N commit atomically"; 2 new tests: 4-retry parallel <0.75 s + per-delivery session isolation) | #9 `process_scheduled_retries` serialises retry POSTs (perf, LOW-MED) | S |

### Still deferred from v0.9.3 (NOT planned in this pass)

The 3 lowest-leverage findings from the original v0.9.3 audit are NOT planned in this pass. Tracked for future cycles:

| # | Finding | Why deferred | Suggested phase |
|---|---|---|---|
| #6 | `WebhookDeliveryOut.payload: dict[str, object]` schema vs `Mapped[bytes]` column (post-migration 0008) | Pre-emptive bug; no GET-deliveries route exposes the field today. 5-line schema type fix in `apps/api/src/gw2analytics_api/schemas.py`; trivial effort; impact 0 today + LOW future. | v0.9.5 cleanup |
| #7 | `WebhookSubscriptionCreate.filter` accepts any `dict[str, object]`; `filter.kind` not validated at creation; integrator can POST `{kind: "anything"}` and dispatcher silently ignores it | Confusing UX but no security impact; documented as the existing dispatcher behavior (`webhook_dispatch.py:178`). 10-line `field_validator` on `WebhookSubscriptionCreate.filter` adding kind-membership check + 422 for unknown kinds. | v0.9.5 cleanup |
| #10 | `_persist_event_blob`'s `except Exception` swallows programming bugs | Documented in `services.py` docstring as the canonical best-effort contract. 5-line narrowing of the catch to `(EvtcParseError, S3Error, OSError, TypeError)` would surface real bugs while keeping the best-effort contract. LOW impact; operator must monitor `logger.exception`. | v0.9.5 cleanup |

### Recommended execution order (v0.9.4)

1. **Plan 013** (getaddrinfo timeout) — S effort, the highest-leverage single fix. Closes the route-thread-starvation vector. Self-contained. Independent of 014/015/016.
2. **Plan 014** (fight blob cache) — S effort, the second perf+simplicity win. `lru_cache(maxsize=8)` is a 5-line change. Self-contained. Independent.
3. **Plan 015** (player routes fast-path) — M effort, the biggest perf refactor. Drops the full-table pre-load + 3 orphan helpers. Requires care for the `fight_id_to_started` tuple-return signature change.
4. **Plan 016** (parallel webhook retries) — S effort, the same pattern as plan 012. Self-contained. Independent.

There are NO inter-plan dependencies across 013-016. All 4 are independent and could ship in any order. The recommended order is by leverage (security > perf > perf > perf).

### Considered and rejected (v0.9.4)

- **Bundle 014 + 015 into one plan (player+fight read perf)**: tempting (both touch player/fight query paths). The two plans are independent at the test fixture level (014 caches the blob; 015 refactors the player query); bundling would conflate the blob-cache invariant with the SQL-refactor invariant, making them harder to revert if regressed.
- **Plan 013 alternative: switch the route to `async def` + `asyncio.wait_for`**: tempting (single-thread async is the canonical FastAPI pattern) but the route is sync; converting to async would force the entire `routes/webhooks.py` module to async. Out of scope per the v0.9.2 hardening posture (sync-FastAPI is the production contract).
- **Plan 014 alternative: `cachetools.LRUCache` instead of `functools.lru_cache`**: `cachetools` is an extra dep. The 5-line `lru_cache` is sufficient; strict maxsize + LRU semantics are already what `cachetools` would give.
- **Plan 015 alternative: keep `_contributions_from_blob_walk` for pre-v0.8.4 fights**: the v0.8.5 backfill + v0.8.6 health probe already ensure production is all post-v0.8.4. Keeping the fallback for 1 cycle (under `if False:`) is a safety net; full deletion in v0.9.5.
- **Plan 016 alternative: `asyncio.gather` + async SQLAlchemy**: same reasoning as plan 012 — the async-pivot is deferred to a future cycle.

## v0.9.3 audit (top-3 selected)

**Author:** senior-advisor audit (improve skill, standard effort) — top-3 by leverage selected by maintainer
**Stamped at:** `44ea862` (origin/main HEAD at audit time — after the v0.9.2 hardening cycle fully closed: 5 atomic commits per the `009 plan` + CHANGELOG `[0.9.2]` close-out + `d70c8c6` tagging deferred per the README `**Status:**` note).
**Recon scope:** README + CHANGELOG + plans/001-009 + apps/api routes/webhooks.py + workers/webhook_dispatch.py + workers/webhook_scheduler.py + config.py + main.py + databases.py + pyproject.toml + apps/api/tests/test_webhooks_e2e.py
**Audit mode:** standard effort (correctness + security + perf + DX focus); full-repo coverage of the apps/api critical path

### v0.9.3 status table

| # | Plan | Status | Addresses finding | Effort |
|---|---|---|---|---|
| 010 | [010-v093-ssrf-dispatch-re-resolve](./010-v093-ssrf-dispatch-re-resolve.md) | **pending** (NEW `apps/api/src/gw2analytics_api/_webhook_security.py` module houses `_resolved_address_kind` + `WebhookUrlBlockedError` + `assert_url_safe_for_dispatch`; call sites rewired in `webhook_dispatch.py::_dispatch_single` AND `webhook_scheduler.py::_attempt_retry` BEFORE the outbound POST; 3 new rebind regression tests in NEW `test_webhooks_e2e_resolve.py`; honors the existing `GW2ANALYTICS_ALLOW_PRIVATE_WEBHOOK_URLS` opt-out; maintenance note flags the residual 1-50 ms TOCTOU window + the canonical network-level egress-filter defense (out of scope for this plan)) | #1 SSRF DNS rebind between create + dispatch (security, HIGH) — `_validate_webhook_url` ran ONCE at `POST /api/v1/webhooks`; dispatchers POST without re-resolving | S |
| 011 | [011-v093-cors-default-secure](./011-v093-cors-default-secure.md) | **pending** (NEW `Settings.env: Literal["dev", "staging", "production"]` field + `@model_validator(mode="after")` rejects `cors_allowed_origins == ["*"]` when `env != "dev"`; fail-fast `pydantic.ValidationError` at app startup with a clear remediation message; `[tool.pytest_env]` injects `ENV = "dev"` so existing tests stay green; 5 new config tests; `apps/api/.env.example` adds `ENV=production` + a comment block) | #2 `cors_allowed_origins` defaults to `["*"]` if `.env.example` copied verbatim + deployed without overrides (security, HIGH) | S |
| 012 | [012-v093-webhook-dispatch-parallel](./012-v093-webhook-dispatch-parallel.md) | **pending** (`concurrent.futures.ThreadPoolExecutor(max_workers=min(N_subs, 8))` fans out N=min(N, 8) concurrent sub-tasks; per-sub session opened INSIDE each worker via `session_factory` (sessions NOT thread-safe at psycopg driver level — per thinker refinement); plain dicts cross the thread boundary (NO ORM instances ever); 4 new parallel-dispatch tests in NEW `test_webhooks_dispatch_e2e.py`; accepts loss of "all N commit atomically" — each delivery row is independent; trades N×10 s worst-case wallclock for ≈10 s + a tiny startup tax) | #3 webhook dispatcher serialises N outbound POSTs (perf, MED) — `for sub in active_subs: _dispatch_single(...)` blocks 10 s per slow subscriber | M |

### Recommended execution order (v0.9.3)

1. **Plan 010** (SSRF DNS rebind on dispatch) — S effort, the highest-leverage single fix. Closes a CVSS-class SSRF hot path. Self-contained (1 NEW module + 3 test additions). Independent of 011 + 012.
2. **Plan 011** (CORS default secured) — S effort, the second security fix. Cross-field check via `@model_validator(mode="after")` (Pydantic v2 idiom; per the senior-advisor thinker refinement — `@field_validator` has no access to the *parsed* `env` field). Self-contained (1 new field + 1 validator + 5 tests + 1 .env addition). Independent.
3. **Plan 012** (webhook dispatch parallelised) — M effort, the perf improvement. ThreadPoolExecutor + per-thread session (CRITICAL: sessions NOT safe across threads; per the thinker refinement — open `with session_factory() as db:` INSIDE the worker). Self-contained (1 file refactor + 1 NEW test module + delete-orphan `_dispatch_single`). Independent.

There are NO inter-plan dependencies across 010/011/012. All 3 are independent and could ship in any order. The recommended order is by highest leverage (security > security > perf).

### Considered and rejected (v0.9.3)

- **Bundle 010 + 012 into one module**: tempting (both touch `_dispatch_single`). The two plans are independent at the test fixture level (010 adds a resolve-block check; 012 fans out the loop); bundling would conflate the SSRF-defense invariant with the perf invariant, making them harder to revert if regressed in CI. Keep separate.
- **Per-sub `httpx.AsyncClient` instead of `ThreadPoolExecutor`** in plan 012: would require migrating `session_factory` to async SQLAlchemy. Out of scope per the v0.9.2 hardening posture (sync-SQLA is the production contract); revisit when asyncpg lands.
- **Plan 010 alternative: pin to a specific pre-resolved IP via custom `httpx` transport** (`httpx.Client(transport=httpx.HTTPTransport(local_address=PinnedIP))`): airtight against TOCTOU but requires re-writing the entire dispatch's transport plumbing. The plan picks the simpler "re-resolve immediately before POST" + maintenance-note caveat because the airtight variant clobbers the existing 22-test contract.
- **Plan 011 alternative: separate `cors_safe_mode: bool` field**: redundant with the existing `env: Literal["dev", "staging", "production"]` discrimination. Adds a 2nd config dial where one already exists.
- **Plan 012 alternative: switch to `asyncio.gather` + async SQLAlchemy**: requires migrating `database.py`'s engine + the worker module. Defers the delivery perf win until a larger async-pivot cycle.

## v0.9.0 audit (closed)

**Author:** senior-advisor audit (improve skill, `next` invocation, `quick` effort)
**Stamped at:** `9fcf1de` (origin/main HEAD at audit time -- after the v0.8.9 cycle fully closed: 3 plans executed + CHANGELOG + `v0.8.9` tag + README Phase Status + 2 followup commits for the visual-regression workflow tightening + the dimension mismatch fix)
**Recon scope:** README + CHANGELOG + plans/001-003 (v0.8.9) + libs/gw2_analytics + libs/gw2_evtc_parser/parser.py + apps/api routes + web/app pages
**Audit mode:** direction-only (3 candidates below); correctness/security/perf/etc. out of scope

### v0.9.0 status table

| # | Finding | Category | Impact | Effort | Risk | Plans |
|---|---------|----------|--------|--------|------|-------|
| 1 | `PlayerTimelineChart` (v0.8.0) + `PerFightTimelineChart` (v0.8.9) duplicate ~120 lines of near-identical SVG rendering logic; the v0.8.9 plan/002 entry noted this as a future refactor | direction (UX + DX) | Medium (DRY win, isolates complex SVG logic) | S | Low | [001](./001-v090-shared-timeline-chart.md) |
| 2 | `/players` AG Grid has no filter UI; an analyst looking for "all Mesmer players" has to scan the full table + sort client-side. The `profession` field is already in the response | direction (UX) | High (server-side filter is a one-line SQL WHERE + a dropdown) | M | Low | [002](./002-v090-filter-by-profession.md) |
| 3 | The v0.8.9 visual-regression spec covers 8 PNGs; 4 high-leverage UI states (second-fixture-fight, sorted-players, fight-with-timeline, account-with-tz) are missing | direction (testing) | Medium (catches v0.8.9 UI regressions that the current 8 PNGs miss) | S | Low | [003](./003-v090-vr-suite-expansion.md) |
| - | Buff uptime tracking (new visualization) | not a finding — the Python parser explicitly skips state-change records (`if is_statechange != 0: continue`); arcdps encodes buff applications as state changes. Implementing requires a major v1.4+ parser update before any aggregators could be built | — | — | — | rejected |
| - | Defense events ("what hit me") | not a finding — the parser only evaluates `is_nondamage == 0 + value > 0` (outgoing damage). Gathering incoming/defense events requires parser-level work + validation of arcdps's target tracking. Too undefined for v0.9.0 | — | — | — | rejected |
| - | AG Grid Community → Enterprise upgrade / Sentry integration | not a finding — same rejections as v0.8.9 (license cost + no production traffic) | — | — | — | rejected |

### Recommended execution order (v0.9.0)

1. **Plan 002** (filter by profession on `/players`) — M effort, the
   highest-leverage new feature. Self-contained (no parser/UX
   dependencies). A server-side `?profession=` query param + a small
   Client Component dropdown unlocks the existing `profession` field
   that's already in the response.
2. **Plan 001** (shared `<TimelineChart>` refactor + unified
   `?window_s=` UI) — S effort, a quick DRY win that depends on the
   v0.8.9 plan/002 being shipped (the per-fight timeline chart is
   one of the 2 refactor targets). The unified window-size UI is a
   small Server-Component change that drives both endpoints.
3. **Plan 003** (visual regression suite expansion) — S effort,
   additive coverage. Locks the v0.8.9 features in CI by capturing
   4 new PNGs (second-fixture-fight, sorted-players,
   fight-with-timeline, account-with-tz). The data-driven spec loop
   picks them up automatically.

There are no inter-plan dependencies blocking. All 3 are independent
and could ship in any order. The recommended order is by highest
leverage (plan/002 = new feature), then DRY win (plan/001), then
additive test coverage (plan/003).

### Considered and rejected (v0.9.0)

- **"Buff uptime tracking"**: a compelling visualization, but the
  Python parser explicitly skips state-change records (`parser.py:201`
  reads `if is_statechange != 0: continue`). arcdps encodes buff
  applications as state changes. Implementing this requires a major
  v1.4+ update to the core parser's binary extraction loop before
  any aggregators could be built. Defer to a future cycle that
  includes a parser overhaul.
- **"Defense events / 'what hit me'"**: complements the v0.8.9
  per-fight timeline ('what I did') with the reverse view. But the
  parser only evaluates `is_nondamage == 0 + value > 0` (outgoing
  damage). Gathering incoming/defense events requires parser-level
  work + validation of arcdps's target tracking. Too undefined for
  v0.9.0.
- **"AG Grid Community → Enterprise upgrade" / "Sentry integration"**:
  same rejections as the v0.8.9 audit. License cost + no production
  traffic.
- **"Compare 2 fights side-by-side"**: could use the v0.9.0 plan/001
  shared `<TimelineChart>` as the base. The side-by-side layout is a
  separate concern; deferred to v0.9.0+ (would depend on plan/001).
- **"Visual regression dashboard"**: a thin Server Component page at
  `/dev/visual-regression` that displays the latest captured PNGs +
  diff-vs-baseline percentages. Deferred to v0.9.0+; would need a
  "latest diff" artifact store that doesn't exist yet.

---

### Hardening followups (post v0.9.1 ship)

Two followup cycles landed during the v0.9.1 hardening pass after the 5 audit plans shipped:

| # | Action | Addresses | Outcome |
|---|---|---|---|
| H1 | **Plan 007 re-attempt** — the originally-deferred multi-tick scheduler test `test_retry_scheduler_failure_promotes_to_dlq_after_max_attempts` (exponential backoff at attempt 2 + DLQ-promote at attempt 3, seeded via `time-machine` clock advances + respx 500 mock) moved to a standalone `apps/api/tests/test_webhooks_e2e_scheduler.py` module with FLAT per-tick `with`-block structure (`_respx.mock` OUTERMOST + short-lived `time_machine.travel` per tick, no nesting); the original `pytest.skip()` placeholder in `apps/api/tests/test_webhooks_e2e.py` replaced with a stub-by-name pointer for search-by-name discoverability; ``assert count1 == 1``/``assert count2 == 1`` assertions moved to 8-space (inside each `time_machine.travel`) so they re-anchor unambiguously after future str_replace cleanups | deferred slot in plan 007 (the in-session deferred multi-tick scheduler test) | **shipped** -- all 4 retry+DLQ+replay tests from plan 007 now land; 22 tests collected across the 2 files; ruff + mypy + pytest collect-only all clean |
| H2 | **Pre-existing lint-debt cleanup** -- 9 ruff errors + 9 ruff-format fixes + 3 mypy errors in `apps/api/tests/` (all pre-existing from prior v0.9.0/v0.9.1 cycles, NOT introduced by plans 004-008). Auto-fixes via `ruff check --fix --unsafe-fixes` (cleared 2 F841 unused-vars in test_players.py) + `ruff format` (10 files reformatted); targeted str_replace / Python edits cleared the rest: dropped 2 unused `# noqa:` directives in test_players.py (PLC0415 on top-level `struct`, F401 on actively-used `_uuid`), dropped extra isort blank-line split, hoisted `import time` to top-level + dropped the inline `import time as _time  # noqa: PLC0415, F811` + converted 2× `_time.sleep(0.1)` to `time.sleep(0.1)`, reordered the stdlib imports in test_uploads_e2e.py (`from X` before `import X`), wrapped the long docstring line in test_webhooks_e2e_scheduler.py via `See  \`\`...\ntest_retry_scheduler_failure_promotes_to_dlq_after_max_attempts\`\``, ran `ruff check --fix` (auto-fixed the trailing W293 whitespace + the residual I001 group split) + `ruff format` for a final pass | accumulated lint debt from test_players.py / test_uploads_e2e.py / test_webhooks_e2e.py / test_webhooks_e2e_scheduler.py | **shipped** -- `ruff check` + `ruff format --check` + `mypy libs apps --no-incremental` all 0 errors; 22 pytest tests collect; ``git status`` shows the 4 affected test files modified (no behavioural changes in production code) |

Both followups are docs-only + test-fixture-touch-ups; no production code paths were affected. The v0.9.1 hardening cycle is now ready for the operator-side close-out: the atomic `feat(api+web): v0.9.1 security + correctness hardening (schemas, SSRF, BG-task, retry+DLQ+replay tests, OpenAPI drift gate)` commit + CHANGELOG `[0.9.1]` entry + `v0.9.1` tag.

---

## v0.9.2 hardening (post v0.9.1 ship)

Stamped at `pre-d70c8c6` (origin/main HEAD at close-out time -- after the v0.9.1 hardening cycle fully closed: 5 audit plans + H1 + H2 followups shipped + the v0.9.2 close-out landed in 5 atomic commits per the [009 plan](./009-v092-webhook-rest.md)).

v0.9.2 was a hard-trigger follow-up surfaced by the v0.9.1 close-out:

| Trigger | Finding | Plan step that closes it |
|---|---|---|
| v0.9.1 deferred-3a | `test_replayed_delivery_byte_for_byte_hmac_matches_original` — JSONB intrinsic key reordering broke the HMAC byte-for-byte guarantee | Step 2 (wire `LargeBinary` through dispatch+scheduler+replay) |
| v0.9.1 deferred-3b | `test_replay_dlq_idempotent_concurrent_calls` — concurrent reads on `OrmWebhookDlq` create duplicate delivery rows | Step 3 (Postgres `SELECT ... FOR UPDATE` row-level lock on `replay_dlq_delivery`) |
| v0.9.1 close-out audit | No project-wide convention for path-parameter vs byte-only discriminator encoding (the urlsafe fix happened at one site; future discriminator sites could regress) | Step 4 (discriminator-encoding docstring convention) |
| v0.9.1 close-out audit | The full `apps/api/tests/` suite times out at >600s due to accumulated DB state across the 4 SLOW modules | Step 5 (central conftest.py fixtures, autouse cleanup of 6 tables) |
| Step 5 by-product | 2 pre-existing test failures (TZ-test contract mismatch; missing-fixture bug in plan-006 regression test) surfaced as the conftest fixed the accumulated-state hang | Followup commit `abd7deb` |

### v0.9.2 execution summary (5 atomic commits)

1. **`85716b6` — Step 1+2 (migration 0008 payload JSONB→LargeBinary + dispatch+scheduler+replay wiring)**: `apps/api/alembic/versions/0008_payload_bytes.py` (NEW) alters both `webhook_deliveries.payload` + `webhook_dlq.payload` from `JSONB` → `LargeBinary` (NOT data-preserving; documented as a v0.9.2 warning); `apps/api/src/gw2analytics_api/models.py` maps both columns to `Mapped[bytes]`; `apps/api/src/gw2analytics_api/workers/webhook_dispatch.py` writes `payload = json.dumps(body_dict, separators=(",", ":")).encode("utf-8")` (canonical bytes that the HMAC signs); `apps/api/src/gw2analytics_api/workers/webhook_scheduler.py` reads back the same bytes verbatim on retry (no dict round-trip, no JSONB re-ordering hazard); `apps/api/src/gw2analytics_api/routes/webhooks.py::replay_dlq_delivery` copies `dlq.payload` (bytes) into `new_delivery.payload` (bytes) directly.
2. **`99faa35` — Step 3 (row-level lock on `replay_dlq_delivery`)**: `apps/api/src/gw2analytics_api/routes/webhooks.py::replay_dlq_delivery` now opens the DLQ lookup with `db.execute(select(OrmWebhookDlq).where(OrmWebhookDlq.id == delivery_id).with_for_update()).scalar_one_or_none()` (Postgres `SELECT ... FOR UPDATE` row-level lock) instead of the legacy `db.get(OrmWebhookDlq, delivery_id)`. Exactly one of the concurrent threads reads + deletes the DLQ row; the second thread's transaction blocks until the first commits then sees NULL → 404.
3. **`a247430` — Step 5 (conftest.py central fixture cleanup)**: `apps/api/tests/conftest.py` (NEW) function-scoped autouse fixture `_isolate_test_state` bulk-deletes from 6 tables (uploads, fights, fight_player_summaries, webhook_subscriptions, webhook_deliveries, webhook_dlq) before each test; pre-Step-5 full suite hangs at >600s, post-Step-5 full suite runs in ~10s; removed the local autouse in `apps/api/tests/test_webhooks_e2e_scheduler.py` (now superseded by the broader conftest cleanup); `apps/api/tests/test_players.py::test_players_filter_with_pagination` now self-seeds 5 Mesmer records (the conftest wipes accumulated state, so the test must rebuild its own seed).
4. **`abd7deb` — Step 5 by-product (fix 2 pre-existing test failures)**: `apps/api/tests/test_uploads_e2e.py::test_player_timeline_tz_422_when_invalid_timezone` assertion fixed (route returns `detail` as a plain string, not a FastAPI-validation list-detail; new assertion handles both shapes via `str(body.get('detail', ''))`); `apps/api/tests/test_uploads_e2e.py::test_background_task_session_alive_at_invocation` (plan 006 regression test, 3 bugs): `probe = get_sessionmaker() → probe = get_sessionmaker()()` (double-call pattern); `assert resp.status_code == 202 → == 201` (correct REST semantics; the BG-task is implementation detail). Plus `apps/api/tests/conftest.py` gained 2 new pytest fixtures: `client` + `get_sessionmaker` (both consumed by the regression test's signature).
5. **`d70c8c6` — Step 4 (discriminator-encoding docstring convention)**: `apps/api/src/gw2analytics_api/routes/webhooks.py` gets 3 docstring additions (no code logic changes) on `_generate_subscription_id` (path-parameter convention), `_generate_secret` (byte-only convention), and `_generate_delivery_id` (UUID is URL-safe by definition). `CONTRIBUTING.md` gains a new `## Webhook discriminator IDs` section (cross-referenced from the 3 helper docstrings) with 3 bullet classifications + a classification guide for new discriminators.

### Outcomes

- Plan 009's 2 originally-deferred v0.9.1 test failures are now resolved (HMAC byte-for-byte across retries + concurrent replay idempotent).
- The full `apps/api/tests/` suite: **92 pass / 0 fail / 3 skip in ~10s** (was 90/1/2 in >600s pre-Step-5).
- Webhook e2e + scheduler: **22 pass / 0 fail / 1 skip** (unchanged from v0.9.1 close-out; the v0.9.2 followups are defect fixes, not new test coverage).
- The discriminator-encoding convention is now IDE-discoverable + CONTRIBUTING-documented for future discriminator sites.
- `apps/api` test count is unchanged (219 → 241 was the v0.9.1 delta; v0.9.2 adds zero new test cases since the pre-existing fixes are regression guards, not new tests).
- Migration 0008 is intentionally **NOT** data-preserving — pre-v0.9.2 rows become an opaque byte-bag (their dict structure is lost). Operators MUST either: (a) drain DLQ + deliveries before applying, OR (b) accept that pre-v0.9.2 rows lose their original dict. Documented in the migration's `# WARNING` header + the CHANGELOG `[0.9.2]` close-out note.

### Considered but not in v0.9.2 scope (deferred to v0.9.3+)

- **webhook secret-at-rest** (carried from v0.9.1 Deferred list): plaintext in PostgreSQL today; HMAC verification requires plaintext, so full hashing is impossible — pgcrypto envelope encryption with a `SECRETS_KEK` env var is the layered defence path. Deferred because v0.9.2 is feature-complete; tracking starts from the v0.9.1 close-out CHANGELOG.
- **migration 0008 reverse path** (data preservation on `alembic downgrade -1`): would require a v0.9.2 patch-release if any operator needs to roll back the upgrade. Listed as a future hardening item.

## v0.8.9 audit (closed)

**Author:** senior-advisor audit (improve skill, `next` invocation, `quick` effort)
**Stamped at:** `1b1de47` (origin/main HEAD at audit time -- after the
v0.8.8 cycle fully closed: 3 plans executed, CHANGELOG entry, `v0.8.8`
tag on origin, README `## Release Tags` + `## Phase Status` synced)
**Recon scope:** README + CHANGELOG + pyproject.toml + apps/api routes +
web/app pages + recent commits + plans/001 + plans/002 + plans/003
**Audit mode:** direction-only (3 candidates below);
correctness/security/perf/etc. out of scope

### v0.8.9 status table

| # | Finding | Category | Impact | Effort | Risk | Plans |
|---|---------|----------|--------|--------|------|-------|
| 1 | Per-day bucketing on `/players/[name]/timeline` is UTC-only; the v0.8.1 CHANGELOG already noted a future `?tz=Europe/Paris` query param | direction (DX + correctness) | Medium (per-day bucketing only really makes sense in an analyst's TZ) | S | Low | [001](./001-tz-param-player-timeline.md) |
| 2 | `/fights/[id]` has per-target trio + per-subgroup + per-skill + event windows; no temporal view within a single fight (the v0.8.0 player timeline is cross-fight only) | direction (analytics + UX) | High (new visualization; complements the per-target trio) | M | Low | [002](./002-per-fight-timeline-tab.md) |
| 3 | v0.8.8 shipped 8 tracked PNGs at `docs/screenshots/` but no automated check that a UI refactor doesn't change them | direction (testing) | High (catches UI regressions in CI) | M | Low | [003](./003-visual-regression-testing.md) |
| - | AG Grid Community → Enterprise upgrade (Row Grouping, Master/Detail, Server-Side Row Model) | not a finding — vendor + license decision; current dataset size doesn't justify the cost | — | — | — | rejected |
| - | Sentry integration for error tracking | not a finding — defer until production traffic warrants it (current setup has no production traffic) | — | — | — | rejected |

### Recommended execution order (v0.8.9)

1. **Plan 001** (`?tz=Europe/Paris` on player timeline) — S effort, the
   smallest + highest-leverage of the 3 plans. Well-scoped extension
   to the v0.8.1 day-bucketing work; the service-layer swap is a
   1-line `to_user_tz(started_at).date()` change. Closes the long-
   standing "TZ assumption documented inline" technical-debt note from
   the v0.8.1 CHANGELOG.
2. **Plan 002** (per-fight timeline tab on `/fights/[id]`) — M effort,
   new visualization that complements the per-target trio. Reuses the
   v0.8.0 `PlayerTimelineChart` data shape (3 polylines, per-series
   normalisation, SVG-native `<title>` tooltip); a future refactor
   could extract a shared `<TimelineChart>` base component. The
   `GET /api/v1/fights/{id}/timeline` route is a thin wrapper over
   the existing events-blob decompress.
3. **Plan 003** (visual regression testing) — M effort, M payoff.
   Closes the gap between "we have 8 tracked PNGs" and "CI fails on
   a UI refactor that changes any of them by > 1%." Uses
   `playwright.screenshot()` + `pixelmatch` (npm, ~50 KB).

There are no inter-plan dependencies blocking. All 3 are independent
and could ship in any order.

### Considered and rejected (v0.8.9)

- **"AG Grid Community → Enterprise upgrade"**: vendor + license
  decision; the current dataset size (single-fight pages with
  5-100 rows) doesn't justify the cost. Row Grouping + Master/Detail
  would be useful for cross-fight roll-ups, but the v0.7.0
  PlayerProfileAggregator already handles the cross-fight join
  server-side. Defer to v0.9.0+ when the dataset grows past 1000
  fights and the client-side rendering starts to struggle.
- **"Sentry integration for error tracking"**: the current setup has
  no production traffic, so error tracking is premature. Defer until
  the first production deployment warrants it.
- **"Upload round-trip e2e test"**: was deferred from v0.8.8 plan/002.
  The fixture-blob work is non-trivial (a real `.zevtc` fixture that
  exercises the parser without taking 30s), and the e2e suite would
  need a real-API CI run (the mock server doesn't exercise the actual
  upload parser). Defer to v0.9.0+ when a real-fixture integration
  test exists for the parser.
- **"Refactor 3 existing Playwright specs to add the `pageerror` check"**:
  was deferred from v0.8.8 plan/002. The 1-line change per spec is
  too small to be a standalone plan. Can be folded into plan 003
  (visual regression testing) as a sub-task if the visual regression
  work is in flight; otherwise, fold it into the first plan that
  touches the existing specs.

---

## v0.8.8 audit (closed)

**Author:** senior-advisor audit (improve skill, `next` invocation, `quick` effort)
**Stamped at:** `fe99cb7` (origin/main HEAD at audit time)
**Recon scope:** README + CHANGELOG + pyproject.toml + apps/api routes + web/app pages + recent commits
**Audit mode:** direction-only (4 candidates below); correctness/security/perf/etc. out of scope

### v0.8.8 status table (closed)

| # | Finding | Category | Impact | Effort | Risk | Status (final) | Plans |
|---|---------|----------|--------|--------|------|----------------|-------|
| 1 | `pnpm screenshots` produces 8 PNGs that are gitignored + invisible to end-users | direction (DX + docs) | High (UX) | S | Low | **shipped** (`6fc4fcb`) | [001](./001-screenshots-into-readme.md) |
| 2 | Playwright config + `pnpm test:e2e` exist but zero actual e2e tests in repo | direction (testing) | High (reliability) | M | Low | **shipped** (`1b1de47`) -- 3 of 6 specs + mock-server + CI already in `web/tests/e2e/` from v0.7.1/v0.7.2/v0.8.0; v0.8.8 added 3 new specs (landing/account/upload) + 2 mock endpoints (POST /api/v1/account + POST /api/v1/uploads) | [002](./002-real-playwright-e2e-suite.md) |
| 3 | `pnpm generate:api` is manual; web app often runs against a stale or absent `schema.d.ts` | direction (DX) | Medium (dev experience) | S | Low | **shipped** (`7f40d51`) | [003](./003-auto-codegen-on-pnpm-dev.md) |
| - | Web routes already cover all API endpoints (7/7 web pages vs 8 distinct API endpoint groups) | not a finding — already shipped | — | — | — | rejected |

### v0.8.8 execution summary

1. ~~**Plan 001** (Screenshots → README)~~ — shipped in `6fc4fcb`. 8
   PNGs tracked at `docs/screenshots/`, wired into a new `## Screenshots`
   section of the root README, with `pnpm screenshots --persist` as
   the refresh workflow.
2. ~~**Plan 002** (Close remaining e2e gaps)~~ — shipped in `1b1de47`.
   3 new spec files (`landing.spec.ts`, `account.spec.ts`,
   `upload.spec.ts`) + 2 mock endpoint additions to
   `web/tests/e2e/mock-server.mjs` (`POST /api/v1/account` +
   `POST /api/v1/uploads`). The plan was revised at `48fa91a` to
   reflect the 3 pre-existing specs (fights/players/players-timeline)
   that the v0.7.1/v0.7.2/v0.8.0 cycles had already shipped.
3. ~~**Plan 003** (Auto-codegen on dev)~~ — shipped in `7f40d51`.
   `pnpm dev` now chains `pnpm generate:api && next dev`; missing
   `openapi-typescript` dep added; `web/.gitignore` updated;
   `web/README.md` `## OpenAPI regeneration` section rewritten.

The v0.8.8 cycle is fully closed: 3 plans executed + CHANGELOG
`[0.8.8]` entry + `v0.8.8` tag on origin + README `## Release Tags` +
`## Phase Status` synced.

### Considered and rejected (v0.8.8)

- **"Build /fights/[id]/timeline tab" / "Upload progress feedback" / "Per-player-fights route"**: each is plausible but small-leverage vs the plans above; would need full design + UX validation first. **The per-fight timeline tab is now plan/002 in the v0.8.9 audit** (with the design + UX validation done); the other two remain reserved for v0.9.0+.
- **"S3-backed blob storage for evtc files"**: large infrastructure commitment (storage vendor, IAM, lifecycle, cost); proceed only after uploader has real-user volume proving the need. Out of scope for v0.8.8 (and v0.8.9).
- **"Web route coverage of remaining API endpoints"**: all 7 web pages already exist and route to the corresponding API endpoints; coverage is full. Not a finding.

---

## Conventions for the executor

- The repo uses Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`, `style:`, `refactor:`).
- Python: `uv run <cmd>` from repo root or `cd apps/api && uv run <cmd>` — never `pip`.
- JS: `pnpm <cmd>` from `web/` or repo root (pnpm workspace).
- Validation: `uv run ruff check`, `uv run mypy --no-incremental libs apps`, `uv run pytest <path>`, `pnpm typecheck`, `pnpm test:unit`, `pnpm exec playwright test`.
- Commit-style: every commit has substance (no empty commits); every feature gets a doc sync in the same cycle (README + CHANGELOG).
- Code-reviewer pattern: spawn `code-reviewer-minimax-m3` for **every** non-trivial commit with concrete prompt (≤70 words + focus questions).
- Plan pattern: every plan is self-contained. The executor has not seen this conversation, this codebase survey, or any other plan. If a plan references "the pattern discussed above," it is broken.
