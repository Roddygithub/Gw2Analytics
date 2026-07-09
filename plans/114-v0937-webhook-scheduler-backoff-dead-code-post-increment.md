# Plan 114 (v0.9.37) — `webhook_scheduler.py` `_BACKOFF_BY_ATTEMPT` dead code elimination + post-increment semantics

## Files touched
- `apps/api/src/gw2analytics_api/workers/webhook_scheduler.py` (drop the `_BACKOFF_BY_ATTEMPT[1: 1]` dead entry; document the post-increment caller-side invariant; add `_MUST_NOT_USE_ATTEMPT_1_BACKOFF: Final[bool] = False` opt-out for the dead-key detection in defensive code review)
- `apps/api/tests/workers/test_webhook_scheduler.py` (NEW — 5 hermetic tests pinning the backoff schedule semantics + the dead-key elimination)

## Findings (audit)

- `webhook_scheduler.py::process_scheduled_retries` (line ~37):
  ```python
  _BACKOFF_BY_ATTEMPT: dict[int, int] = {1: 1, 2: 10, 3: 100}
  ```
- `webhook_scheduler.py::_attempt_retry` (line ~141):
  ```python
  delivery.attempt += 1
  delivery.next_attempt_at = None

  try:
      resp = client.post(...)
  except httpx.HTTPError as exc:
      delivery.error = f"{type(exc).__name__}: {exc}"
      if delivery.attempt < _MAX_ATTEMPTS:
          delivery.next_attempt_at = _compute_next_attempt_at(delivery.attempt)
      # ...
      return False
  ```
- The flow: after the FIRST failed retry, `delivery.attempt` is `2` (incremented from the initial `1`). The conditional `if delivery.attempt < _MAX_ATTEMPTS: delivery.next_attempt_at = _compute_next_attempt_at(delivery.attempt)` calls `_compute_next_attempt_at(2)`. After the SECOND failed retry, `delivery.attempt` is `3`, calls `_compute_next_attempt_at(3)`. After the THIRD failed retry, `delivery.attempt` is `3` (the cap), so the retry path SKIPS the `_compute_next_attempt_at` call and instead goes to `_promote_to_dlq`.
- Net effect: `_compute_next_attempt_at` is called with `attempt ∈ {2, 3}` — `attempt=1` is **NEVER** called by the retry path. The initial dispatch writes `next_attempt_at = _utcnow()` (= now), bypassing `_compute_next_attempt_at`. So the `_BACKOFF_BY_ATTEMPT[1: 1]` entry is **unreachable**.
- `_compute_next_attempt_at(1)` would also be unreachable if DEBUG-invoked manually — the function pattern (post-increment attempt) is enforced by caller discipline only; an `attempt=1` call today silently returns `now + 1s` (a non-issue at runtime; a code-smell at review time).
- The dead-entry pattern is a real maintenance hazard:
  1. A future migration to a tunable backoff (per integration-specific policies the user requested in v0.9.3 backlog) would naturally add MORE entries; the dead-key at `attempt=1` invites a contributor to "use it" — which would couple the dead-key semantics to a future call site, hiding the actual semantic shift.
  2. The 3-entry schedule is doubly documented (the `_BACKOFF_BY_ATTEMPT` dict + the inline `_MAX_ATTEMPTS = 3` constant + the design doc reference in the module docstring). Drift among the 3 sources is a real maintenance risk.
- A 3rd sub-finding: the `_REQUEST_TIMEOUT_S = 10.0` constant is also duplicated between `webhook_dispatch.py` (line ~34) and `webhook_scheduler.py` (line ~52). This is the canonical v0.9.x cross-worker-surface literal duplication. Plan 113 v0.9.37 moves the constant to `_delivery_common.REQUEST_TIMEOUT_S`; Plan 114 confirms the scheduler import path updates accordingly.

## Fix

1. `apps/api/src/gw2analytics_api/workers/webhook_scheduler.py` — replace `_BACKOFF_BY_ATTEMPT`:

   ```python
   # Post-increment backoff schedule: keys are the (about-to-become)
   # attempt value AFTER ``delivery.attempt += 1``. The retry path
   # invokes ``_compute_next_attempt_at(delivery.attempt)`` only for
   # ``attempt ∈ {2, 3}`` -- the entry for ``attempt == 0`` is
   # unreachable (the initial dispatch writes ``next_attempt_at``
   # directly via ``_utcnow()``) and ``attempt == 1`` is unreachable
   # (the retry path increments BEFORE the call). The schedule is
   # exactly 2 entries, ordered: 10s before attempt 2, 100s before
   # attempt 3.
   _BACKOFF_BY_ATTEMPT: dict[int, int] = {2: 10, 3: 100}
   """

   The accompanying module-level docstring is updated::

   The retry backoff schedule is enforced post-increment:
   ``_BACKOFF_BY_ATTEMPT[attempt]`` is consulted AFTER
   ``delivery.attempt += 1``. ``attempt=2`` schedules 10s,
   ``attempt=3`` schedules 100s. ``attempt=4`` would be the
   DLQ-promotion boundary (caught by the ``if delivery.attempt
   < _MAX_ATTEMPTS`` guard -- ``_MAX_ATTEMPTS = 3``). The
   unreachable entry ``attempt=0`` is omitted on purpose:
   the initial dispatch writes ``next_attempt_at = now`` directly,
   so the backoff schedule is keyed on retry-only values.
   ```

2. `webhook_scheduler.py::_compute_next_attempt_at` — update the docstring to spell the post-increment invariant explicitly:

   ```python
   def _compute_next_attempt_at(attempt: int) -> datetime:
       """``now + backoff[attempt]`` for the post-attempt delay.

       ``attempt`` is the (about-to-become) attempt value AFTER the
       caller's ``delivery.attempt += 1``. The caller-side
       invariant is:

       - ``attempt == 2`` -> 10s wait before retry-as-attempt-3.
       - ``attempt == 3`` -> 100s wait before retry-as-attempt-4
         (capped by ``_MAX_ATTEMPTS = 3`` so retry 4 is the
         DLQ-promotion boundary, NOT another POST).

       The ``_MAX_ATTEMPTS`` cap is checked by the caller's
       ``if delivery.attempt < _MAX_ATTEMPTS`` guard; this
       function does NOT consult ``_MAX_ATTEMPTS`` directly.
       A ``KeyError`` would fire on ``attempt=0`` (unreachable)
       -- the dead-key check below is a test-layer invariant.
       """
       return datetime.now(tz=UTC) + timedelta(seconds=_BACKOFF_BY_ATTEMPT[attempt])
   ```

   Note: the silent `.get(attempt, _BACKOFF_BY_ATTEMPT[_MAX_ATTEMPTS])` fallback at the end of the line is REMOVED (the implicit assumption that an unknown attempt falls back to `_MAX_ATTEMPTS` backoff is no longer needed once the schedule is exactly `{2, 3}`; a future contributor adding `attempt=4` should fail loudly with `KeyError`, not silently retry with the old `_MAX_ATTEMPTS` backoff).

## Tests (5, NEW file `apps/api/tests/workers/test_webhook_scheduler.py`)

- `test_backoff_schedule_is_exactly_two_entries` — `len(_BACKOFF_BY_ATTEMPT) == 2` AND `set(_BACKOFF_BY_ATTEMPT.keys()) == {2, 3}`. Defensive: catches a future regression that re-adds the `attempt=1` entry.
- `test_compute_next_attempt_at_attempt_2_returns_now_plus_10s` — invoke `_compute_next_attempt_at(2)`; assert the returned datetime is approximately `now + 10s` (with a small tolerance for time elapsing during the call).
- `test_compute_next_attempt_at_attempt_3_returns_now_plus_100s` — same pattern for `100s`.
- `test_compute_next_attempt_at_unknown_attempt_raises_keyerror` — invoke `_compute_next_attempt_at(0)` and `_compute_next_attempt_at(99)`; both raise `KeyError` (the silent fallback removed).
- `test_request_timeout_s_matches_dispatch_module_via_delivery_common` — `_delivery_common.REQUEST_TIMEOUT_S == 10.0` AND the worker's `httpx.Client(timeout=...)` constructor reads from `_delivery_common.REQUEST_TIMEOUT_S` (via `inspect.getsource` or a re-export).

## Rejected alternatives

- **Keep the `_BACKOFF_BY_ATTEMPT[1: 1]` entry as documentation** — the dead entry is a maintenance hazard (catches no errors, includes dead-code). The TODO comment on the schedule is a better doc surface. REJECTED.
- **Add a runtime warning when `_compute_next_attempt_at` is called with `attempt=0`** — adds runtime surface for a purely defensive concern (the dead-key elimination test pins the invariant). The test-layer pin is cheaper. REJECTED.
- **Use a `dict`-typed constant pattern (`BACKOFF = AttemptBackoff(attempt_2_s=10, attempt_3_s=100)`) instead of a plain dict** — over-engineered for a 2-entry schedule. The dict literal is the canonical pattern. REJECTED.
- **Move `_MAX_ATTEMPTS` to a `Settings` model** — it's a worker-policy number, not an environment-driven value. Tests + docstrings are the right place. REJECTED.
- **Build a type-safe `_BackoffSchedule` typed-dict** — same refactoring cost as the dict overengineering; no functional benefit. REJECTED.

## Dependency graph

- Independent: touches `webhook_scheduler.py` only + NEW tests.
- Parallel-safe with plans 113 / 115.
- Pattern-aligns with plan 113: SAME `_delivery_common` import strategy for the shared `REQUEST_TIMEOUT_S` constant (the implicit cross-worker literal duplication that plan 113 surfaces as a single canonical source).
- Plans 113 + 114 together close the "shared worker-side literals diverge silently" pattern. Plan 113 fixes HMAC + headers + User-Agent; Plan 114 fixes the backoff schedule + the silent fallback removal.
