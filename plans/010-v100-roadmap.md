# 010 - v0.10.0 roadmap

**Author:** forward-looking scope from `docs/ROADMAP.md` §1 + §2 + §3 after the v0.9.0 close-out (commit `f5e8667` + `baabe53` + `d07a09c` now live on `origin/main`; tag `v0.9.0` pushed).

**Status:** scoping (no implementation yet). Each item below has a `### Why now` block + an effort estimate + a recommended executor; a maintainer can pick the top 1-3 as the v0.10.0 cycle's scope.

## Recommended scope (pick 1-3)

### A. Webhook secret-at-rest encryption (deferred from v0.9.1)

**Source:** `CHANGELOG.md` `### Deferred (v0.9.2 followups)` → `**webhook secret-at-rest**`.

**Why now:** the connector partner who onboards in the next month adds the threat-model that needs this layer. The shipped v0.9.1 webhook accepts the threat "plain secret in the operator-led-DB-compromise scenario" but deferred the fix; the v0.9.X hardening slice closed HMAC byte-for-byte + replay idempotency + secret-at-rest $$RENAME$$→ wait, secret-at-rest remains deferred. v0.10.0 is the natural cycle to close this.

**Effort:** S. The v0.9.1 deferred note suggests `pgcrypto` envelope encryption with a `SECRETS_KEK` env var. Single new migration + 1 `__init__.py` KEK loader + 1 helper + per-route `_decrypt_secret()` call on HMAC verify. 5 NEW hermetic tests (encrypt + decrypt round-trip + 3 invalid-KEK paths).

**Why now (deeper):** the v0.9.0 hardening close-out (plan 041 in `plans/README.md`) introduced `SecretStr` for route-layer ergonomics (no log leak) but did NOT add at-rest encryption. The natural complement is at-rest encryption; the gap is "the SQL row is still plaintext" + "the HMAC signature requires plaintext copy". Closing the at-rest layer is the v0.10.0 prerequisite for a real defensive posture.

### B. Cross-account comparison (M effort, web UX)

**Source:** `docs/ROADMAP.md` §1 → `**Cross-account comparison** — overlay 2-4 accounts' timelines on the same chart`.

**Why now:** the v0.8.0 player timeline shipped single-account only. The squad-comparison use case (e.g. "how does my DPS compare to my healer's damage absorbed over the same fight window?") is the most-requested feature in the maintainer's incident log. Reuses `PlayerTimelineChart` from v0.8.0 + extends `PlayerTimelineSection` with a multi-series overlay mode.

**Effort:** M. 1 NEW `<CrossAccountSection>` Client Component wrapper + 1 NEW `fetchPlayerTimelineMulti(accountNames)` API client + 1 NEW `GET /api/v1/players/{account_names}/timeline` route (comma-joined account names) + 1 NEW vitest case on the chart wrapper + 1 NEW e2e spec + 1 NEW upload-multifight paginated test.

**Dependencies:** depends on v0.8.0's `PlayerTimelineChart` (✅ shipped) + `fetchPlayerTimeline` (✅ shipped). Independent of A.

### C. Webhook at-rest encryption OR CSV injection guard (security HIGH)

**Source:** `plans/README.md` v0.9.9 audit → `030-v099-csv-injection-fix.md` (**pending**).

**Why now:** OWASP CWE-1236 (`=`, `+`, `-`, `@`, `\t`, `\r` formula triggers in Excel / Sheets). The analyst CSV export flow lets a malicious `name` / `skill_name` / `subgroup` uploaded by a hostile party execute a formula on the analyst's local machine. Currently mitigated by the upload API's `.zevtc`-extension guard (which blocks binary upload) but the parsed `name` field is unfiltered on the export.

**Effort:** S. 1 NEW `FORMULA_TRIGGERS` regex in `web/src/lib/csv.ts` + 1 NEW `csvEscape` body + 12 NEW hermetic tests on `csv.test.ts`. Independent of A + B.

## Deprioritised (deferred to v0.10.1+ or v0.11.0)

- **Combat readout (XL+)** (`docs/v0.9.0-combat-readout-design.md`) — blocked on the statechange parser + skills DB. The blocked reason is unchanged; deferring until either blocker lifts.
- **Skill build analyser (M)** — reuse of `SkillUsageTable` from v0.7.1; valuable UX but blocked on the EVTC loadout parser (no `.zevtc` field carries loadout bytes; would require arcdps' separate log file).
- **Real-time DPS meter (XL)** — WebSocket + auth + reconnect + partial-parse; own dedicated cycle.
- **PNG / SVG export** (`docs/ROADMAP.md` §3) — defer until CSV injection guard is in (the export surface widens the threat).

## Recommended execution order

1. **C (CSV injection guard)** — S effort, security HIGH, defensive in depth. Independent of A + B. Closes the OWASP attack on the existing export surface.
2. **A (Webhook secret-at-rest)** — S effort, the deferred-item hardening. Depends on the v0.9.1 already-shipped HMAC byte-for-byte + the v0.9.0 `SecretStr` ergonomic layer; v0.10.0 closes the at-rest layer.
3. **B (Cross-account comparison)** — M effort, the UX win for squad-comparison. Independent of A + C.

All 3 are PR-friendly. Could ship in 3 separate PRs OR as one combined "v0.10.0 hardening + UX" cycle PR if the maintainer prefers a single signed tag.

## Rejected alternatives

- **Bundle all 3 into one mega-plan**: tempting (single release tag). The 3 plans touch 3 different files (`web/src/lib/csv.ts` + `apps/api/src/gw2analytics_api/routes/webhooks.py` + `web/src/components/PlayerTimelineSection.tsx`); bundling would conflate the security-debt invariant (A + C) with the UX invariant (B), making any one of them harder to revert if regressed.
- **Skip C in favour of A**: tempting (both are security). C is HIGHER severity (OWASP CWE-1236 is publicly known; many CVEs list it). A is deferred-debt closure (predates C in priority). The plan ships C first.
- **Move B into v0.10.1**: tempting (defer the M-effort UX). B's primary risk is implementation churn; a v0.10.0 cycle scope of all 3 should be re-estimated after C closes.

## See also

- `docs/ROADMAP.md` §1 — the canonical v1.0 candidate list (the candidates A / B / C above are the 3 highest-priority from §1 + the deferred list).
- `plans/README.md` — the senior-advisor audit history + the per-cycle plan index. Plan 030 (CSV injection) + Plan 041 (SecretStr) are both indexed there.
- `CHANGELOG.md` `### Deferred (v0.9.2 followups)` — the formal may-not-ship_without-this-blocker items.
