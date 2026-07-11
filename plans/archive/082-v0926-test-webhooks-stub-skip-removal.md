# Plan 082 — v0.9.26 — `apps/api/tests/test_webhooks_e2e.py` `pytest.skip()` stub removal (canonical implementation in `test_webhooks_e2e_scheduler.py`)

**Drift base:** `44ea862` (origin/main HEAD at audit time)
**Addressed finding (LOW DX + cleanup):** `apps/api/tests/test_webhooks_e2e.py` has a `test_retry_scheduler_failure_promotes_to_dlq_after_max_attempts` function that does NOTHING except `pytest.skip(...)`. The skip message is a pointer to the canonical implementation: "moved to `test_webhooks_e2e_scheduler.py::test_retry_scheduler_failure_promotes_to_dlq_after_max_attempts` (re-attempt of the in-session deferral; flat with-block structure to avoid the nested dedent footgun)".

The stub was added in plan 007 commit (v0.9.1) to preserve the test NAME across the re-attempt (the original in-session implementation broke on a nested `with`-block dedent footgun + was relocated to the standalone module). The docstring + skip message are explicit: this is intentional. But the stub:

1. **Pollutes `pytest --collect-only` output** (a "skipped" test looks like an active test with an `xfail` reason — confusing for a future maintainer browsing the test inventory).
2. **Pollutes `pytest --collect-only --strict-markers`** (the `pytest.skip()` in a function body is itself treated as a test marker; some CI configurations warn or fail on this).
3. **Misleads a future maintainer** who runs `pytest -k test_retry_scheduler_failure_promotes_to_dlq_after_max_attempts` and expects to find an active test in `test_webhooks_e2e.py` — they get a SKIP, not a pass. The canonical location is in `test_webhooks_e2e_scheduler.py`, but the test name appears in BOTH files (the stub's name is byte-identical to the canonical test's name).

The fix is to remove the stub from `test_webhooks_e2e.py`. The canonical implementation in `test_webhooks_e2e_scheduler.py` stays untouched (it's the production-version test). A short comment in `test_webhooks_e2e.py` documents the relocation, but ONLY for maintainers who grep for the test name (not as a `pytest.skip` stub).

## File changes

### 2 files edited (one rename + one comment update) + 0 NEW test files

**`apps/api/tests/test_webhooks_e2e.py`** — current 700+ line file. Remove the stub function:

```diff
-def test_retry_scheduler_failure_promotes_to_dlq_after_max_attempts(
-    session_factory: Any,
-    monkeypatch: pytest.MonkeyPatch,
-) -> None:
-    """Plan 007 v0.9.1: STUB POINTER — moved to a standalone module.
-
-    The canonical 2-tick exponential-backoff → DLQ promotion test
-    landed in ``apps/api/tests/test_webhooks_e2e_scheduler.py``
-    (the re-attempt of the in-session deferral). Keeping this
-    function here as a stub via ``pytest.skip`` preserves the
-    name (so anyone searching by test name lands on a clear
-    pointer instead of a deleted-symbol surprise).
-
-    The standalone module flattens the ``with``-block structure
-    (``_respx.mock`` OUTERMOST + per-tick short-lived
-    ``time_machine.travel``) to avoid the nested-dedent footgun
-    that broke the original in-session test.
-    """
-    pytest.skip(
-        "moved to test_webhooks_e2e_scheduler.py::"
-        "test_retry_scheduler_failure_promotes_to_dlq_after_max_attempts "
-        "(re-attempt of the in-session deferral; flat with-block structure "
-        "to avoid the nested dedent footgun)"
-    )
```

That's a ~25-line deletion. The function is replaced with a 1-line comment in the same file:

```diff
+# NOTE: ``test_retry_scheduler_failure_promotes_to_dlq_after_max_attempts``
+# was moved to ``test_webhooks_e2e_scheduler.py`` in the plan 007
+# re-attempt (the v0.9.1 ``with``-block dedent footgun). The canonical
+# implementation lives there. This file no longer has a ``pytest.skip``
+# stub to avoid polluting ``pytest --collect-only`` output + mislead
+# future maintainers who run ``pytest -k`` expecting an ACTIVE test here.
```

The 13 OTHER tests in `test_webhooks_e2e.py` are unchanged (the 11 v0.9.0 CRUD tests + the 1 v0.9.1 SSRF-block test + the 1 v0.9.1 replay-idempotency test).

**`apps/api/tests/test_webhooks_e2e_scheduler.py`** — current 200+ line file with the canonical implementation. NO content change. The docstring of the canonical test stays identical (it already documents the relocation history).

### Test changes — augment the canonical test's docstring + (optionally) add a 1-line cross-reference

**Augmentation of the canonical test in `test_webhooks_e2e_scheduler.py`** — the docstring already references `test_webhooks_e2e.py::test_retry_scheduler_failure_promotes_to_dlq_after_max_attempts` as the "stub-by-name pointer to this module". This wording was the pre-removal asymmetry — the docstring pointed AT a stub in `test_webhooks_e2e.py`; post-removal, the stub is gone, so the cross-reference becomes a maintenance note:

```diff
-See ``apps/api/tests/test_webhooks_e2e.py::
-test_retry_scheduler_failure_promotes_to_dlq_after_max_attempts``
-for the stub-by-name pointer to this module.
+# See ``apps/api/tests/test_webhooks_e2e.py`` for a historical note on
+# the relocation (post-plan-082 the stub has been removed; the canonical
+# implementation lives here, exclusively).
```

That's a 1-line change in the canonical test's docstring — purely documentary.

## Considered and rejected

- **Alternative: keep the stub + add a `pytest.skip(..., allow_module_level=True)` annotation** — the module-level allow is for SKIP-at-module-load (e.g., missing optional dep); the function-body skip is the right pattern for a test that conditionally cannot run, but the new finding is that the skip pattern is the wrong choice for a TEST THAT HAS BEEN MOVED to a different module — the canonical pattern is to MOVE the test, not to leave a stub.
- **Alternative: keep the stub + rename it to `test_retry_scheduler_failure_promotes_to_dlq_after_max_attempts_RELOCATED`** — a future maintainer who greps the original test name gets a `SKIP` + a clear error message; the renaming convention pollutes the pytest inventory (the symbol is no longer the original name).
- **Alternative: delete the stub + add a `conftest.py` assertion that the canonical location is reachable** — a future maintainer who moves the canonical test (for the same dedent footgun reason) gets an automatic fail signal from pytest collection. But the canonical implementation is in a sibling module — no import-time guarantee of its existence is needed (pytest's import-failure semantics handle missing module names automatically).
- **Alternative: keep the stub but change the body to `pytest.fail("relocated; see test_webhooks_e2e_scheduler.py")`** — flips the SKIP to a FAIL. A FAIL is louder than a SKIP, but neither is desirable: the test was moved, not removed, so the right semantics is "the canonical location is `test_webhooks_e2e_scheduler.py`" — a comment, not a pytest skip / fail.

## Effort

`S` — 1 stub removal (~25 lines deleted) + 1 documentary comment (1 line added) + 1 docstring tweak in the canonical test (1 line). Net code change is strongly negative (~22 lines deleted, 2 added). The CI time savings: each `pytest --collect-only` invocation skips 1 fewer stub-test artifact. Independent of plans 080 + 081.
