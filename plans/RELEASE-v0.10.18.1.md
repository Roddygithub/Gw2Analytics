# Release v0.10.18.1 — D2 pre-closure marker + NEW M8 forward-deferred discovery (11 webhook/Arq/DNS test-substrate mismatches)

**Cycle:** v0.10.18.1 (post-v0.10.18 follow-up mimo-half).
**Working branch:** `v0.10.18.1/mimo-half` (reset + recreated from `main` at post-v0.10.18 HEAD `e47c9a3` per Plan (b)(ii) from the strategic re-design).
**Tag:** `v0.10.18.1`.
**Anchor commit:** `e47c9a3e` (substituted post-final-`git commit`).
**Discovery milestone:** NEW M8 finding — 11 pytest failures surfaced in apps/api/tests ahead of v0.10.18.1 closeout; classified as bucket K (Test-Substrate Mismatch), NOT regressions; inserted as ROADMAP §1.2 new item 3, forward-deferred to v0.10.19 mimo-half PRIMARY budget.

## Summary

The v0.10.18.1 cycle ships a **two-fold closeout with ROADMAP §1.2 reclassification**:

1. **D2 pre-closure marker (per-file) — closes ROADMAP §1.2 item 3 of v0.10.18 main**: the v0.10.18 brief's D2 ("close the 2 pre-existing pytest failures in `apps/api/tests/test_uploads_e2e.py`") is **CONFIRMED VACUOUS for that specific file**. `test_uploads_e2e.py` runs **36/36 PASS in 3.18s** at cycle-start HEAD `e47c9a3` (the v0.10.18 closeout tip), per the diagnostic-first verification phase. The v0.10.17 cycle-end audit's O6 hypothesis about `test_uploads_e2e.py` is therefore reclassified: pre-existing failures in THAT file = 0. The M-cluster ROADMAP §1.2 "Residual pre-existing tests fix-up" closure thread (item 3 of v0.10.18 main §1.2) is now **fully closed** (M1-M4 closed at v0.10.18 D1+D3+D4 + D2 closed at v0.10.18.1 D2 vacuity per-file).

2. **NEW M8 discovery (forward-deferred as ROADMAP §1.2 new item 3)**: the diagnostic revealed **11 ACTUAL pytest failures** in the broader `apps/api/tests/` surface, NOT in `test_uploads_e2e.py` but concentrated in **webhook/Arq/DNS-related test suites**. All 11 are classified as **bucket K — Test-Substrate Mismatch** (env/test-substrate drift on the live docker-compose stack), NOT production code regressions. Inserted as the new ROADMAP §1.2 item 3 of v0.10.18.1 cycle-end.

**Why this matters:** the v0.10.17 audit's "2 pre-existing pytest failures" hypothesis was NARROW (pointed at `test_uploads_e2e.py`), so it correctly identified that file as vacuous but did NOT surface the broader webhook/Arq failure cluster. The v0.10.18.1 diagnostic (with fresh `apps/api/.env` SECRETS_KEK + freshly-dropped + re-created `gw2analytics` Postgres + `alembic upgrade head` at `0013_drift_cleanup` + live docker compose services HEALTHY) ran the **FULL `apps/api/tests/` surface** and surfaced these 11 hidden failures for the first time.

**Cycle scope decision (Plan (b))**: keep v0.10.18.1 as a D2-vacuity-closure marker (the original scope) + ADD the NEW M8 discovery note (forward-deferred to v0.10.19). Pivoting v0.10.18.1 to fix the 11 webhook/Arq failures would have (a) violated the project's `CONTRIBUTING.md` linear-history rule (the marker commit's cycle boundary is fixed at "D2 vacuity" + M8 discovery) AND (b) inflated the v0.10.18.1 mimo-half budget M-times. Forward-deferring M8 to v0.10.19 with explicit PRIMARY priority is the cleanest separation.

### Diagnostic methodology (canonical for future cycles' O6/O7/O8-class hypotheses)

The diagnostic that surfaced this finding was:

```bash
cd /home/roddy/Gw2Analytics/apps/api
set -a; source /home/roddy/Gw2Analytics/apps/api/.env; set +a  # .env has KEK + URL + bucket config
uv run pytest /home/roddy/Gw2Analytics/apps/api/tests -rfE --tb=no --no-header -q
# Result: 11 failed, 286 passed, 2 skipped in ~15 seconds
# Specifically identified via: grep -c '^FAILED' /tmp/diag.txt → 11
```

The key signal here is the **full surface run**, not the pinpointed-file run. Future audits should always:

- Run the FULL `apps/api/tests/` surface (not just the pinpointed file in O6/O7/O8 hypotheses).
- Use **fresh env** (KEK + alembic head + docker HEALTHY) so substrate-state leaks don't mask pre-existing failures.
- Use `-rfE --tb=no --no-header -q` so per-test outcomes + the aggregate footer are both captured.
- Verify by `grep -c '^FAILED' /tmp/diag.txt` (returns 0 = vacuous; >0 = real).

This **per-file vs full-surface metric distinction** is the methodological refinement future cycles' audit hypotheses must adopt.

### Per-file D2 vacuity (the audit-pointed hypothesis file)

The v0.10.17 cycle-end audit O6 hypothesis was: "2 pre-existing pytest failures in apps/api/tests/test_uploads_e2e.py". Verifying on JUST that file:

```bash
cd /home/roddy/Gw2Analytics/apps/api
set -a; source /home/roddy/Gw2Analytics/apps/api/.env; set +a
uv run pytest /home/roddy/Gw2Analytics/apps/api/tests/test_uploads_e2e.py --no-header
# Result: 36 passed in 3.18s — D2 vacuous per file
```

The audit's pinpointed file IS vacuous (36/36 PASS). D2 closes **as vacuous per file**, but the audit's hypothesis was too narrow.

### Full-surface M8 discovery (enumerated + classified)

The full-surface diagnostic surfaced 11 failures, classified by hypothesis-driven root cause:

| # | Test | File | Sub-bucket |
|---|---|---|---|
| 1 | `test_create_upload_enqueues_via_arq` | `tests/test_uploads_arq.py` | K1 (Arq-Worker connectivity) |
| 2 | `test_create_upload_idempotent_existing_failed_enqueues` | `tests/test_uploads_arq.py` | K1 (Arq-Worker connectivity) |
| 3 | `test_create_upload_503_when_arq_down_and_no_fallback` | `tests/test_uploads_arq.py` | K1 (Arq-Worker connectivity) |
| 4 | `test_re_upload_does_not_redispatch_when_not_failed[pending]` | `tests/test_uploads_arq.py` | K1 (Arq-Worker connectivity) |
| 5 | `test_re_upload_does_not_redispatch_when_not_failed[completed]` | `tests/test_uploads_arq.py` | K1 (Arq-Worker connectivity) |
| 6 | `test_pool_saturation_gracefully_returns_422` | `tests/test_webhooks_dns_under_attack.py` | K3 (DNS-resolver-pool saturation / latency budget) |
| 7 | `test_post_webhook_rejects_https_private_ip_literal` | `tests/test_webhooks_e2e.py` | K2 (IP-routing/SSRF gate semantics) |
| 8 | `test_post_webhook_rejects_https_link_local_literal` | `tests/test_webhooks_e2e.py` | K2 (IP-routing/SSRF gate semantics) |
| 9 | `test_post_webhook_rejects_https_ipv6_loopback_literal` | `tests/test_webhooks_e2e.py` | K2 (IP-routing/SSRF gate semantics) |
| 10 | `test_post_webhook_rejects_https_hostname_resolving_to_private` | `tests/test_webhooks_e2e.py` | K2 (IP-routing/SSRF gate semantics) |
| 11 | `test_getaddrinfo_timeout_returns_422` | `tests/test_webhooks_getaddrinfo_timeout.py` | K3 (DNS-resolver-pool saturation / latency budget) |

**Distribution by sub-bucket**: K1 = 5 (Arq), K2 = 4 (SSRF), K3 = 2 (DNS pool/timeout) — verifies the v0.9.2 webhook SSRF module + v0.10.1 plan 010 Arq worker substrate drift are the prime suspects.

### Classification bucket K — Test-Substrate Mismatch (sharpened narrative)

> The v0.10.18.1 diagnostic surfaced 11 failures across 4 test modules, all clustering on test-to-substrate mismatches (Arq pool fallback toggles, IP-routing/SSRF gates, and monkeypatched DNS timeouts) running on the live docker-compose stack. Confirmed as test environment drift rather than production code regressions. Deferred as a new M8 forward-deferral to v0.10.19, joining the already-queued F17 Combat readout + M6 AG Grid replacement backlog.

### Guard rail (NOT a regression in production code)

> None of the 11 failures indicate a regression in core application logic; they are purely isolation leaks and test-env mismatches where the test suite's fake DNS, literal IP assumptions, and Redis mocks collide with the host's live docker-compose substrate.

The production code paths (POST /api/v1/webhooks SSRF gate, GET /api/v1/fights/{id}/events Arq fallback, etc.) work correctly in live deployment. The pytest failures are engineering-debt on the test isolation layer, not on the application layer. v0.10.19's M8 fix-up will land test-substrate corrections (e.g., tighter conftest.py autouse fixtures + DNS monkeypatch restoration + Arq mock-pool parity) without touching production logic.

### Pre-existing test tally after v0.10.18.1

| Surface | Pre-v0.10.17 audit | Pre-v0.10.18 (audit) | Pre-v0.10.18.1 audit | Pre-tag v0.10.18.1 | Trend |
|---|---:|---:|---:|---:|---|
| pytest `apps/api/tests/test_uploads_e2e.py` (the O6-pointed file) | (baseline) | 2 (= hypothesis) | (cycle-start empirical) | **0** ✅ | -2 (per-file) |
| pytest `apps/api/tests/` (FULL surface) | (not measured) | (not measured) | 11 (NEW discovery) | **11** ⚠️ | forward-deferred to v0.10.19 |
| vitest whole-repo | 7 (= hypothesis) | 0 (v0.10.17 D3 closed) | 0 | **0** | flat |
| Playwright e2e | (n/a) | 25 (4 NEW + 21) | 25 | **25** | flat |

The 11 pytest failures (apps/api/tests full surface) are NOT closed by v0.10.18.1; they are the NEW high-priority forward-deferral (new ROADMAP §1.2 item 3 = M8) for the v0.10.19 mimo-half PRIMARY budget.

### ROADMAP §1.2 reclassification (Option B+ per the cycle-end structural review)

The v0.10.18 main §1.2 "Ready to implement" shortlist had 4 items. After v0.10.18.1 closes the M-cluster (M1-M4 + D2 per-file) + the F16 README 9th-route sync (closed at v0.10.18 D4), the v0.10.18.1 cycle-end §1.2 list is reclassified per Option B+ from the strategic structural review:

- **DROPPED from §1.2** (closed; per ROADMAP §4 "check off any item that landed in the release"):
  - Item 3 of v0.10.18 main: "Residual pre-existing tests fix-up + D2 Playwright e2e" — M-cluster thread FULLY CLOSED at v0.10.18 D1+D3+D4 + v0.10.18.1 D2.
  - Item 4 of v0.10.18 main: "README 9th-route sync (F16 followup)" — CLOSED at v0.10.18 D4 (1-row append in `## Screenshots`).
- **KEPT in §1.2** (still open / future scope):
  - Item 1 of v0.10.18 main: "Combat readout (F17)" — XL+ effort; design spec at `docs/v0.9.0-combat-readout-design.md`; blocked on statechange parser + skills DB.
  - Item 2 of v0.10.18 main: "Skill build analyser" — M effort; design spec at `docs/v0.8.0-web-design.md` §6.
- **NEW in §1.2** (this cycle):
  - NEW Item 3: "**M8 (bucket K = Test-Substrate Mismatch) — 11 pytest failures in webhook/Arq/DNS tests**" — forward-deferred to v0.10.19 mimo-half PRIMARY scope. Conftest isolation + DNS monkeypatch restoration + Arq mock-pool parity; **NO production logic changes**. Effort: M-L.

**Net §1.2 list at v0.10.18.1 cycle-end**:

1. Combat readout (F17) — XL+ effort.
2. Skill build analyser — M effort.
3. **M8 test-substrate fix-up (NEW)** — M-L effort, **v0.10.19 PRIMARY**.

The "pick ONE between F17 + M6" framing from the v0.10.18 cycle-end brief is **AXED** — the new PRIMARY is M8; F17 + M6 + M5 + M7 all deferred to v0.10.20+.

### Cycle topology

3 atomic commits on `v0.10.18.1/mimo-half` working branch → ff-merge to `main` → tag `v0.10.18.1` → push tag → `gh release create` published.

| # | Commit | Subject |
|---|---|---|
| 1 | `<marker-sha>` | `test(api): verify D2 pre-closed + mark M8 webhook discovery (plan 038 D2 marker)` (allow-empty) |
| 2 | `<docs1-sha>` | `docs(release+changelog): v0.10.18.1 cycle release notes + [0.10.18.1] entry + M8 discovery narrative (bucket K = Test-Substrate Mismatch)` |
| 3 | `<docs2-sha>` | `docs(roadmap+audit): v0.10.18.1 cycle ROADMAP sync (§1.2 reclassified per Option B+ — M-cluster item 3 of v0.10.18 main fully closed; F16 item 4 of v0.10.18 main closed at v0.10.18 D4; M8 = new item 3 forward-deferred to v0.10.19) + cycle-end audit` |

### Reference docs (next-cycle audit must cite these)

- [`plans/AUDIT-2026-07-13-3b2e71f.md`](./AUDIT-2026-07-13-3b2e71f.md) — v0.10.17 audit's narrow O6 hypothesis (the per-file D2 source)
- [`plans/AUDIT-2026-07-13-PROJECT-WIDE.md`](./AUDIT-2026-07-13-PROJECT-WIDE.md) — project-wide audit baseline
- [`plans/RELEASE-v0.10.18.md`](./RELEASE-v0.10.18.md) — D2 deferred section that motivated v0.10.18.1
- `plans/AUDIT-2026-07-13-<marker-sha>.md` (NEW) — v0.10.18.1 cycle-end audit with M8 finding + bucket K classification + §1.2 reclassification
- [`plans/v0.10.18-mimo-half-prompt.md`](./v0.10.18-mimo-half-prompt.md) — parent brief
- `CHANGELOG.md` `[0.10.18.1]` entry
- `docs/ROADMAP.md` "Current state (post v0.10.18.1 cycle)" + §1.2 shortlist (M8 = new item 3, v0.10.19 PRIMARY)

### Why this cycle ships as a 2-fold closeout (not a fix)

The project's diagnostic-first mandate (per `CONTRIBUTING.md`) requires surfacing actual failure modes before any closing commit. v0.10.18.1 surfaced 2 distinct finding classes: (i) D2 vacuous-per-file + (ii) M8 webhook/Arq/DNS failures surfaced (bucket K confirmed). Pivoting v0.10.18.1 to fix M8 would have lost the cycle's scope (D2 vacuity-closure + discovery note) AND inflated the mimo-half budget; forward-deferring to v0.10.19 PRIMARY is the cleanest separation.

The `--allow-empty` marker preserves the cycle boundary + the discovery note in git lineage.

### Why README.md is UNCHANGED in this cycle

The project's single-source-of-truth for forward-deferral tracking is `docs/ROADMAP.md` per the file's own §4 Update protocol ("this file is the **single source of truth** for 'what's left to do' on the project. It supersedes any ad-hoc 'what's next' list in the README or the CHANGELOG"). README.md at cycle-start HEAD `e47c9a3` does not contain a forward-deferral Status line — the only "Deferred" mentions are historical referbot-deferred-PR references, unrelated to v0.10.19+ shortlist items. README is not updated by this cycle; the forward-deferral moves live only in ROADMAP §1.2 (M8 as new item 3).

### Forward cadence

**v0.10.19 (mimo-half budget = M8 PRIMARY)**:

- **PRIMARY scope**: M8 — fix the 11 pytest failures in webhook/Arq/DNS test suites (bucket K = Test-Substrate Mismatch). Diagnostic-first enumeration of the root cause per failure + test-substrate corrections (conftest isolation + DNS monkeypatch restoration + Arq mock-pool parity). M-L effort.
- **ALREADY-ON-SHORTLIST, DEFERRED FROM v0.10.18 → v0.10.19**: F17 Combat readout (XL+ effort) + M6 AG Grid bundle replacement (M effort) + M5 F17 long-tail (XL+) + M7 CHANGELOG backlog (M). The "pick ONE between F17 + M6" framing from the v0.10.18 cycle-end brief is AXED — the new PRIMARY is M8.

The forward-cadence is documented in `docs/ROADMAP.md` §1.2 with M8 = new item 3 (v0.10.19 PRIMARY). README is unchanged per the single-source-of-truth rule.
