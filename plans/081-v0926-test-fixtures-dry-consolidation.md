# Plan 081 — v0.9.26 — `apps/api/tests/test_players.py` `_make_cbtevent` + `_make_minimal_zevtc` locally-duplicated helpers → shared `_fixtures.py`

**Drift base:** `44ea862` (origin/main HEAD at audit time)
**Addressed finding (LOW DX + cleanup):** `apps/api/tests/test_players.py` has local copies of `_make_cbtevent` + `_make_minimal_zevtc` that are byte-for-byte duplicates of the same-named helpers in `apps/api/tests/test_uploads_e2e.py`. The duplication is documented in the docstring: "Local copy of :func:`test_uploads_e2e._make_cbtevent` to keep this test file self-contained (avoids an import dependency on the e2e module's private helpers)." The rationale ("avoid import dependency") is a v0.8.x holdover; in v0.9.x there is already an `apps/api/tests/_fixtures.py` module that exports `make_cbtevent` + `post_minimal_fight` for the v0.8.5 backfill tests + the v0.8.6 health-summary tests.

Move the two helpers from `test_uploads_e2e.py` to `_fixtures.py` (rename to `make_cbtevent` + `make_minimal_zevtc` for consistency with the existing `make_cbtevent` export), then update the 2 consumers:
- `test_uploads_e2e.py` — drops the local copies + imports from `_fixtures.py`
- `test_players.py` — drops the local copies + imports from `_fixtures.py`

The result: 1 source of truth for the wire-format helpers → 3 callers (the existing `post_minimal_fight` test fixture + `test_uploads_e2e.py` + `test_players.py`). A future maintainer who changes the EVTC struct layout (e.g., to add a field) updates 1 file, not 3.

The canonical counterpart of `make_minimal_zevtc` in `_fixtures.py` is the existing `post_minimal_fight` helper which the v0.8.5 + v0.8.6 tests already import. The new `make_minimal_zevtc` (a pure pack function with no side effects) + `make_cbtevent` (pure struct pack) are the low-level building blocks; `post_minimal_fight` is the high-level wrapper that adds the POST + wait-for-completion. The plan adds the 2 missing low-level helpers without changing the high-level one.

## File changes

### 2 files edited + 1 NEW test file + 0 NEW modules

**`apps/api/tests/_fixtures.py`** — currently exports `make_cbtevent` + `post_minimal_fight`. Add the missing `_make_minimal_zevtc` helper (renamed to `make_minimal_zevtc` for naming consistency):

```diff
 def make_cbtevent(
     time_ms: int,
     src: int,
     dst: int,
     value: int,
     skill_id: int,
     *,
     is_statechange: int = 0,
     is_nondamage: int = 0,
     buff_dmg: int = 0,
 ) -> bytes:
     """Pack one 64-byte cbtevent record matching the parser's struct layout.
     [existing docstring]
     """
     return struct.pack(_EVENT_FMT, ...)

+def make_minimal_zevtc(
+    agents: list[tuple[int, int, int, str, bool]],
+    build: str,
+    skills: list[tuple[int, str]] | None = None,
+    events: list[bytes] | None = None,
+) -> bytes:
+    """Build a synthetic .zevtc blob (zip wrapper around EVTC).
+    [canonical docstring ported from test_uploads_e2e.py]
+    """
+    if skills is None:
+        skills = []
+    if events is None:
+        events = []
+    buf = BytesIO()
+    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
+        header = struct.pack(_HEADER_FMT, ...)
+        # [body building...]
+        zf.writestr("fight.evtc", header + bytes(body))
+    return buf.getvalue()
```

The struct format constants (`_HEADER_FMT` + `_HEADER_SIZE` + `_AGENT_RECORD_FMT` + `_AGENT_PREFIX_SIZE` + `_AGENT_NAME_SIZE` + `_AGENT_SIZE` + `_SKILL_HEADER_FMT` + `_SKILL_HEADER_SIZE` + `_EVENT_FMT` + `_EVENT_SIZE`) are all moved to `_fixtures.py` as the canonical wire-format constants. The 2 helper functions depend on them.

**`apps/api/tests/test_uploads_e2e.py`** — current 700+ line file. Remove the local `_HEADER_FMT` / `_AGENT_RECORD_FMT` / `_SKILL_HEADER_FMT` / `_EVENT_FMT` constants (all moved to `_fixtures.py`). Remove the local `_make_cbtevent` + `_make_minimal_zevtc` definitions (re-exports of `_fixtures.py`). Add 1 import line at the top:

```diff
+from _fixtures import (
+    make_cbtevent,
+    make_minimal_zevtc,
+)
```

The 12 test functions in `test_uploads_e2e.py` don't change (they call `make_cbtevent` + `make_minimal_zevtc` which now resolve to the canonical `_fixtures.py` versions).

**`apps/api/tests/test_players.py`** — current 350+ line file. Remove the local `_make_cbtevent` + `_make_minimal_zevtc` definitions (the ones the docstring explicitly admits are "Local copy of :func:`test_uploads_e2e._make_cbtevent` to keep this test file self-contained"). Add 1 import line at the top:

```diff
+from _fixtures import (
+    make_cbtevent,
+    make_minimal_zevtc,
+)
```

The 7 test functions in `test_players.py` don't change (they call `make_cbtevent` + `make_minimal_zevtc` which now resolve to the canonical `_fixtures.py` versions).

### NEW `apps/api/tests/test_fixtures.py` — 6 hermetic tests

The fixtures are pure functions with no DB / Postgres dependency; the tests are hermetic + fast.

| # | Test | Asserts |
|---|---|---|
| 1 | `make_minimal_zevtc([])` returns a non-empty bytes blob | Empty-agents call doesn't crash; the header is valid EVTC (4-byte magic = `b"EVTC"`) |
| 2 | `make_minimal_zevtc(agents=[(1, 0, 0, "Test", True)], build="0", events=[])` round-trips through a `zipfile.ZipFile` read | The wrapper zip is valid; the inner `fight.evtc` file decodes to a 25-byte header + 96-byte agent record |
| 3 | `make_cbtevent(1500, 100, 200, 1234, 1000)` returns exactly 64 bytes | The 64-byte record size invariant (Phase 8 v1 wire contract) |
| 4 | `make_cbtevent` with `is_nondamage=1` + `value=800` + `buff_dmg=300` produces a record where the `is_nondamage` byte is `1` + the `buff_dmg` int32 is `300` | The dual-emit record (Phase 8) round-trips correctly |
| 5 | Two `make_minimal_zevtc` calls with different uuid-derived agent ids return DIFFERENT blobs (byte-for-byte) | The fixture is deterministic + unique per invocation |
| 6 | The 3 callers (`test_uploads_e2e.py` + `test_players.py` + `_fixtures.py`'s own users) all `from _fixtures import make_cbtevent, make_minimal_zevtc` | AST-based assertion: parse each test file as Python AST, find an `ImportFrom` whose `module == "_fixtures"` and whose names include both `make_cbtevent` and `make_minimal_zevtc` |

## Considered and rejected

- **Alternative: leave the duplicated copies + add a docstring cross-reference** (status quo + a TODO) — the cross-reference doesn't change the maintenance burden (3 sites to update on a wire-format change).
- **Alternative: move ONLY `make_cbtevent` (the 64-byte struct pack) to `_fixtures.py` + keep `make_minimal_zevtc` per-file** — the per-file `make_minimal_zevtc` instances still duplicate the 18 lines of agent/skill/event-appending logic. The plan moves BOTH helpers atomically.
- **Alternative: rename `_fixtures.py::make_cbtevent` to `_fixtures.py::_make_cbtevent` (underscore-prefix for "private")** — the existing `_fixtures.py::make_cbtevent` is exported without an underscore (it's used by `test_backfill.py` + `test_health_summary.py` + future tests), so the new plan matches the existing naming convention.
- **Alternative: drop the high-level `post_minimal_fight` wrapper + inline it in the 3 callers** — the high-level wrapper is the canonical "2-line POST + wait-for-completion" helper; inlining would clutter 4 test functions with the same 30-line wait-for-completion pattern.
- **Alternative: extract the wire-format struct constants to a new `_evtc_layout.py` module** — over-engineered for 10-line constants; the existing `_fixtures.py` is the canonical "test helpers" module + the constants logically live with the functions they parameterize.

## Effort

`S` — 2 file edits (test_uploads_e2e.py drops 2 helpers + 18 lines of constants; test_players.py drops 2 helpers + ~80 lines; _fixtures.py gains 2 helpers + 18 lines of constants) + 1 NEW test file (6 hermetic tests). Net code change is negative (more lines deleted than added). Plan 005 (the existing conftest consolidation v0.9.2 plan 029 Step 5) set the precedent for test-facility consolidation. Independent of plans 080 + 082.
