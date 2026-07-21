# Plan 115 (v0.9.37) — `routes/health.py` `/api/v1/health/db` canonical liveness probe + drift docstring DRY consolidation

## Files touched
- `apps/api/src/gw2analytics_api/routes/health.py` (NEW `GET /api/v1/health/db` endpoint with a cheap `SELECT 1` query + DRY-the-docstring refactor on the existing `/summary` endpoint to the canonical `SummaryDrift` source-of-truth)
- `apps/api/src/gw2analytics_api/health.py` (extends `SummaryDrift` TypedDict docstring to be the single source-of-truth + adds a NEW `DbHealth(TypedDict)` for the liveness probe)

## Findings (audit)

- `apps/api/src/gw2analytics_api/routes/health.py` currently exposes only `GET /api/v1/health/summary` — a probe that mixes 3 distinct operational concerns:
  1. **DB reachability** (the SELECT round-trip succeeds).
  2. **Dataset size** (`total_fights` + `fights_with_summaries` counts).
  3. **Drift detection** (`drift_count` + `status`).
- Today, a monitoring system polling this endpoint sees a single response that conflates all 3 with a sentinel-like semantic. The `status` is `"ok"` when `drift_count == 0` AND THERE'S A NON-EMPTY DATABASE; but it's ALSO `"drift"` on a freshly-deployed empty database (zero fights, zero summaries, drift_count = 0 — correct) AND on a crashed DB (the `db.execute(text(...))` raises, the request returns 500).
- Real-world impact: a monitoring dashboard cannot distinguish "DB unreachable" from "drift detected on a non-empty DB" from "0 fights yet (green-field deploy)". The plans that established `health_gate.py` per v0.9.x plan 005 / 053 / 073 / 074 (the CI health-gate scripts) all need the SAME shape — and they all use the drift shape. A separate liveness probe is the right addition.
- A second finding: the drift semantic docstring is duplicated in 3 places:
  - `health.py::summary_drift` lines ~36-46: the `drift_count` + `drift_pct` + `status` semantics.
  - `health.py::SummaryDrift` TypedDict docstring lines ~22-50: same semantics, again.
  - `routes/health.py::get_health_summary` lines ~28-46: same semantics, yet again.
- Three places to update on any drift-semantic change is the canonical DRY-violation maintenance hazard. The `SummaryDrift` TypedDict is the schema — the schema docstring IS the canonical source. The two consumers (the function + the route) cross-reference.

## Fix

1. `apps/api/src/gw2analytics_api/health.py` — add a NEW `DbHealth(TypedDict)` and tighten `SummaryDrift`:

   ```python
   class DbHealth(TypedDict):
       """The shape of the ``GET /api/v1/health/db`` response.

       A minimal liveness probe: a single ``SELECT 1`` round-trip
       to confirm the API can reach Postgres. The shape is
       intentionally minimal -- monitoring systems can poll at
       high cadence without a meaningful footprint.

       Attributes
       ----------
       status:
           ``"ok"`` when the ``SELECT 1`` round-trip succeeds,
           ``"unavailable"`` when it raises (the route layer maps
           the exception to a 503 Service Unavailable response).
       latency_ms:
           The approximate round-trip latency in milliseconds, as
           a positive int. The value is rounded to 2 decimal
           places for stable monitoring diffs. The detection of
           "DB unreachable" is via the HTTP-status signal (503),
           NOT via the latency field (high latency is normal under
           load, NOT a liveness indicator).
       """

       status: Literal["ok", "unavailable"]
       latency_ms: float

   def db_health(db: Session) -> DbHealth:
       """Return a liveness probe response in < 1 ms Postgres round-trip.

       Single round-trip: ``SELECT 1``. The query plan is a no-op
       (no tables scanned, no subqueries); even an empty database
       resolves the round-trip. Returns ``DbHealth`` regardless of
       the outcome -- the route translates exception -> 503.

       The implementation deliberately does NOT call
       :func:`summary_drift` here: the two probes serve different
       operational needs. Operators that want both can poll both
       endpoints; monitoring systems that want liveness only
       consume ``/api/v1/health/db`` (the cheaper round-trip).
       """
       import time

       start = time.perf_counter()
       db.execute(text("SELECT 1"))
       latency_ms = round((time.perf_counter() - start) * 1000.0, 2)
       return DbHealth(status="ok", latency_ms=latency_ms)
   ```

2. `apps/api/src/gw2analytics_api/health.py::SummaryDrift` — tighten the docstring to be the canonical source-of-truth + add a "See Also:" cross-link:

   ```python
   class SummaryDrift(TypedDict):
       """The shape of the ``GET /api/v1/health/summary`` response.

       This is THE canonical docstring for the drift semantics.
       Other consumers (:func:`summary_drift` + the route layer
       ``get_health_summary``) cross-reference this section rather
       than re-stating the semantics, so a future schema change
       only touches this one block.

       Attributes
       ----------
       total_fights: ...
       fights_with_summaries: ...
       drift_count: ...
       drift_pct: ...
       status: ...

       See Also
       --------
       :func:`summary_drift` -- the canonical implementation.
       :func:`db_health` -- the liveness probe (cheaper round-trip).
       """
   ```

3. `apps/api/src/gw2analytics_api/routes/health.py` — drop the duplicated explanation in `get_health_summary` (replace with a `See Also:` cross-link), AND add the new liveness endpoint:

   ```python
   @router.get("/db", response_model=DbHealth)
   def get_health_db(db: Session = Depends(get_session)) -> DbHealth:  # noqa: B008
       """Return a liveness probe (``SELECT 1``) for monitoring systems.

       The probe is intentionally minimal -- a single
       ``SELECT 1`` confirms Postgres reachability without any
       table scans or subqueries. Polling cadence can be high
       (every minute, every 30s, etc.) without meaningful cost.

       Response shape (see :class:`DbHealth` for canonical docstring)::

           {
               "status": "ok",
               "latency_ms": 1.23
           }

       A 503 Service Unavailable response on the
       ``db.execute(...)`` exception -- the monitoring system
       routes that signal to an alert ("DB unreachable").

       See Also
       --------
       :class:`DbHealth` -- canonical schema docstring.
       :func:`get_health_summary` -- the drift-detecting probe.
       """
       try:
           return db_health(db)
       except SQLAlchemyError as exc:
           raise HTTPException(
               status_code=503,
               detail={"code": "database_unavailable", "message": str(exc)},
           ) from exc
   ```

4. `apps/api/src/gw2analytics_api/routes/health.py` — slim the `get_health_summary` docstring to a `See Also:` cross-link to the canonical `SummaryDrift` docstring (no semantic drift between the 3 surfaces):

   ```python
   @router.get("/summary", response_model=SummaryDrift)
   def get_health_summary(db: Session = Depends(get_session)) -> SummaryDrift:  # noqa: B008
       """Return the fight-summary drift for the operational health probe.

       See :class:`SummaryDrift` for the canonical response shape
       + the ``status`` semantics.

       The probe is a single SQL round-trip (2 subqueries); safe
       to poll from a monitoring system at a high cadence.
       """
       return summary_drift(db)
   ```

## Tests (5, NEW file `apps/api/tests/routes/test_health_route.py`)

- `test_db_health_returns_ok_with_latency_under_10ms_in_normal_test_db` — call the route via the in-process TestClient; assert `status == "ok"` AND `latency_ms < 50.0` (a generous threshold; the test DB's `SELECT 1` is well under 10ms).
- `test_db_health_returns_503_on_database_error` — monkeypatch `db.execute` to raise `OperationalError`; assert the route returns `503` AND the response JSON has `code == "database_unavailable"`.
- `test_summary_drift_docstring_is_the_canonical_source_of_drift_semantics` — `inspect.getsource(SummaryDrift)` docstring contains the canonical phrases `total_fights` + `fights_with_summaries` + `drift_count` + `drift_pct` + `status - ok / drift`; the `summary_drift` + `get_health_summary` docstrings DO mention `See SummaryDrift`.
- `test_get_health_db_endpoint_is_canonical_liveness` — invoke `get_health_db` directly (not via the route); `db_health(db)` returns `{status: "ok", latency_ms: <positive_float>}`.
- `test_summary_drift_round_trip_matches_typeddict_shape` — verify `summary_drift(db).keys() == SummaryDrift.__annotations__.keys()` (round-trip integrity).

## Rejected alternatives

- **Add `latency_ms` to `SummaryDrift` (combining the 2 probes)** — couples 2 distinct operational signals; a `drift_pct` of `0.0` doesn't mean "DB ok" if there's no Postgres round-trip at all. The split is canonical. REJECTED.
- **Use FastAPI's `BackgroundTasks` to record the latency async** — overkill for a `SELECT 1` round-trip; the latency is measured at the route layer synchronously. REJECTED.
- **Move the `SELECT 1` literal to `health.py` + import** — it's used in one place (the new `db_health` function). The constant-in-module pattern is fine. REJECTED.
- **Reuse the existing `/healthz` root-level endpoint** for the new liveness probe — that's in `main.py` (`@app.get("/healthz", include_in_schema=False)`); the routes group is `/api/v1/health/*` for OpenAPI discovery. Keeping the API surface consistent. REJECTED.
- **Have `get_health_summary` call `get_health_db` first as a fail-fast gate** — coupling the two probes (operationally separate). Each is callable independently. REJECTED.
- **Use `Depends(get_sessionmaker)` + manual session instead of `Depends(get_session)`** — adds session-management boilerplate for one endpoint that doesn't need it; the canonical FastAPI `get_session` dependency is the right pattern. REJECTED.

## Dependency graph

- Independent: touches `routes/health.py` + `health.py` + NEW tests file. The other plans affect `webhook_*` workers (parallel-safe).
- Parallel-safe with plans 113 / 114.
- Pattern-aligns with the v0.9.x workspace convention: ONE canonical schema (`SummaryDrift`/`DbHealth` TypedDict) + ONE canonical impl (`summary_drift`/`db_health`) + thin route-layer wiring. Cross-references in the route's docstrings.
- Future-proofs a v0.8.x follow-up that adds additional probes (e.g. `/api/v1/health/minio` for S3 reachability): the pattern is now established.
