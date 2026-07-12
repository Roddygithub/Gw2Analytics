# Release v0.10.20 — M8 test-substrate fix-up (PRIMARY 1-iteration budget)

**Cycle:** v0.10.20 `mimo-half` (forward-deferred from v0.10.19 mimo-half).
**Marker commit SHA:** TBD at cycle-execution start (`--allow-empty` v0.10.20 cycle-window marker).
**Cycle-end audit filename convention:** `plans/AUDIT-2026-07-<cycle-end-date>-<marker>.md`.

---

## §1 — Cycle thread (the four-cycle logical unit)

| Cycle | Phase | Output |
|---|---|---|
| v0.10.18 | main scope | CHANGELOG reorder (K counts post-v0.10.18 closeout) + ROADMAP §1.2 Option B+ M8 placement |
| v0.10.18.1 | mimo-half follow-up | Lock-in v0.10.18 close-out; place M8 ↔ ROADMAP §1.2; close-out audit at `plans/AUDIT-2026-07-13-2ffafc75.md`; K1+K2+K3 discoverer |
| v0.10.19 | mimo-half M8 attempt + DEFER | plan-landing docs at `712522a`; 6 iterations on conftest.py exhausted signature budget; DEFER close-out audit at `plans/AUDIT-2026-07-12-cd6e9ad.md`; CHANGELOG `[0.10.19]` spliced |
| **v0.10.20** | **mimo-half M8 PRIMARY (this plan)** | 1-iteration budget on PR-1 (Arq mock) + PR-2 (DNS per-test pool) + PR-3 (SSRF network namespace stub); cycle-end audit at `plans/AUDIT-2026-07-<date>-<marker>.md` |

---

## §2 — Sub-deliverables (3-PR split inside the 1-iteration budget)

### PR-1 — K1: Arq-Worker connectivity (5 failures in `tests/test_uploads_arq.py`)

**Target:** the 5 failures in `tests/test_uploads_arq.py` (forward-discovered at v0.10.18.1; unmitigated at v0.10.19 due to lost PR-3 closure).

**Sub-task:**
- Rescue `mock_arq_pool` fixture so that it installs AFTER `client` (TestClient lifespan) runs. The v0.10.19 mimo-half PR-3 (`mock_arq_pool(client: TestClient)` dependency) was discarded under DEFER — re-apply here.
- Verify each of the 5 K1 failures opens with the post-lifespan mock installed AND the per-test `monkeypatch.delenv("ALLOW_INREQUEST_PARSE_FALLBACK", raising=False)` is the ONLY env-isolation branch used (no dotenv source).

**Acceptance criteria:**
- `tests/test_uploads_arq.py` passes 5/5.
- No regression on `tests/test_uploads_e2e.py` (D2 baseline stays 36/36 green in 3.18s).

### PR-2 — K3: DNS-resolver-pool saturation (2 failures)

**Target:** the 2 failures in `tests/test_webhooks_dns_under_attack.py` + `tests/test_webhooks_getaddrinfo_timeout.py`.

**Sub-task:**
- Re-apply `v0.10.19/mimo-half` PR-2: add `_isolate_dns_executor` autouse fixture that `monkeypatch.setattr(webhooks, "_DNS_EXECUTOR", ThreadPoolExecutor(max_workers=1, ...))`. Per-test pool forces serial DNS lookups, which triggers the 2.0s `future.result(timeout)` fence for the saturation test's 100-tarpit burst + the per-test timeout test.
- Use the hardened `apps/api/scripts/cycle_closeout_apply_docs.py` style for production-safety (no `assert`-stripped guards; explicit `raise SystemExit(...)` instead).

**Acceptance criteria:**
- `tests/test_webhooks_dns_under_attack.py` passes 2/2 (down from 1/2 currently + 1 ERROR setup-time); `tests/test_webhooks_getaddrinfo_timeout.py` passes 2/2.
- No regression on `test_webhooks_e2e.py` 22/22 baseline.

### PR-3 — K2: IP-routing/SSRF gate semantics (4 failures in `tests/test_webhooks_e2e.py`)

**Target:** the 4 SSRF-gate failures (`test_post_webhook_rejects_https_private_ip_literal` + `test_post_webhook_rejects_https_link_local_literal` + `test_post_webhook_rejects_https_ipv6_loopback_literal` + `test_post_webhook_rejects_https_hostname_resolving_to_private`).

**Sub-task:**
- Add `_isolate_webhook_validation_env` autouse fixture that `monkeypatch.delenv("GW2ANALYTICS_ALLOW_PRIVATE_WEBHOOK_URLS", raising=False)`.
- **CRITICAL FIX for v0.10.20 (the v0.10.19 lesson):** the v0.10.19 conftest.py's `_disable_dotenv_for_tests` autouse fixture attempted to patch `Settings.settings_customise_sources` to omit the `DotEnvSettingsSource` — but the `assert`-based guards + signature mismatches across 6 iterations. v0.10.20 MUST use the production-safety pattern (no `assert`, no silent fallback, correct 7-arg signature with `settings_cls` as 2nd positional per pydantic-settings actual call).
- Or, simpler (preferred): drop the `_disable_dotenv_for_tests` autouse fixture entirely and use a `Settings(_env_file=None)` construction via a wrapped `get_settings` factory in conftest.

**Acceptance criteria:**
- All 4 `_rejects_https_private_ip_*` test variants pass.
- No regression on the broader `test_webhooks_e2e.py` 22-test surface.

---

## §3 — Cycle topology (5 commits per v0.10.18.1 + v0.10.19 convention)

| Commit | Purpose |
|---|---|
| `<marker>` | `--allow-empty` cycle-window marker |
| `pr1` | conftest `_isolate_arq_mock_pool` fixture (K1 fix) |
| `pr2` | conftest `_isolate_dns_executor` autouse fixture (K3 fix) |
| `pr3` | conftest `_isolate_webhook_validation_env` + `_disable_dotenv_for_tests` (K2 fix) OR the simpler `Settings(_env_file=None)` wrapper |
| docs1 | CHANGELOG `[0.10.20]` splice (M8 closed + 1-iteration budget summary) |
| docs2 | ROADMAP §1.2 M8 reclassification (M8 status -> closed) |
| audit | `plans/AUDIT-2026-07-<date>-<marker>.md` cycle-end audit |

---

## §4 — Risk register

1. **Re-introducing the 6-iteration signature-budget trap.** The v0.10.19 mimo-half's `_disable_dotenv_for_tests` autouse fixture caused 6 iterations on the `Settings.settings_customise_sources` signature shape. v0.10.20's PR-3 MUST either:
   - (a) use the hardened `apps/api/scripts/cycle_closeout_apply_docs.py` pattern (no `assert`; explicit `if not X: raise SystemExit(X)`).
   - (b) drop `_disable_dotenv_for_tests` entirely and use a `Settings(_env_file=None)` wrapper construction.

   Recommendation: (b) — the simpler path.

2. **PR-3's `monkeypatch.delenv` + `monkeypatch.setenv` + `monkeypatch.delenv` stack race.** When `_disable_arq_for_tests` autouse setenvs `ALLOW_INREQUEST_PARSE_FALLBACK=1`, then PR-3's `_isolate_webhook_validation_env` concurrently delenvs, then per-test `monkeypatch.delenv` removes it — pytest's LIFO monkeypatch undo at teardown must restore all 3 layers consistently. The `_clear_settings_cache` autouse fixture already wraps setenv/delenv with `get_settings.cache_clear()`. The contract is sound; verify with per-test Settings() introspection logs if needed.

3. **Substrate baseline preservation.** `tests/test_uploads_e2e.py` MUST stay 36/36 green throughout. M8 close-out's positive acceptance criteria is "0 / 11 → 11 / 11" on the K-cluster WITHOUT breaking any D2 surface.

---

## §5 — Cross-references

- **Prior v0.10.19 mimo-half DEFER audit**: `plans/AUDIT-2026-07-12-cd6e9ad.md` (this cycle's INPUT).
- **Prior v0.10.18.1 cycle-end audit (K-discoverer)**: `plans/AUDIT-2026-07-13-2ffafc75.md`.
- **Closure thread retrospective**: `plans/AUDIT-2026-07-13-RETROSPECTIVE-V01017-V010181.md` (v0.10.17 → v0.10.18 → v0.10.18.1).
- **Prior v0.10.19 release plan** (this plan's structural template): `plans/RELEASE-v0.10.19.md` (M8 fix-up PRIMARY plan v0.10.19 attempted).
- **F17 sizing spike**: `docs/v0.10.19-combat-readout-spike.md` (forward-deferred blocker for F17 itself; M8 is INDEPENDENT of F17).
- **M9 pre-commit hook race fix** (forward-prep for this cycle's close-out): `plans/M9-pre-commit-hook-race-fix.md`.
- **ADR 002 (statechange parser extension Phase 9 step 4)**: `plans/adr/002-statechange-parser-extension.md` (F17 forward-blocker, locked at v0.10.21+).
- **Hardened cycle close-out script** (replaces ad-hoc /tmp script on future cycle close-outs): `apps/api/scripts/cycle_closeout_apply_docs.py`.
- **Smoke test for the close-out script**: `apps/api/tests/test_cycle_closeout_apply_docs.py`.

---

## §6 — Cycle-execution checklist (close-out time)

At the end of the v0.10.20 mimo-half cycle, the executor MUST verify:

1. `pytest tests/test_uploads_e2e.py` → 36/36 green (D2 baseline preserved).
2. `pytest tests/test_uploads_arq.py` → 5/5 green (K1 closed).
3. `pytest tests/test_webhooks_e2e.py` → 22/22 green (K2 closed).
4. `pytest tests/test_webhooks_dns_under_attack.py tests/test_webhooks_getaddrinfo_timeout.py` → 4/4 green (K3 closed).
5. `pytest tests/test_webhooks_dns_executor_concurrency.py` → pass (the 3 DNS-concurrency-specific tests; not in v0.10.18.1 K-cluster but in same surface area).
6. Full surface `pytest tests` → 297/297 green (1 skipped unchanged from D2).
7. `ruff check` + `mypy --no-incremental` on the modified `apps/api/tests/conftest.py` + new scripts + new tests → clean.
8. CHANGELOG `[0.10.20]` entry spliced with K-cluster closed language.
9. ROADMAP §1.2 M8 row reclassified from "M8 (Test-Substrate Mismatch fix-up)" PENDING to "M8 (test-substrate fix-up)" CLOSED.
10. Cycle-end audit authored with the standard 5-section structure (Executive Summary + §1 Cycle topology + §2 K-cluster closed rationale + §3 Validation matrix + §4 Cross-references).
11. Annotated tag `v0.10.20` + force-push + `gh release create`.
