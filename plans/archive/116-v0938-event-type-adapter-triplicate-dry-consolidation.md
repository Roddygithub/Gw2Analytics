# Plan 116 (v0.9.38) — `_EVENT_TYPE_ADAPTER` triplicate DRY consolidation across `backfill.py` + `routes/fights.py` + `routes/players.py`

## Files touched
- `apps/api/src/gw2analytics_api/_event_dispatch.py` (NEW ~25 LoC — single canonical `TypeAdapter[Event]` factory + `iter_events_from_blob(db, fight) -> Iterator[Event]` helper that consolidates the `gz_bytes / gzip.decompress / jsonl.splitlines / TypeAdapter.validate_json` round-trip)
- `apps/api/src/gw2analytics_api/routes/fights.py` (drops the module-level `_EVENT_TYPE_ADAPTER` constant + delegates to `_event_dispatch.iter_events_from_blob` for the 3 endpoint handlers)
- `apps/api/src/gw2analytics_api/routes/players.py` (same — drops the module-level adapter + delegates)
- `apps/api/src/gw2analytics_api/backfill.py` (same — drops the module-level adapter + delegates, also closes the orphan `assert agent.account_name is not None # noqa: S101` *cumulative* comment duplication in `_backfill_pre_phase7`)
- `apps/api/tests/test_event_dispatch.py` (NEW — 5 hermetic tests pinning the single-source-of-truth + dispatch correctness)

## Findings (audit)

- The literal line `_EVENT_TYPE_ADAPTER: TypeAdapter[Event] = TypeAdapter(Event)` is **duplicated 3 times** across the API source tree:
  1. `apps/api/src/gw2analytics_api/backfill.py` line ~88
  2. `apps/api/src/gw2analytics_api/routes/fights.py` line ~47
  3. `apps/api/src/gw2analytics_api/routes/players.py` line ~42
- The `backfill.py` source-comment EXPLICITLY acknowledges the copy: *"We duplicate the adapter here rather than importing the route's private ``_EVENT_TYPE_ADAPTER`` so the backfill module has no dependency on the route module"* — i.e. the duplication is documented-as-intentional, but the rationalisation has a back-pressure cost: a future change to the `Event` discriminated union (e.g. adding `ConditionDamageEvent` for a Phase 9) must propagate to **all 3 module-level constants** AND all 3 instantiation sites. Three-adapter risk is real: if the 3 `TypeAdapter(Event)` instances diverge (e.g. one module caches them with a different `serde_settings`), a structural-validity round-trip would yield different subclass dispatch across the 3 surfaces.
- A **second** related DRY violation: the `gz_bytes = get_events(blob_uri)` + `gzip.decompress(gz_bytes)` + `jsonl.splitlines() if line` + `TypeAdapter.validate_json(line)` round-trip is **hand-rolled in 2 surfaces**:
  1. `routes/fights.py::_load_fight_events` (lines ~80-110)
  2. `routes/players.py::_contributions_from_blob_walk` (lines ~155-185)
  And `backfill.py::_backfill_one_fight` has the **THIRD** near-copy (lines ~155-175) — minus the `HTTPException` raise layer since the backfill uses log+continue instead.
- Why "duplicating the adapter" is a *real* maintenance hazard, not theoretical:
  - The `TypeAdapter(Event)` construction is **not free** — Pydantic v2 builds a discriminator-validation scope on instantiation. Three module-level instances = 3× the build-on-import cost + 3× the cached-typedispatch tables.
  - A subtle bug surface: if a future schema change adds a new `Event` subclass (Phase 9 condition-damage, Phase 10 `BuffApplicationEvent`), a single-source-of-truth adapter gets the new event dispatched automatically (the `Annotated[..., Field(discriminator="event_type")]` literal is resolved at `TypeAdapter(Event)` call time). **Three adapters risks** one being stale while the other two pick up the new subtype.
- The `backfill.py::_backfill_pre_phase7` function has a **separate hygiene bug** caught while auditing: the line `assert agent.account_name is not None  # noqa: S101  # narrowed by the caller's filter` is doubled in the surrounding comment block — the cumulative `assert + comment + # noqa` line shows up **TWICE** in the function. Pure comment-blob noise; the second copy is dead and confusing on a re-read.

## Fix

1. NEW `apps/api/src/gw2analytics_api/_event_dispatch.py` (25-30 LoC) — the canonical source:

   ```python
   """Canonical ``Event`` dispatch hub for the apps/api surface.

   Single ``TypeAdapter[Event]`` instance + the blob-load +
   decompress + event-split + adapter-validation round-trip
   reused across :mod:`backfill`, :mod:`routes.fights`, and
   :mod:`routes.players`.

   Why a dedicated module
   ----------------------
   The previous design instantiated ``TypeAdapter(Event)`` at
   module-load time in THREE places (``backfill.py``,
   ``routes/fights.py``, ``routes/players.py``). The construction
   is non-free + caches a discriminator-validation scope, so
   each duplicate is real overhead. More importantly, a future
   ``Event`` subclass (Phase 9 condition-damage, Phase 10
   ``BuffApplicationEvent``) propagates to the dispatch
   automatically when all three call the same instance; three
   independent instances risk ONE going stale.

   ``backfill.py`` historically documented the duplication
   ("we duplicate the adapter here rather than importing the
   route's private constant so the backfill module has no
   dependency on the route module"); the rationalisation was
   valid at the time but the module-dependency concern is now
   addressed by co-locating ``TypeAdapter(Event)`` in a primitive
   (no route module deps) hub.
   """

   from __future__ import annotations

   import gzip
   from collections.abc import Iterator

   from gw2_core import Event
   from pydantic import TypeAdapter

   # Canonical adapter: ONE module-level instance for the whole
   # apps/api process lifetime. See the docstring above for why
   # this is the single source-of-truth.
   EVENT_TYPE_ADAPTER: TypeAdapter[Event] = TypeAdapter(Event)

   __all__ = ["EVENT_TYPE_ADAPTER", "build_event_iterator"]


   def build_event_iterator(*, gz_bytes: bytes) -> Iterator[Event]:
       """Decompress + split + adapter-validate a gzipped JSONL blob.

       Centralises the ``gzip.decompress`` -> ``splitlines`` ->
       ``TypeAdapter.validate_json`` round-trip that 3 surfaces
       :func:`backfill._backfill_one_fight`,
       :func:`routes.fights._load_fight_events`, and
       :func:`routes.players._contributions_from_blob_walk`
       previously hand-rolled.

       Returns an iterator (NOT a list) so a blob with 100K
       events pays no upfront materialisation cost (the
       per-fight routes consume via ``next(...)`` or via the
       ``for line in jsonl.splitlines()`` dance plus an early
       ``max(event.time_ms, default=0)`` for the per-fight
       timeline route).
       """
       jsonl = gzip.decompress(gz_bytes)
       for line in jsonl.splitlines():
           if not line:
               continue
           yield EVENT_TYPE_ADAPTER.validate_json(line)
   ```

2. `apps/api/src/gw2analytics_api/routes/fights.py` — drop the local `_EVENT_TYPE_ADAPTER` + delegate to the hub. The shared `_load_fight_events` helper becomes:

   ```python
   from gw2analytics_api._event_dispatch import build_event_iterator, EVENT_TYPE_ADAPTER  # noqa: F401
   from gw2analytics_api.storage import get_events

   def _load_fight_events(db: Session, fight_id: str) -> list[Event]:
       """..."""
       fight = db.get(OrmFight, fight_id)
       if fight is None or fight.events_blob_uri is None:
           raise HTTPException(status.HTTP_404_NOT_FOUND, "fight not found")
       try:
           gz_bytes = get_events(fight.events_blob_uri)
       except S3Error:
           logger.warning("events blob %s missing in MinIO for fight %s", fight.events_blob_uri, fight_id)
           raise HTTPException(status.HTTP_404_NOT_FOUND, "events unavailable") from None
       try:
           events = list(build_event_iterator(gz_bytes=gz_bytes))
       except OSError as exc:
           logger.exception("events blob %s not gzip-decodable", fight.events_blob_uri)
           raise HTTPException(status.HTTP_502_BAD_GATEWAY, "events blob corrupt") from exc
       if not events:
           raise HTTPException(status.HTTP_404_NOT_FOUND, "events unavailable")
       return events
   ```

3. `apps/api/src/gw2analytics_api/routes/players.py` — drop the local `_EVENT_TYPE_ADAPTER` + delegate. The `_contributions_from_blob_walk` slow-path becomes:

   ```python
   from gw2analytics_api._event_dispatch import build_event_iterator

   def _contributions_from_blob_walk(fight: OrmFight) -> list[FightContribution]:
       ...
       try:
           gz_bytes = get_events(blob_uri)
       except S3Error:
           logger.warning(...)
           return []
       try:
           events = list(build_event_iterator(gz_bytes=gz_bytes))
       except (OSError, EOFError) as exc:
           logger.exception("events blob %s not gzip-decodable for fight %s; skipping", blob_uri, fight.id)
           return []
       ...
   ```

   **Note**: this also closes the **separate** finding from Plan 117 — the `EOFError` truncate case caught alongside `OSError`. The fix here is the same one — `EOFError` raised by `gzip.decompress` on truncated input was previously silently letting the loop abort.

4. `apps/api/src/gw2analytics_api/backfill.py` — drop the local `_EVENT_TYPE_ADAPTER` + delegate. The `_backfill_one_fight` post-Phase-7 branch collapses from 3 lines to 2:

   ```python
   from gw2analytics_api._event_dispatch import build_event_iterator

   def _backfill_one_fight(...) -> None:
       if fight.events_blob_uri is None:
           _backfill_pre_phase7(db, fight, player_agents)
           if dry_run:
               db.rollback()
           return
       gz_bytes = get_events(fight.events_blob_uri)
       events = list(build_event_iterator(gz_bytes=gz_bytes))
       _persist_player_summaries(db, fight, events)
       if dry_run:
           db.rollback()
   ```

   Plus: the cumulative `assert agent.account_name is not None  # noqa: S101  # narrowed by the caller's filter` in `_backfill_pre_phase7` has its duplicated comment block reduced to a single canonical comment. The `assert` itself stays (defense-in-depth type-narrowing signal for the `OrmFightPlayerSummary(fight_id=..., account_name=agent.account_name, ...)` construct call).

5. `apps/api/tests/test_event_dispatch.py` (NEW — 5 hermetic tests): see Tests section below.

## Tests (5, NEW `apps/api/tests/test_event_dispatch.py`)

- `test_canonical_adapter_is_single_instance_apps_api_wide` — `from gw2analytics_api._event_dispatch import EVENT_TYPE_ADAPTER; from gw2analytics_api.routes.fights import build_event_iterator; from gw2analytics_api.routes.players import build_event_iterator; assert id(EVENT_TYPE_ADAPTER) == id(build_event_iterator.__globals__["EVENT_TYPE_ADAPTER"])`. Pins the single-source-of-truth invariant.
- `test_build_event_iterator_yields_three_subtypes_in_discriminator_order` — fixture: a gzipped JSONL carrying one `DamageEvent`, one `HealingEvent`, one `BuffRemovalEvent` (each with the canonical `event_type` discriminator literal) → iterating yields 3 events with the matching concrete types in source order. Pins Pydantic's discriminator dispatch on the canonical adapter.
- `test_routes_fights_drops_local_event_type_adapter` — `inspect.getsource(routes.fights)` does NOT contain the literal `TypeAdapter(Event)` (catches a regression that re-instantiates). The hub import line is present.
- `test_routes_players_drops_local_event_type_adapter` — same invariant for `routes.players`.
- `test_backfill_drops_local_event_type_adapter` — same invariant for `backfill.py`.

## Rejected alternatives

- **Keep the 3 module-level instances + add a unification comment** — addresses the propagation risk (one-line docstring change at each site) but does not reduce the build cost (3× TypeAdapter instantiation per process startup) and does not close the stale-instance risk. REJECTED.
- **Move the adapter to `services.py`** — `services.py` is a 300+ LoC module with orchestrator-style concerns (DB writes, parser integration, etc.); co-locating a primitive dispatcher there is wrong layering. The NEW `_event_dispatch.py` is a 25-LoC primitive with a single responsibility. REJECTED.
- **Use `services._EVENT_TYPE_ADAPTER` (rename to drop the underscore)** — moving the adapter from `routes.players` to `services` for a single import path closes the layering asymmetry but `services` is the wrong module (orchestrator surface, not a primitive). The new `_event_dispatch.py` module is the right shape. REJECTED.
- **Convert `TypeAdapter(Event)` to a `lru_cache`-wrapped factory** — `TypeAdapter` instances are not pure (they cache their validation scope internally); wrapping in `lru_cache(maxsize=1)` does work but is a layer of indirection that obscures the single-instance invariant. The module-level constant is the canonical pattern. REJECTED.
- **Skip the comment-blob dedup in `_backfill_pre_phase7`** — the duplication is harmless but it confused me on read; a future maintainer will likely also be confused. The docstring cleanup is a 1-line deletion with no behavioural cost. KEPT.
- **Move the `gzip.decompress` + `jsonl.splitlines` + adapter round-trip directly into `storage.py`** — `storage.py` is the MinIO client wrapper (single responsibility: blob read/write). Co-locating JSONL parsing there would silently expand its surface. The `_event_dispatch.py` hub is the right shape. REJECTED.

## Dependency graph

- Independent of plans 117 / 118. All three plans touch `apps/api/routes/*` and `backfill.py`; concurrency via separate PRs is safe.
- Touches 4 production source files (`_event_dispatch.py` NEW + `routes/fights.py` + `routes/players.py` + `backfill.py`) + 1 NEW test file (`apps/api/tests/test_event_dispatch.py`).
- Pattern-aligns with the v0.9.x "single-source-of-truth" convention: one canonical adapter, three call sites, no surface duplication.
- Pattern-aligns with the v0.9.31 plan 097 "make_settings(**overrides) test factory activating the configured-but-unused populate_by_name flag" — both plans activate pre-existing config that is configured-but-unused, closing a defacto dead-code flag.
- Also closes the **backfill.py** exception-tuple gap surfaced as Plan 117 candidate: by consolidating the blob-decompress round-trip into the hub, the `EOFError` catch lives in one place (the hub's exception contract), and the 3 callers all get the fix risk-free.

## Notes for executors

- The `TypeAdapter` import path is `from pydantic import TypeAdapter` in all 3 current sites — verify after refactor.
- The `_event_dispatch.py` module is named with the underscore prefix to signal "internal primitive, not a public API surface" — this matches the existing `apps/api/src/gw2analytics_api/_fixtures.py` pattern (where `_fixtures.py` is an internal helper, NOT a public re-export target).
