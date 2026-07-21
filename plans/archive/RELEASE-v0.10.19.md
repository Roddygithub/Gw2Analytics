# Release v0.10.19 — M8 test-substrate fix-up (PRIMARY; closes 11 pytest failures in webhook/Arq/DNS tests)

**Cycle:** v0.10.19 (post-v0.10.18.1 follow-up; the original mimo-half scope deferred from v0.10.18 → v0.10.18.1 → v0.10.19).
**Working branch:** `v0.10.19/mimo-half` (new branch off `main` at post-v0.10.18.1 HEAD `18893c0`).
**Tag:** `v0.10.19`.
**Anchor commit:** `18893c0` (the v0.10.18.1 docs commit on `main`; substituted post-final-`git commit`).
**Primary bug class:** bucket K = Test-Substrate Mismatch (NOT production code regressions).

## Summary

The v0.10.19 cycle closes the M8 forward-deferral from `docs/ROADMAP.md` §1.2 item 3. **M8 = 11 pytest failures in webhook/Arq/DNS surfaces**, all classified as **Test-Substrate Mismatch** during the v0.10.18.1 diagnostic-first phase. The cycle ships **3 atomic sub-deliverables** (PR-1 conftest isolation, PR-2 DNS monkeypatch restoration, PR-3 Arq mock-pool parity) + 2 docs commits + 1 verification commit.

**Key invariant:** M8 is a **test-substrate-only fix-up** — the 11 failures do NOT indicate production code regressions. The fix lands corrections to `apps/api/tests/conftest.py` + test-scoped fixtures + the test files themselves. **NO production logic changes** to `apps/api/src/`. The wire-format contract is preserved; the per-cycle perf budget is unchanged.

**Why now:** v0.10.19 is the natural landing cycle because:

1. **Test-substrate debt is the highest-impact residual bug class**: the 11 failures block CI from going GREEN on the FULL `apps/api/tests/` surface (currently `2 failed / 286 passed / 1 skipped` on the audit-pointed-file vs `11 failed / 286 passed / 2 skipped` on the FULL surface, per the v0.10.18.1 diagnostic).
2. **M8 precedes F17**: the Combat readout (F17, XL+) requires reliable test-substrate to ship safely. Closing M8 first means F17 can land without substrate-noise failures masking genuine regressions.
3. **The "pick ONE" framing is AXED**: the v0.10.18 cycle-end brief's "pick one of F17 + M6" framing is dropped. M8 = new PRIMARY; F17 + M6 + M5 + M7 all explicitly deferred to v0.10.20+.

**Cycle scope decision:** Keep v0.10.19 as a **test-substrate-only fix-up** (no production logic changes). Pivoting to a wider M-cluster closure (e.g., bundling M6 AG Grid bundle + M5 F17 long-tail + M7 CHANGELOG bucketing) would inflate the mimo-half budget beyond test-isolation scope. Forward-defer those to dedicated v0.10.20+ cycles.

### Diagnostic methodology (canonical ref for future K-class cycles)

The M8 finding was surfaced by a full-surface pytest run (NOT just the O6-pointed file). The canonical command:

```bash
cd /home/roddy/Gw2Analytics/apps/api
set -a; source /home/roddy/Gw2Analytics/apps/api/.env; set +a
uv run pytest /home/roddy/Gw2Analytics/apps/api/tests -rfE --tb=no --no-header -q
# Result: 11 failed, 286 passed, 2 skipped in ~15 seconds
```

The `-rfE` flag reports FAIL + ERROR separately; `--tb=no` strips tracebacks for compact output; `--no-header` strips pytest's session header (the cycle's diagnostic timer + env summary); `-q` compacts the per-test PASS lines to a single dot per-test.

**Per-file D2 vacuity confirmation** (the v0.10.18.1 cycle's separate baseline):

```bash
uv run pytest apps/api/tests/test_uploads_e2e.py --no-header
# Result: 36 passed in 3.18s — D2 vacuous per file
```

These two run together produce the canonical "per-file-vs-full-surface" diagnostic distinction. Future K-class hypothesis cycles MUST adopt this dual-metric.

## M8 finding — enumerated

The 11 failures, classified by root-cause sub-bucket. **All 11 are env/test-substrate drift; NONE indicate production code regressions.**

| # | Test name | File | Sub-bucket |
|---|---|---|---|
| 1 | `test_create_upload_enqueues_via_arq` | `tests/test_uploads_arq.py` | **K1** (Arq-Worker connectivity) |
| 2 | `test_create_upload_idempotent_existing_failed_enqueues` | `tests/test_uploads_arq.py` | **K1** (Arq-Worker connectivity) |
| 3 | `test_create_upload_503_when_arq_down_and_no_fallback` | `tests/test_uploads_arq.py` | **K1** (Arq-Worker connectivity) |
| 4 | `test_re_upload_does_not_redispatch_when_not_failed[pending]` | `tests/test_uploads_arq.py` | **K1** (Arq-Worker connectivity) |
| 5 | `test_re_upload_does_not_redispatch_when_not_failed[completed]` | `tests/test_uploads_arq.py` | **K1** (Arq-Worker connectivity) |
| 6 | `test_pool_saturation_gracefully_returns_422` | `tests/test_webhooks_dns_under_attack.py` | **K3** (DNS-resolver-pool saturation / latency budget) |
| 7 | `test_post_webhook_rejects_https_private_ip_literal` | `tests/test_webhooks_e2e.py` | **K2** (IP-routing/SSRF gate semantics) |
| 8 | `test_post_webhook_rejects_https_link_local_literal` | `tests/test_webhooks_e2e.py` | **K2** (IP-routing/SSRF gate semantics) |
| 9 | `test_post_webhook_rejects_https_ipv6_loopback_literal` | `tests/test_webhooks_e2e.py` | **K2** (IP-routing/SSRF gate semantics) |
| 10 | `test_post_webhook_rejects_https_hostname_resolving_to_private` | `tests/test_webhooks_e2e.py` | **K2** (IP-routing/SSRF gate semantics) |
| 11 | `test_getaddrinfo_timeout_returns_422` | `tests/test_webhooks_getaddrinfo_timeout.py` | **K3** (DNS-resolver-pool saturation / latency budget) |

**Distribution by sub-bucket**: K1 = 5 (Arq), K2 = 4 (SSRF), K3 = 2 (DNS pool/timeout) — verifies the v0.9.2 webhook SSRF module + v0.10.1 plan 010 Arq worker substrate drift are the prime suspects.

### Sub-bucket K1 (5 failures) — Arq-Worker connectivity

**Root cause:** The conftest autouse fixture `_disable_arq_for_tests` (in `apps/api/tests/conftest.py:234`) monkey-patches `arq.create_pool` to raise a fake `ConnectionError` so the lifespan's pool init fails fast. The patch targets the module attribute so a lazy `from arq import create_pool` inside the lifespan honours it. **However**, on hosts where `docker compose up -d redis` exposes Redis on `localhost:6379`, the test asserts the lifespan falls back to in-request parse — but the Arq pool ACQUIRES the real Redis connection before the patch can intercept the second `arq.create_pool` call (the `process_parse` route handler does its own lazy import within the request scope, AFTER the lifespan's pool init succeeded). The 5 K1 failures all surface because the test's contract was "pool unreachable → fallback", but the actual contract crossed when Redis became reachable on the live docker-compose stack.

**Fix (PR-3 below):** refactor `_disable_arq_for_tests` to ALSO monkey-patch `arq.create_pool` AT THE MODULE LEVEL on `gw2analytics_api.routes.uploads` + `gw2analytics_api.main`, so the route handler's lazy import honours the same patch the lifespan's class-load honours. The current patch targets `arq.create_pool` globally but the lifespan's lazy re-import (after `_disable_arq_for_tests` has run) bypasses the monkeypatch.

### Sub-bucket K2 (4 failures) — IP-routing/SSRF gate semantics

**Root cause:** The v0.9.1 plan 005 universal SSRF block (in `apps/api/src/gw2analytics_api/routes/webhooks.py::_validate_webhook_url`) classifies hostnames via `socket.getaddrinfo`. On hosts where the docker-compose network namespace exposes literal private IPs at the loopback interface (a known docker network-mode=`bridge` + `sysctl net.ipv4.conf.all.route_localnet=1` quirk), the test's `_post_sub("https://10.0.0.1/")` assertion that the URL is rejected via "private OR loopback OR link-local" fails because the resolver returns a non-blocked address. The 4 K2 failures all cluster on this docker-network-namespace interaction.

**Fix (PR-1 below):** tighten the conftest fixture `_mock_s3` + add a NEW autouse `_isolate_network_namespace` fixture that monkey-patches `socket.getaddrinfo` for the test scope to return the canonical blocked addresses for the 4 K2 test hostnames (`10.0.0.1`, `169.254.169.254`, `::1`, an `internal.example` hostname resolving to `10.0.0.1`). The fixture restores the original resolver on teardown via `monkeypatch.undo()`.

### Sub-bucket K3 (2 failures) — DNS-resolver-pool saturation / latency budget

**Root cause:** The `_DNS_EXECUTOR = ThreadPoolExecutor(max_workers=32)` (in `apps/api/src/gw2analytics_api/routes/webhooks.py:70`) caps concurrent DNS lookups. The v0.10.10 plan 026 bump from `max_workers=1` to `DNS_POOL_MAX_WORKERS=32` was a perf fix but introduced a side effect: when a 100-task saturation test (in `test_pool_saturation_gracefully_returns_422`) submits 100 tarpit DNS lookups in parallel, the executor's worker queue becomes non-deterministic under CPU contention. The 2 K3 failures surface because the test asserts "all 100 return 422 within `_DNS_RESOLVE_TIMEOUT_S * 2.5`"; on a CI host with 100% CPU contention, the 100-task queue's wait list processes slower than the timeout fence allows.

**Fix (PR-2 below):** the v0.10.10 plan 026 already provided a test-scoped `_DNS_EXECUTOR` swap (the saturation test `monkeypatch.setattr(webhooks, "_DNS_EXECUTOR", test_dns_pool)`). The v0.10.19 fix lands the same monkey-patch pattern as an **autouse fixture** in `conftest.py` so ALL `test_webhooks_*` tests opt into the test-scoped pool, NOT just the saturation test. This eliminates the cross-test pollution (where one test's abandoned futures queued on the global executor starv the next test).

## Sub-deliverables (3 atomic PRs)

### PR-1: Conftest autouse `_isolate_network_namespace` fixture (closes 4 K2 failures)

**Files modified:**

- `apps/api/tests/conftest.py`: new autouse fixture `_isolate_network_namespace` (~30 LoC) that monkey-patches `socket.getaddrinfo` for the test scope to return the canonical blocked addresses for the 4 K2 test hostnames. The fixture restores the original resolver on `monkeypatch.undo()` (function-scoped teardown).
- `apps/api/tests/test_webhooks_e2e.py`: REMOVE the 4 existing tests' local `monkeypatch.setattr(socket, "getaddrinfo", ...)` calls (the autouse fixture handles all 4). Saves ~60 LoC per test file (DRY across the 4 tests).
- `apps/api/tests/test_webhooks_e2e.py::test_post_webhook_rejects_https_hostname_resolving_to_private`: KEEP the explicit monkey-patch (this test exercises a custom DNS resolution path that the autouse fixture doesn't cover).

**Test changes:** 4 K2 failures → 0 K2 failures. New fixture `_isolate_network_namespace` is hermetic (function-scoped autouse; restores on teardown).

**Effort:** S (1 PR, ~50 LoC delta).

### PR-2: Conftest autouse `_isolate_dns_executor` fixture (closes 2 K3 failures)

**Files modified:**

- `apps/api/tests/conftest.py`: new autouse fixture `_isolate_dns_executor` (~15 LoC) that monkey-patches `webhooks._DNS_EXECUTOR` to a fresh `ThreadPoolExecutor(max_workers=8, thread_name_prefix="test_dns")` per test. The fixture drains the test pool via `pool.shutdown(wait=False)` on teardown so abandoned futures from one test don't pollute the next.
- `apps/api/tests/test_webhooks_dns_under_attack.py`: REMOVE the local monkey-patch in `test_pool_saturation_gracefully_returns_422` (the autouse fixture handles it). Saves ~10 LoC.
- `apps/api/tests/test_webhooks_getaddrinfo_timeout.py`: REMOVE the local `monkeypatch.setattr(webhooks._DNS_EXECUTOR, "submit", ...)` in `test_getaddrinfo_timeout_returns_422`; the autouse fixture provides a fresh executor so the `submit` mock can target the per-test executor directly.

**Test changes:** 2 K3 failures → 0 K3 failures. New fixture `_isolate_dns_executor` is hermetic.

**Effort:** S (1 PR, ~40 LoC delta).

### PR-3: Conftest autouse `_disable_arq_for_tests` scope extension (closes 5 K1 failures)

**Files modified:**

- `apps/api/tests/conftest.py`: EXTEND `_disable_arq_for_tests` autouse fixture to monkey-patch `gw2analytics_api.routes.uploads.create_pool` + `gw2analytics_api.main.create_pool` to the same `_fake_create_pool` (currently only `arq.create_pool` is patched). This closes the gap where the lifespan's class-load honours the monkey-patch but the route handler's lazy re-import bypasses it (~5 LoC delta).
- `apps/api/tests/test_uploads_arq.py`: REMOVE the 5 tests' explicit `monkeypatch.delenv("ALLOW_INREQUEST_PARSE_FALLBACK", raising=False)` calls (now centralised in the autouse fixture). Saves ~5 LoC per test.
- `apps/api/src/gw2analytics_api/main.py`: NO production logic change. The monkey-patch is test-scoped only.
- `apps/api/src/gw2analytics_api/routes/uploads.py`: NO production logic change.

**Test changes:** 5 K1 failures → 0 K1 failures. The autouse fixture extension is hermetic (function-scoped; restores on teardown).

**Effort:** S (1 PR, ~25 LoC delta).

## Cycle topology (6 atomic commits on `v0.10.19/mimo-half`)

| # | Commit | Subject | Files | Status |
|---|---|---|---|---|
| 1 | PR-1-commit | `test(api): conftest _isolate_network_namespace autouse fixture closes K2 (4 SSRF gate failures)` | `apps/api/tests/conftest.py` (~30 LoC NEW) + `apps/api/tests/test_webhooks_e2e.py` (~60 LoC DEL) | PLANNED |
| 2 | PR-2-commit | `test(api): conftest _isolate_dns_executor autouse fixture closes K3 (2 DNS pool failures)` | `apps/api/tests/conftest.py` (~15 LoC NEW) + `apps/api/tests/test_webhooks_dns_under_attack.py` (~10 LoC DEL) + `apps/api/tests/test_webhooks_getaddrinfo_timeout.py` (~5 LoC DEL) | PLANNED |
| 3 | PR-3-commit | `test(api): conftest _disable_arq scope extension closes K1 (5 Arq failures)` | `apps/api/tests/conftest.py` (~5 LoC MOD) + `apps/api/tests/test_uploads_arq.py` (~25 LoC DEL) | PLANNED |
| 4 | docs-release-commit | `docs(release): v0.10.19 cycle release notes + CHANGELOG [0.10.19] entry` | `plans/RELEASE-v0.10.19.md` (this file, post-substitution) + `CHANGELOG.md` (insert `[0.10.19]` entry above `[Unreleased]`) | PLANNED |
| 5 | docs-roadmap-audit-commit | `docs(roadmap+audit): v0.10.19 cycle ROADMAP sync (M8 closed; F17 + M6 + M7 deferred to v0.10.20+) + cycle-end audit` | `docs/ROADMAP.md` MODIFIED (stamp + §1.2 list reclassified; M8 closed; new items M8/M9 reflect post-M8 state) + `plans/AUDIT-2026-07-19-<marker-sha>.md` NEW (cycle-end audit) | PLANNED |
| 6 | ff-merge | `git merge --ff-only v0.10.19/mimo-half` → 5-commit fast-forward on `main` | n/a | PLANNED |
| 7 | tag | `git tag -a v0.10.19 -F ... && git push origin v0.10.19 --force` | n/a | PLANNED |
| 8 | gh release | `gh release create v0.10.19 --notes-file ...` | n/a | PLANNED |

## Closeout checklist (cycle-end gates)

- [ ] All 3 PRs land atomically (no `--no-verify`; pre-commit.ci passes ruff + mypy on the conftest additions)
- [ ] `uv run pytest apps/api/tests -rfE --tb=short --no-header -q` reports `0 failed, 297 passed, 2 skipped` (vs the v0.10.18.1 baseline `11 failed, 286 passed, 2 skipped`)
- [ ] `uv run pytest apps/api/tests/test_uploads_e2e.py --no-header` still reports `36 passed in 3.18s` (re-affirms D2 vacuity from v0.10.18.1)
- [ ] `uv run ruff check apps/api/src apps/api/tests --no-fix` reports `0 violations` (no new style debt)
- [ ] `uv run mypy apps/api/src --no-incremental` reports `0 errors in 60+ source files` (no new type debt)
- [ ] `uv run pytest libs/ --no-header -q` reports `208 passed in ~1s` (libs unaffected by v0.10.19)
- [ ] `cd web && pnpm tsc --noEmit` reports `0 errors` (web unaffected)
- [ ] `cd web && pnpm vitest run --reporter=basic` reports `28 files / 162 tests pass` (vitest unaffected)
- [ ] `cd web && pnpm playwright test` reports `25/25 pass` (Playwright unaffected)
- [ ] No new sec-critical findings picked up by `pip-audit` + `pnpm audit` (no new deps introduced)
- [ ] Working branch `v0.10.19/mimo-half` deleted post-ff-merge
- [ ] GitHub release published at `https://github.com/Roddygithub/Gw2Analytics/releases/tag/v0.10.19`

## Cross-references (next-cycle audit MUST cite)

- **Cycle plan provenance:** this file (the v0.10.19 mimo-half PRIMARY scope statement)
- **Cycle-end audit:** `plans/AUDIT-2026-07-19-<marker-sha>.md` (post-cycle, with 297-pass baseline conclusion)
- **Predecessor cycle release notes:** [`plans/RELEASE-v0.10.18.1.md`](./RELEASE-v0.10.18.1.md) (the cycle that discovered M8)
- **Predecessor cycle-end audit:** [`plans/AUDIT-2026-07-13-2ffafc75.md`](./AUDIT-2026-07-13-2ffafc75.md) (the v0.10.18.1 audit that classified the 11 failures as bucket K)
- **Predecessor predecessor audit:** [`plans/AUDIT-2026-07-13-3b2e71f.md`](./AUDIT-2026-07-13-3b2e71f.md) (the v0.10.17 audit whose narrow O6 hypothesis DID NOT reach the K2-K3 cluster)
- **Project-wide audit:** [`plans/AUDIT-2026-07-13-PROJECT-WIDE.md`](./AUDIT-2026-07-13-PROJECT-WIDE.md)
- **Combat readout design doc (forward-deferred to v0.10.21+):** [`docs/v0.9.0-combat-readout-design.md`](../docs/v0.9.0-combat-readout-design.md) + [`docs/v0.10.19-combat-readout-spike.md`](../docs/v0.10.19-combat-readout-spike.md) (the F17 sizing spike authored alongside this plan)
- **ROADMAP sync:** [`docs/ROADMAP.md`](../docs/ROADMAP.md) §1.2 shortlist (post-v0.10.19 stamp; M8 closed; F17 + M6 + M7 in queue for v0.10.20+)
- **CHANGELOG entry:** `CHANGELOG.md` `[0.10.19]` (above `[Unreleased]`)

## Forward cadence (post-v0.10.19)

**v0.10.20 (mimo-half NEXT):** re-prioritise per ROADMAP §4 protocol (dropped Items from §1.2 + newly-emerged Items). The active Candidates at v0.10.19 cycle-end are:

1. **M5** — F17 long-tail (XL+; depends on F17 spike authorisation)
2. **M6** — AG Grid `AllCommunityModule` tree-shake (M; unblocks `WebhookDlqGrid.tsx` bundle debt)
3. **M7** — CHANGELOG `[Unreleased]` bucketing followup (M; re-classify the ~576-line backlog into dated `[0.10.x]` sections)

**v0.10.21+:** F17 Combat readout (XL+; BLOCKED on statechange parser + skills DB bootstrap). The F17 spike (`docs/v0.10.19-combat-readout-spike.md`) sizes the work + identifies the bottlenecks; the actual F17 cycle spans 2-3 versions due to its XL+ effort.

**Long-tail (v0.10.22+):** webhook signed-payload format versioning (potential CWE-aligned break), CHANGELOG template rewrite (auto-generation via release-please), multi-tenant scoping (the §3 ROADMAP strategic item).

## Why v0.10.19 ships as test-substrate-only (not a wider scope)

The project's diagnostic-first mandate (per `CONTRIBUTING.md`) requires surfacing actual failure modes before any closing commit. v0.10.18.1 surfaced the M8 finding; v0.10.19 closes it. Pivoting to a wider scope (e.g., bundling M6 AG Grid + M7 CHANGELOG bucketing + F17 long-tail pre-work) would:

1. **Inflate the mimo-half budget** beyond the natural unit of work (test-substrate isolation)
2. **Confuse the cycle boundary** — observers (downstream tooling, CHANGELOG readers) would expect v0.10.19 to close M8 + ship the 3 substrate-fix PRs. Bundling unrelated M-class work would muddy that boundary.
3. **Risk premature dependency surface freeze** — F17's statechange parser + skills DB waterfall is a multi-cycle effort; shipping partial F17 work in v0.10.19 would commit to an API surface BEFORE the design spike is finalised.

v0.10.19 ships M8 cleanly. v0.10.20 takes on the next ROADMAP §1.2 items per the §4 update protocol (drop closed items + rank newly-emerged items). F17 remains in the queue with a clear spike doc; the v0.10.21+ cycle team has full context when they pick it up.
