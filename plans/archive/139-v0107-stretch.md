# plans/139 — v0.10.7 stretch tracking checklist (updated post-Fix-A)

**Status as of session end:** main HEAD = `955116b` (PR-ready, PARITY YES with `origin/main`).
- `92ddeeb` — S3 mock fixture (closed 26 `InvalidAccessKeyId` failures)
- `97cd08a` — `.github/CODEOWNERS` expansion
- `6d58ab2` — plans/139 stub (this file)
- `955116b` — Fix-A: `_make_cbtevent` struct.pack arg count 23→22 in `test_fight_rollup_cap.py`

---

## Fix-A outcome (post-commit, v0.10.8 plan 140)

**Original hypothesis (WRONG for the abort criterion):** pytest total fails would drop from 17 → ~13.

**Actual outcome:** pytest total fails stayed at **17**, BUT the *failure mode shifted*:
- `test_fight_rollup_cap.py`: 4 failures went from `struct.error: pack expected 22 items for packing (got 23)` to `TypeError: a bytes-like object is required, not 'MagicMock'`.
- The struct.pack fix WAS structurally correct — `struct.calcsize(_EVENT_FMT) == 64` and the helper now passes 22 args matching 22 format codes. The MagicMock-BytesIO error was always underneath; the struct.error now masks nothing.
- The file `test_uploads_e2e.py` has the SAME 22-arg helper and the SAME MagicMock-BytesIO failure (its 4 failures are unrelated to struct.pack).

**Net result of Fix-A:** 1 real bug eliminated (the 23-arg helper), 0 net pytest change. Acceptable trade-off because the underlying MagicMock-BytesIO issue is Fix-B's problem (one fix kills both clusters).

---

## Deferred items (next agent / next session)

### Fix-B: FakeMinio S3 read-path mock (medium risk)

**Goal:** drop 17 → ~9 total pytest failures (clears `test_uploads_e2e.py` 4 + `test_fight_rollup_cap.py` 4).

**Scope:** `apps/api/tests/conftest.py` only (replace the bare `MagicMock` returned by `_mock_s3` with a `FakeMinio` class that stores bytes on `put_object` and returns `BytesIO(stored_bytes)` on `get_object(...).read()`).

**Recipe:**
1. Replace the body of the `_mock_s3` autouse fixture with a `FakeMinio` class implementing:
   - `put_object(bucket, object_name, data, length, **kw)` — `data.read()` → `_storage[object_name]`
   - `get_object(bucket, object_name, **kw)` — return `_FakeHttpResponse(_storage[object_name])` where `_FakeHttpResponse.read() -> bytes`, `.close() -> None`
   - `bucket_exists(bucket)` — `_buckets.add(bucket)` on `make_bucket`, return `bucket in _buckets`
   - `remove_object(bucket, object_name)` — `_storage.pop(object_name, None)`
2. Also raise `S3Error(...)` (real `minio.error.S3Error`) on `get_object` for non-existent objects to match the production behavior the routes rely on.

**Risks:**
- Test that depends on MinIO retry/backoff surface might explode (no such test exists in the suite per pre-Fix-A grep).
- Test that asserts on `get_object` arg shape might break (the conftest's `monkeypatch.setattr` returns the FakeMinio instance, not a MagicMock, so any `MagicMock.assert_called_once_with(...)` deep-inspection pattern would break — check if any test uses such a pattern via `grep "minio.*assert" apps/api/tests/`).

### Fix-C: per-test TestClient fixture (high risk)

**Goal:** drop ~9 → ~3 total pytest failures (clears `test_player_compare.py` 5 + `test_main_mount_order.py` 1).

**Scope:** `apps/api/tests/conftest.py` (extend `client` fixture with `with TestClient(app) as c: yield c`) + AT LEAST 3 test files that declare module-level `client = TestClient(app)` (`test_player_compare.py`, `test_uploads_e2e.py`, `test_main_mount_order.py`, `test_fight_rollup_cap.py`).

**Recipe:**
1. In `conftest.py`, change `client` fixture from `return TestClient(app)` to `with TestClient(app) as c: yield c` (proper lifespan entry/exit).
2. In each affected test file, REMOVE the module-level `client = TestClient(app)` line AND add `client: TestClient` as a parameter to each test function signature.
3. The fix is invasi ve but mechanical — every test that uses `client.get(...)` / `client.post(...)` becomes `def test_x(client: TestClient) -> None:` with the body unchanged.

**Risks:**
- Tests that intentionally share `client` state across tests (probably none per the conftest's `_isolate_test_state` autouse), would break.
- The TestClient lifespan itself hits the schema-drift guard — if test DB lacks the `alembic_version` row, all tests fail with `RuntimeError` until `SKIP_SCHEMA_GUARD=1` setdefault is added *back* (mild regression risk).

### Fix-D: small-cluster bug fixes (low risk)

**Goal:** drop ~3 → ~0 total pytest failures (clears `test_backfill.py` 2 + `test_backfill_eoferror.py` 1).

**Scope:** likely `apps/api/src/gw2analytics_api/backfill.py` + related tests. The backfill_eoferror test monkeypatches `gw2analytics_api.storage.get_events` with a truncated gzip blob — this works only if `run_backfill` references `storage.get_events` via a *live* attribute lookup, not a module-local binding.

**Recipe:**
1. Investigate `git log --all --oneline -- apps/api/src/gw2analytics_api/backfill.py` for the post-5556 sequence; the regression is likely in a refactor that moved the `from gw2analytics_api.storage import get_events` import to a module-local binding (no longer monkeypatchable).
2. Switching back to a delayed lookup (`storage.get_events(...)` inside `_backfill_one_fight`) restores the monkeypatch path.
3. The 2 `test_backfill.py` failures may be the same root cause (separate test, same module) — fixing Fix-D likely clears both.

---

## Summary checklist for next agent

| # | Item | Branch | Commit | Risk |
|---|---|---|---|---|
| Plan 136 (port-5432) | ✅ merged | `9f70aaf` | low (setup-tear-down) | — |
| Plan 137 (CODEOWNERS A0) | ✅ merged | `97cd08a` | low (config-only) | — |
| Plan 138 (dependabot dev-dep bump) | ✅ merged | — | low (dev-dep) | — |
| Plan 139 stub (this file) | ✅ merged | `6d58ab2` | low (doc-only) | — |
| Plan 140 Fix-A (struct.pack) | ✅ merged | `955116b` | low (1-line cosmetic) | 0 |
| Plan 140 Fix-B (FakeMinio) | ⏳ deferred | TBD | medium (conftest mock) | 17→9 |
| Plan 140 Fix-C (TestClient fixture) | ⏳ deferred | TBD | high (3+ test files) | 9→3 |
| Plan 140 Fix-D (backfill cluster) | ⏳ deferred | TBD | low (single module) | 3→0 |
| 7 dependabot PRs (plans/135) | ⏳ user-driven | — | medium-high (per PR) | n/a |

**Next session entry point:** start with Fix-B (lowest regression-risk-per-payoff), then Fix-C, then Fix-D, then process the 7 dependabot PRs in risk order (#12 uvicorn → #14 mypy → ag-grid pair → redis + jsdom + @types/node).

**Note to next agent:** the 2 prior `c703ba0` (S3-refine) and `53644e9` (SKIP_SCHEMA_GUARD) commits both regressed and were reverted via `git reset --hard HEAD~1`. Read this file before touching conftest.py.
