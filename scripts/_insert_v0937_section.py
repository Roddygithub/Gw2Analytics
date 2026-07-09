#!/usr/bin/env python3
"""Idempotent helper: insert the v0.9.37 audit section into plans/README.md.

Pattern matches _insert_v0927_section.py through _insert_v0936_section.py:
writes the section template literal to file if and only if the
v0.9.37 header is NOT already present, and places it just before
"## v0.9.36 audit (current)" so the section-order invariant (newest
always closest to the top of the closed history block) holds. Refuses
to re-run on consecutive invocations.
"""
from __future__ import annotations

import sys
from pathlib import Path

README = Path("plans/README.md")
V0937_HEADER = "## v0.9.37 audit (current)"
V0937_ANCHOR = "## v0.9.36 audit (current)"


SECTION_TEMPLATE = """## v0.9.37 audit (current)

**Author:** senior-advisor read-only audit pass. **Status:** current cycle.

**Scope.** `apps/api/src/gw2analytics_api/workers/{__init__.py, webhook_dispatch.py, webhook_scheduler.py}` + `apps/api/src/gw2analytics_api/health.py` + `apps/api/src/gw2analytics_api/routes/health.py` -- the worker pool + the operational health probe (`/api/v1/health/summary`). The webhook routes were covered by v0.9.15 + the commit failure-handling pattern was tightened in v0.9.25 plan 079; the WORKER surfaces (the SQLAlchemy-session-bound retry + dispatch paths) plus the health probe were un-audited. Today's 5 files are the worker + health observability surface never deeply audited.

| Plan | File(s) touched | Risk | LOC delta |
| --- | --- | --- | --- |
| **113** | NEW `apps/api/src/gw2analytics_api/workers/_delivery_common.py` + 2 modified workers | low-medium -- consolidate duplicate HMAC + canonical headers builder between `webhook_dispatch.py` + `webhook_scheduler.py` (the literal `_USER_AGENT` currently diverges: `"0.9.0"` initial vs `"0.9.1"` retry). Adds a canonical single-source-of-truth. | +60, -30 |
| **114** | `apps/api/src/gw2analytics_api/workers/webhook_scheduler.py` | low -- dead-code: ``_BACKOFF_BY_ATTEMPT[1: 1]`` is unreachable (caller passes `attempt` AFTER ``delivery.attempt += 1`` -- only `attempt ∈ {2, 3}` ever reached). Plus the silent ``.get(attempt, _MAX_ATTEMPTS)`` fallback removed; ``KeyError`` is the right surface on a future addition. | +6, -4 |
| **115** | `apps/api/src/gw2analytics_api/routes/health.py` + `health.py` | low-medium -- add NEW `GET /api/v1/health/db` route (cheap `SELECT 1` liveness probe that distinguishes "DB unreachable" from "drift detected"); DRY the duplicated drift-semantics docstring (currently in 3 places) into the canonical ``SummaryDrift``TypedDict. | +50, -25 |

**Dependency graph.** All three plans touch DISJOINT file regions: 113 affects the 2 worker files + a NEW private shared module; 114 affects `webhook_scheduler.py` only; 115 affects the 2 health files + NEW tests. PRs can land concurrently.

**Cross-cutting thematics**:

- **Single-source-of-truth for worker-side request envelope (Plan 113)**: the canonical HMAC + header builder + the workspace-level ``REQUEST_TIMEOUT_S`` + the canonical ``USER_AGENT`` (the v0.9.x-series release-string) consolidate the divergent literals across the 2 worker files into the ONE set of constants in `_delivery_common.py`.
- **Dead-code elimination + documented post-increment semantics (Plan 114)**: the `_BACKOFF_BY_ATTEMPT[1: 1]` entry was unreachable by virtue of caller discipline (the `_attempt_retry` caller increments BEFORE consulting the backoff). The plan eliminates the dead entry + removes the silent `.get(attempt, _MAX_ATTEMPTS)` fallback so future additions fail loudly with `KeyError`.
- **Health-probe granularity (Plan 115)**: the existing `/api/v1/health/summary` endpoint mixes 3 distinct operational signals (DB reachability + dataset size + drift count). A monitoring system polling for liveness cannot distinguish "DB unreachable" from "0 fights yet" from "drift detected". The new `GET /api/v1/health/db` (cheap `SELECT 1` probe) isolates liveness; the existing `/summary` stays focused on drift. Plus the drift-semantics docstring DRYs across 3 surfaces into the canonical `SummaryDrift` TypedDict.

**Rejected alternatives (15 total across the 3 plans).** Highlights:

- **Plan 113 alternative: inline the canonical builder into BOTH files via a shared `_helpers.py` module** -- convention drift here would re-create the divergence. The single canonical module is the right pattern. REJECTED.
- **Plan 113 alternative: keep the `_USER_AGENT` divergence ("initial=0.9.0, retry=0.9.1") as a forensic signal** -- the integrator's User-Agent parsing is the canonical contract for version-detection; a divergence is a bug-class surface. REJECTED.
- **Plan 114 alternative: keep the `_BACKOFF_BY_ATTEMPT[1: 1]` entry as documentation** -- dead entry is a maintenance hazard (catches no errors, includes dead-code). The TODO comment on the schedule is a better doc surface. REJECTED.
- **Plan 114 alternative: add a runtime warning when `_compute_next_attempt_at` is called with `attempt=0`** -- adds runtime surface for a purely defensive concern (the dead-key elimination test pins the invariant). The test-layer pin is cheaper. REJECTED.
- **Plan 115 alternative: add `latency_ms` to `SummaryDrift` (combining the 2 probes)** -- couples 2 distinct operational signals; a `drift_pct` of `0.0` doesn't mean "DB ok" if there's no Postgres round-trip at all. The split is canonical. REJECTED.
- **Plan 115 alternative: reuse the existing `/healthz` root-level endpoint** -- that's in `main.py` (`@app.get("/healthz", include_in_schema=False)`); the routes group is `/api/v1/health/*` for OpenAPI discovery. REJECTED.

**Test count.** 5 + 5 + 5 = **15 new hermetic tests** across the 3 plans.

**Conventions for the executor.** All 3 plans:
- Touch **only** the listed files; no incidental edits.
- 113 introduces a NEW ``_delivery_common.py`` private shared module adjacent to its 2 workers (the v0.9.x workspace convention: private (``_`` prefix) shared modules for cross-cutting helpers).
- 114 is documentation + dead-code elimination: a 2-line + 4-line tweak; the runtime behaviour is unchanged (the unreachable entry was never called).
- 115 introduces a NEW ``DbHealth`` TypedDict as the schema-of-truth for the liveness probe; the route layer cross-references ``SummaryDrift`` for the drift docstring.

"""


def main() -> int:
    text = README.read_text(encoding="utf-8")
    if V0937_HEADER in text:
        print(f"[skip] {V0937_HEADER!r} already present; no-op.")
        return 0

    if V0937_ANCHOR not in text:
        print(f"[error] anchor {V0937_ANCHOR!r} not found; abort.", file=sys.stderr)
        return 1

    replacement = SECTION_TEMPLATE + V0937_ANCHOR
    updated = text.replace(V0937_ANCHOR, replacement, 1)
    README.write_text(updated, encoding="utf-8")
    print(f"[ok] inserted {V0937_HEADER!r} (anchor: {V0937_ANCHOR!r}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
