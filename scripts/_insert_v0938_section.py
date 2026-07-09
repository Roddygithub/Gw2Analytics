"""v0.9.38 plans/README.md section inserter (idempotent).

Mirrors the v0.9.27..37 inserter pattern:
  - Reads plans/README.md
  - Locates the '## v0.9.37 audit (closed)' section header (the
    immediately-preceding v0.9.X audit pass marker)
  - Inserts a '## v0.9.38 audit (current)' block right after the
    v0.9.37 section ends (and before the next sibling section)
  - Idempotent: re-running on an already-inserted v0.9.38 section
    is a no-op (the inserter detects the marker + bails)

The script is intentionally tiny (~85 LoC) + uses only stdlib to
avoid adding a runtime dep to the workspace. The convention
established across v0.9.27..37 keeps the inserter script in
`scripts/_insert_vNNNN_section.py` for one-shot use; the script
can be deleted after the v0.9.38 plans are accepted into the
cycle.
"""

from __future__ import annotations

import sys
from pathlib import Path

README = Path("plans/README.md")
MARKER = "## v0.9.38 audit (current)"
# The inserter script runs BEFORE the trailing ``sed -i`` that
# flips the preceding pass to ``(closed)`` -- so at script time
# the preceding section header is still labelled ``(current)``.
# The trailing ``sed -i`` step is part of the same shell
# pipeline (``python3 _insert_v0938_section.py && sed -i ...``).
PRECEDING_HEADER = "## v0.9.37 audit (current)"

INSERT_BLOCK = """
## v0.9.38 audit (current)

> **Scope.** Surface coverage: `apps/api/src/gw2analytics_api/backfill.py` + `routes/{fights,account,players}.py`. The remaining routes (`webhooks.py`, `uploads.py`, `health.py`) were covered by v0.9.15 + v0.9.25 + v0.9.26; the backfill library + the 3 largest operational routes (`fights`, `account`, `players`) are the v0.9.x cycle's most-touched surfaces (each edited 5-10 times across the v0.8.x / v0.9.x release history).

### Status

| Plan | Title | Files | Status | Tests |
|------|-------|-------|--------|-------|
| 116  | `_EVENT_TYPE_ADAPTER` triplicate DRY consolidation across `backfill.py` + `routes/fights.py` + `routes/players.py` | `_event_dispatch.py` NEW + 3 route/backfill sites + 1 test file | open | 5 NEW |
| 117  | `routes/fights.py::get_fight_events` monolithic 200+ lines → extract per-target roll-up helper for DRY | `routes/fights.py` + 1 test file | open | 5 NEW |
| 118  | `backfill.py::run_backfill` exception tuple gap: `EOFError` from truncated gzipped blobs aborts the loop instead of counting as `failed: 1` | `backfill.py` + 1 test file | open | 5 NEW |

**Total**: 3 plans, 15 NEW hermetic tests.

### Dependency graph

- **Plan 116** (single-source-of-truth `TypeAdapter` + `iter_events_from_blob` helper) is standalone; touches 4 production source files (`_event_dispatch.py` NEW + 3 call sites) + 1 NEW test file.
- **Plan 117** (per-target roll-up helper) is standalone; touches 1 production source file + 1 NEW test file.
- **Plan 118** (backfill `EOFError` catch + comment-block dedup) is standalone BUT transitively surfaces the same `EOFError` catch gap that plan 116 closes for the routes-via-hub path — both plans address per-fight exception-tuple correctness in different surfaces. The 3 plans can ship concurrently as 3 separate PRs.
- **No plan depends on a v0.9.27..v0.9.37 plan being merged first**. The 3 plans are independent and PR-friendly.

### Cross-cutting patterns

- **DRY consolidation across 3 call sites** (plan 116) — matches the v0.9.x convention of "ONE canonical implementation + thin call-site fan-out". Previously documented in plan 037 + plan 095 + plan 113.
- **Per-target roll-up DRY** (plan 117) — `get_fight_events` is the canonical Phase 7 v1 + Phase 8 v0.8.0 + v0.8.3 endpoint; extracting the per-target trio to a helper cleans up 120 LoC of noise.
- **Per-fight exception-tuple completeness** (plan 118) — `EOFError` from truncated gzipped blobs is the canonical "blameless error" surface (the operator shouldn't see a stacktrace on a corrupted mid-upload blob); the existing 4-tuple `(S3Error, OSError, SQLAlchemyError, ValidationError)` misses `EOFError`.

### Rejected alternatives (this pass's pattern, condensed)

- **Three module-level `TypeAdapter(Event)` instances** (vs. plan 116's one) — 3× build-on-import cost + stale-instance risk. REJECTED.
- **`singledispatch` on the `Event` superclass** (vs. plan 117's `if/elif`) — closed-form dispatch table is more readable for 3 known targets. REJECTED.
- **Catch `Exception` broadly** (vs. plan 118's specific 5-tuple) — silently swallows `AttributeError` from future schema drift. REJECTED.

### Test inventory (cumulative v0.9.27..v0.9.38)

| Pass | NEW hermetic tests |
|------|--------------------|
| v0.9.27 | 16 |
| v0.9.28 | 14 |
| v0.9.29 | 16 |
| v0.9.30 | 18 |
| v0.9.31 | 16 |
| v0.9.32 | 12 |
| v0.9.33 | 14 |
| v0.9.34 | 13 |
| v0.9.35 | 10 |
| v0.9.36 | 14 |
| v0.9.37 | 15 |
| **v0.9.38** | **15** |
| **Total** | **173** |

### Style conventions

- All 3 plans mirror the `## Findings → ## Fix → ## Tests → ## Rejected alternatives → ## Dependency graph → ## Notes for executors` structure established in the v0.9.27..v0.9.37 plans.
- All 3 plans name the **real** audit finding (the line + the duplicated concept + the SOURCE comment if it documents the duplication).
- All 3 plans surface a **cross-cutting hook** to the v0.9.x cycle conventions (plan 116 → single-source-of-truth; plan 117 → thin route layer; plan 118 → blameless per-fight errors).
"""


def main() -> int:
    if not README.exists():
        print(f"ERROR: {README} not found", file=sys.stderr)
        return 1

    text = README.read_text(encoding="utf-8")

    if MARKER in text:
        print(f"NOTICE: {MARKER!r} already present in {README}; no-op.")
        return 0

    if PRECEDING_HEADER not in text:
        print(
            f"ERROR: preceding marker {PRECEDING_HEADER!r} not found in {README}; "
            "did the prior v0.9.37 inserter run?",
            file=sys.stderr,
        )
        return 1

    # Insert the new block right after the v0.9.37 section. We
    # approximate "end of the v0.9.37 section" as the next
    # '## v0.9.X' or '## ' line at the same heading level. Since the
    # README follows a strict '## v0.9.NN audit (...)' pattern,
    # the insertion point is the next sibling '## v' line. We
    # conservatively insert BEFORE the next '## ' sibling section.
    lines = text.splitlines(keepends=True)
    insert_idx: int | None = None
    for idx, line in enumerate(lines):
        if line.startswith("## ") and line != PRECEDING_HEADER + "\n":
            # Skip past the v0.9.37 section's own headers. We
            # find the IMMEDIATELY-NEXT '## v' line that is NOT
            # the v0.9.37 header itself.
            if idx == 0:
                continue
            insert_idx = idx
            break
    if insert_idx is None:
        # Fallback: append at the end of the file (shouldn't happen
        # given the v0.9.x README structure but defensive).
        insert_idx = len(lines)

    new_lines = lines[:insert_idx] + [INSERT_BLOCK] + lines[insert_idx:]
    README.write_text("".join(new_lines), encoding="utf-8")
    print(f"OK: inserted {MARKER!r} at line {insert_idx + 1} of {README}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
