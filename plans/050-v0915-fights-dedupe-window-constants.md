# Plan 050 — v0.9.15 `fights.py` dedupe window constants

**Drift base:** `44ea862` (origin/main HEAD at audit time)
**Author:** senior-advisor audit (improve skill, standard effort) — `apps/api/src/gw2analytics_api/routes/*` deep pass
**Status:** pending
**Effort:** S
**Category:** DX (duplicated constants)
**Files touched:** `apps/api/src/gw2analytics_api/routes/fights.py` (1 file, additive change only) + `apps/api/tests/test_fights.py` (additions to assert the deduped constants match the 2 endpoints)

## Problem

`apps/api/src/gw2analytics_api/routes/fights.py` has
4 module-level constants that duplicate the same
bounds:

```python
_TIMELINE_DEFAULT_WINDOW_S: int = 5
_TIMELINE_MAX_WINDOW_S: int = 600

_EVENTS_DEFAULT_WINDOW_S: int = 5
_EVENTS_MAX_WINDOW_S: int = 600
```

The 2 pairs are used in 2 different endpoints:

```python
@router.get(
    "/{fight_id}/timeline",
    response_model=PerFightTimelineOut,
)
def get_fight_timeline(
    fight_id: str,
    window_s: int = Query(
        _TIMELINE_DEFAULT_WINDOW_S,
        ge=1,
        le=_TIMELINE_MAX_WINDOW_S,
        description=(...),
    ),
    db: Session = Depends(get_session),
) -> PerFightTimelineOut:
    ...

@router.get(
    "/{fight_id}/events",
    response_model=FightEventsSummaryOut,
)
def get_fight_events(
    fight_id: str,
    window_s: int = Query(
        _EVENTS_DEFAULT_WINDOW_S,
        ge=1,
        le=_EVENTS_MAX_WINDOW_S,
        description=(...),
    ),
    db: Session = Depends(get_session),
) -> FightEventsSummaryOut:
    ...
```

The values are identical (5 + 600). The 2 pairs
are separated for historical reasons (the timeline
endpoint was added in v0.8.9 as a sibling of the
events endpoint; the original `_EVENTS_*` pair was
not refactored to be shared). The 4-constant
duplication is a tech-debt artefact.

A future change to the bounds (e.g. raising the
max to 1200 seconds for a 20-minute WvW zerg)
would have to update BOTH pairs to keep them in
sync. Forgetting one creates a subtle
inconsistency (the timeline endpoint accepts a
larger window than the events endpoint, or vice
versa).

### Severity

- **DX**: LOW — the duplication is a tech-debt
  artefact, not a correctness bug. The 2 pairs
  have identical values today; the risk is a
  future drift if the bounds change.
- **Maintainability**: LOW — a 1-time refactor to
  dedupe the constants removes the future-drift
  risk.

## Goals

- Replace the 4 module-level constants
  (`_TIMELINE_DEFAULT_WINDOW_S` +
  `_TIMELINE_MAX_WINDOW_S` +
  `_EVENTS_DEFAULT_WINDOW_S` +
  `_EVENTS_MAX_WINDOW_S`) with 2 constants
  (`_DEFAULT_WINDOW_S = 5` + `_MAX_WINDOW_S = 600`).
- Update the 2 endpoint signatures to use the
  deduped constants.
- Add a comment documenting the canonical
  bounds + the rationale (the 2 endpoints share
  the same bounds; the per-bucket window contract
  is the same for both).
- Add 2 hermetic tests that assert the deduped
  constants are used in BOTH endpoints + the
  bounds are 5 + 600 (the canonical values).

## Non-goals

- Changing the canonical bounds. The plan
  preserves the existing values (5 + 600) and
  only deduplicates the constants. A future
  plan can change the bounds (e.g. raise the
  max to 1200) using the deduped constants.
- Adding a per-endpoint override (e.g. the
  timeline endpoint allows 1200, the events
  endpoint allows 600). The current code uses
  the same bounds for both endpoints; the
  per-endpoint override is a future
  enhancement.
- Refactoring the events endpoint to use the
  `PerFightTimelineAggregator`'s native
  per-bucket window (the aggregator accepts a
  `window_s` argument; the deduped constants
  feed into BOTH endpoints' `window_s`
  argument).

## Implementation

### File: `apps/api/src/gw2analytics_api/routes/fights.py`

Replace the 4 module-level constants with 2
deduped constants.

```python
# ... (existing imports) ...

# v0.9.15 plan 050: deduped window bounds shared
# by the per-fight events endpoint + the
# per-fight timeline endpoint. The canonical
# default of 5 seconds matches the standard
# GW2 toolchain bucketing convention (1 s is
# noisy for DPS graphs; 10 s hides burst
# variance). The canonical max of 600 seconds
# (10 minutes) is a sanity bound so a
# misconfigured client cannot ask for 24h
# buckets. The 2 endpoints share the same
# bounds; the per-bucket window contract is the
# same for both. The pre-v0.9.15 code had 4
# constants (``_TIMELINE_DEFAULT_WINDOW_S`` +
# ``_TIMELINE_MAX_WINDOW_S`` +
# ``_EVENTS_DEFAULT_WINDOW_S`` +
# ``_EVENTS_MAX_WINDOW_S``) with identical
# values; the deduped pair is the single source
# of truth.
_DEFAULT_WINDOW_S: int = 5
_MAX_WINDOW_S: int = 600

router = APIRouter(prefix="/api/v1/fights", tags=["fights"])

# ... (existing _load_fight_events + list_fights) ...


@router.get(
    "/{fight_id}/timeline",
    response_model=PerFightTimelineOut,
)
def get_fight_timeline(
    fight_id: str,
    window_s: int = Query(
        _DEFAULT_WINDOW_S,
        ge=1,
        le=_MAX_WINDOW_S,
        description=(
            "Time-bucket size for the per-fight "
            "timeline roll-up. Defaults to 5 "
            "seconds; bounded 1 <= window_s <= 600 "
            "(10 minutes)."
        ),
    ),
    db: Session = Depends(get_session),
) -> PerFightTimelineOut:
    ...


@router.get(
    "/{fight_id}/events",
    response_model=FightEventsSummaryOut,
)
def get_fight_events(
    fight_id: str,
    window_s: int = Query(
        _DEFAULT_WINDOW_S,
        ge=1,
        le=_MAX_WINDOW_S,
        description=(
            "Time-bucket size for the roll-up "
            "window. Defaults to 5 seconds; "
            "bounded 1 <= window_s <= 600 (10 "
            "minutes)."
        ),
    ),
    db: Session = Depends(get_session),
) -> FightEventsSummaryOut:
    ...
```

### File: `apps/api/tests/test_fights.py` (additions)

```python
class TestFightsWindowConstants:
    """The ``_DEFAULT_WINDOW_S`` + ``_MAX_WINDOW_S``
    constants are the single source of truth for
    the per-bucket window bounds; the 2 endpoints
    (events + timeline) use the same bounds."""

    def test_default_window_s_is_5(self) -> None:
        from gw2analytics_api.routes.fights import (
            _DEFAULT_WINDOW_S,
        )
        assert _DEFAULT_WINDOW_S == 5

    def test_max_window_s_is_600(self) -> None:
        from gw2analytics_api.routes.fights import (
            _MAX_WINDOW_S,
        )
        assert _MAX_WINDOW_S == 600

    def test_timeline_endpoint_uses_deduped_constants(
        self,
    ) -> None:
        """The per-fight timeline endpoint uses
        the deduped constants for its ``window_s``
        ``Query`` validation bounds."""
        from gw2analytics_api.routes.fights import router
        # Find the timeline route
        timeline_route = next(
            route for route in router.routes
            if route.path.endswith("/timeline")
        )
        # The ``window_s`` Query's ``default`` is
        # the deduped constant.
        window_s_param = next(
            param for param in timeline_route.dependant.query_params
            if param.name == "window_s"
        )
        assert window_s_param.default == 5
        assert window_s_param.ge == 1
        assert window_s_param.le == 600

    def test_events_endpoint_uses_deduped_constants(
        self,
    ) -> None:
        """The per-fight events endpoint uses the
        deduped constants for its ``window_s``
        ``Query`` validation bounds."""
        from gw2analytics_api.routes.fights import router
        # Find the events route (the one with
        # ``/{fight_id}/events``)
        events_route = next(
            route for route in router.routes
            if route.path.endswith("/events")
        )
        window_s_param = next(
            param for param in events_route.dependant.query_params
            if param.name == "window_s"
        )
        assert window_s_param.default == 5
        assert window_s_param.ge == 1
        assert window_s_param.le == 600
```

## Test plan

1. **4 new hermetic tests** in
   `apps/api/tests/test_fights.py` cover the
   deduped constants (the 2 constant values + the
   2 endpoint usages).
2. **All existing tests pass** — the change is
   backwards-compatible (the deduped constants
   have the same values as the original 4
   constants).
3. **`uv run pytest apps/api/tests/`** exits 0.
4. **`uv run mypy --no-incremental libs apps`** is
   clean.

## Acceptance criteria

- [ ] `_TIMELINE_DEFAULT_WINDOW_S` +
      `_TIMELINE_MAX_WINDOW_S` +
      `_EVENTS_DEFAULT_WINDOW_S` +
      `_EVENTS_MAX_WINDOW_S` are removed.
- [ ] `_DEFAULT_WINDOW_S = 5` +
      `_MAX_WINDOW_S = 600` are added.
- [ ] The 2 endpoint signatures use the deduped
      constants.
- [ ] 4 new hermetic tests pass.
- [ ] All existing tests pass.
- [ ] `mypy --no-incremental` is clean.
- [ ] `ruff check` is clean.
- [ ] No production code paths change (the
      deduped constants have the same values as
      the original 4 constants; the 2 endpoints
      accept the same `window_s` range).

## Out-of-scope / deferred

- **Changing the canonical bounds**: out of scope
  (the plan preserves the existing values 5 + 600
  and only deduplicates the constants). A future
  plan can change the bounds using the deduped
  constants.
- **Adding a per-endpoint override** (e.g. the
  timeline endpoint allows 1200, the events
  endpoint allows 600): out of scope (the current
  code uses the same bounds for both endpoints;
  the per-endpoint override is a future
  enhancement).

## Maintenance notes

- **The deduped constants are documented** with
  the canonical bounds + the rationale (the 2
  endpoints share the same bounds; the per-bucket
  window contract is the same for both). A future
  plan that wants to change the bounds (e.g.
  raise the max to 1200) is a 1-line change to
  `_MAX_WINDOW_S = 1200`; the 2 endpoints
  automatically pick up the new bound.
- **The pre-v0.9.15 code had 4 constants with
  identical values**; the deduped pair is the
  single source of truth. The diff is purely
  additive (the new constants replace the old
  ones; the endpoint signatures update the
  constant references).
- **The FastAPI `Query` validation contract** is
  preserved (the `ge=1` + `le=600` bounds are
  unchanged). A 422 is raised for an
  out-of-range `window_s` BEFORE the route body
  runs (the canonical FastAPI contract).
