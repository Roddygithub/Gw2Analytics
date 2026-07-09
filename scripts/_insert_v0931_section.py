#!/usr/bin/env python3
"""Idempotent helper: insert the v0.9.31 audit section into plans/README.md.

Pattern matches _insert_v0927_section.py through _insert_v0930_section.py:
writes the section template literal to file if and only if the
v0.9.31 header is NOT already present, and places it just before
"## v0.9.30 audit (current)" so the section-order invariant (newest
always closest to the top of the closed history block) holds. Refuses
to re-run on consecutive invocations.
"""
from __future__ import annotations

import sys
from pathlib import Path

README = Path("plans/README.md")
V0931_HEADER = "## v0.9.31 audit (current)"
V0931_ANCHOR = "## v0.9.30 audit (current)"


SECTION_TEMPLATE = """## v0.9.31 audit (current)

**Author:** senior-advisor read-only audit pass. **Status:** current cycle.

**Scope.** `apps/api/src/gw2analytics_api/{storage.py, database.py, models.py, schemas.py, main.py, config.py}` — the FastAPI infrastructure (MinIO wrapper + SQLAlchemy engine/sessionmaker + Base + 7 ORM models + Pydantic schemas + FastAPI app + CORS + lifespan + Settings) never audited in depth. Routes (`uploads/fights/players/account/health/webhooks`) were covered via v0.9.15 + v0.9.25 + v0.9.26; the 6 INFRA files listed were the holdouts.

| Plan | File(s) touched | Risk | LOC delta |
| --- | --- | --- | --- |
| **095** | NEW `apps/api/src/gw2analytics_api/_cache_reset.py` + `apps/api/tests/conftest.py` (autouse fixture) | low — pure helper consolidation; production code (config/database/storage) UNCHANGED | +35, -0 |
| **096** | `apps/api/src/gw2analytics_api/storage.py` + `models.py` | low — zero-migration docstring clarification; column name retained for historical alignment with design-doc schema. Alembic rename to `events_blob_key` is a flagged v0.9.x+ follow-up. | +20, -10 |
| **097** | NEW `apps/api/tests/_settings_factory.py` + `apps/api/tests/_fixtures.py` (1-line import) | low — activates the configured-but-unused `populate_by_name=True` flag on `Settings`. No production-source change. | +50, -0 |

**Dependency graph.** All three plans touch DISJOINT file regions: 095 introduces a new `_cache_reset.py` helper (reaches into the 3 production modules but does NOT modify them) + autouse fixture in conftest; 096 touches `storage.py` docstrings + `models.py::OrmFight.events_blob_uri` field-docstring; 097 lives entirely under `apps/api/tests/_settings_factory.py`. PRs can land concurrently.

Plan 095 ↔ Plan 097 COMPOSITION: tests that mutate env vars use `reset_infrastructure_caches()` (plan 095) to clear the cache AFTER the mutation so the next call sees the change; tests that want a self-contained Settings override use `make_settings(**overrides)` (plan 097) to construct an isolated instance. A test that wants BOTH calls `reset_infrastructure_caches()` first, then `make_settings(**overrides)` for the kwarg layer.

**Rejected alternatives (15 total across the 3 plans).** Highlights:

- **Plan 095 alternative: add a `reset_*` helper per module** (`config.reset_settings_cache`, `database.reset_engine`, `storage.reset_minio_client`) and let each test call each in turn — same fragmented problem at a different layer. The single helper consolidates the 4 paths.
- **Plan 095 alternative: use `functools.cache` (thread-safe at init time) instead of manual `_engine = None` resets** — would simplify `database.py` but introduce 2 more `functools.cache`-decorated globals WITH their own `.cache_clear()` paths. Net LOC change is a wash. REJECTED.
- **Plan 096 alternative: alembic-migration rename `events_blob_uri` -> `events_blob_key`** — invasive (one-shot migration script + backward-compat shim + ORM attr rename + every route/service/model reference). The minimal fix is the docstring + parameter rename; the migration is a separate v0.9.x+ pass.
- **Plan 096 alternative: rewrite the column to store full s3://bucket/key URIs** — bigger migration (write path + read path both changed; existing rows need a backfill UPDATE to prepend `s3://{bucket}/`). Operator benefit is high but the payload is too big for this audit pass.
- **Plan 096 alternative: don't rename the `get_events(key)` parameter to `get_events(blob_key)`** — keeps parameter unchanged so existing callers compile; but the parameter rename is the single biggest signal that "the value is a relative key, not a URI". Leaving it as `key` propagates the docstring burden.
- **Plan 097 alternative: drop `populate_by_name=True` from the Settings config** — the flag is dead code today; removing it makes the cleanup. But the flag was added with the explicit comment "Settings(kw=...)" intentionally, and removing it would close the door on the future test factory. The factory is the activation, not the removal. REJECTED.
- **Plan 097 alternative: inline `get_settings.cache_clear() + Settings(**overrides)` boilerplate in every test** — exactly what the factory replaces; the factory IS the DRY hoist.

**Test count.** 5 + 4 + 4 + 3 demonstrations = **16 new hermetic tests** across the 3 plans.

**Conventions for the executor.** All 3 plans:
- Touch **only** the listed files; no incidental edits.
- 095 + 097 both leave production SOURCE code untouched (095 reaches into 3 production globals via the helper; 097 reads the configured `populate_by_name=True` flag).
- 096 is the one plan that touches production source (storage.py + models.py) but is deliberately LOW-RISK — docstring + parameter-name renames; no behaviour change, no migration.

"""


def main() -> int:
    text = README.read_text(encoding="utf-8")
    if V0931_HEADER in text:
        print(f"[skip] {V0931_HEADER!r} already present; no-op.")
        return 0

    if V0931_ANCHOR not in text:
        print(f"[error] anchor {V0931_ANCHOR!r} not found; abort.", file=sys.stderr)
        return 1

    replacement = SECTION_TEMPLATE + V0931_ANCHOR
    updated = text.replace(V0931_ANCHOR, replacement, 1)
    README.write_text(updated, encoding="utf-8")
    print(f"[ok] inserted {V0931_HEADER!r} (anchor: {V0931_ANCHOR!r}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
