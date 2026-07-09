#!/usr/bin/env python3
"""Idempotent helper: insert the v0.9.34 audit section into plans/README.md.

Pattern matches _insert_v0927_section.py through _insert_v0933_section.py:
writes the section template literal to file if and only if the
v0.9.34 header is NOT already present, and places it just before
"## v0.9.33 audit (current)" so the section-order invariant (newest
always closest to the top of the closed history block) holds. Refuses
to re-run on consecutive invocations.
"""
from __future__ import annotations

import sys
from pathlib import Path

README = Path("plans/README.md")
V0934_HEADER = "## v0.9.34 audit (current)"
V0934_ANCHOR = "## v0.9.33 audit (current)"


SECTION_TEMPLATE = """## v0.9.34 audit (current)

**Author:** senior-advisor read-only audit pass. **Status:** current cycle.

**Scope.** `apps/api/alembic/env.py` + `apps/api/alembic/versions/{0001..0008}*.py` + `apps/api/src/gw2analytics_api/scripts/{backfill_player_summaries.py, health_gate.py}` — the alembic migration surface + the two CLI scripts (one-shot backfill + CI health gate). Routes (`uploads/fights/players/account/health/webhooks`) covered in v0.9.15/v0.9.25; ORM models + SQLAlchemy infrastructure covered in v0.9.31. The 11 files in this scope are the operability-migration surface never deeply audited.

| Plan | File(s) touched | Risk | LOC delta |
| --- | --- | --- | --- |
| **104** | `apps/api/alembic/versions/0003_fight_skills.py` + `0007_webhook_retry.py` + `0005_fight_player_summaries.py` | low — annotation consistency (untyped `revision = "..."` -> typed `revision: str = "..."`) + docstring typo fix (`0004` -> `0005` in 0005's docstring). Migration identifiers preserved (no alembic-hash churn). | +4, -4 |
| **105** | `apps/api/alembic/env.py` | low — add `compare_type=True` + `compare_server_default=True` kwargs to both `run_migrations_offline::context.configure()` AND `run_migrations_online::context.configure()`. Plan 061 v0.9.19 documented this fix but the env.py change never landed. | +16, -0 |
| **106** | `apps/api/src/gw2analytics_api/scripts/health_gate.py` | low-medium — add `_validate_drift_shape` helper for baseline + live-probe shape validation (currently bare `KeyError` on shape mismatch); add `--max-drift-delta` CLI flag (currently hardcoded module-level `MAX_DRIFT_DELTA = 2` constant). | +35, -4 |

**Dependency graph.** All three plans touch DISJOINT file regions: 104 affects 3 version files (metadata-only); 105 affects `env.py` only; 106 affects `health_gate.py` only. PRs can land concurrently.

**Cross-cutting thematics**:

- **DRY (Plan 104)**: same alembic revision-identifier shape was declared in 2 styles across the 8 migrations (typed annotation in 0001/0002/0004/0005/0006/0008; bare literal in 0003/0007). Standardized.
- **Autogen correctness (Plan 105)**: alembic `context.configure()` is type-blind + server-default-blind by default; the 2 kwargs enable future `--autogenerate` to detect the column-type + server-default changes that the historical 0002 + 0006 migrations did BY HAND.
- **Operator ergonomics (Plan 106)**: hardcoded `MAX_DRIFT_DELTA = 2` constant moves to a CLI flag; baseline-shape validation catches opaque `KeyError` failures at CI time with explicit "re-capture baseline" guidance.

**Rejected alternatives (12 total across the 3 plans).** Highlights:

- **Plan 104 alternative: move the annotations to a shared `_migration_template.py` and import from each** — alembic scripts MUST be standalone modules (no shared imports allowed in the `versions/` directory per alembic's design); each script is the unit of version control. The in-file pattern is mandatory. REJECTED.
- **Plan 105 alternative: set the flags globally in `alembic.ini`** — works but is less discoverable than the in-file kwargs. A future contributor looking at `env.py` would miss the global setting. The kwargs pattern is the alembic-recommended approach. REJECTED.
- **Plan 105 alternative: add `compare_type=True` only (skip `compare_server_default=True`)** — leaves the second drift hazard in place. Both are needed.
- **Plan 106 alternative: use Pydantic v2 `SummaryDrift.model_validate(baseline)` for shape validation** — the `SummaryDrift` TypedDict is a static-only annotation, NOT a runtime validator. The minimal-fix shape check (3 lines) is the right scoped fix. REJECTED.
- **Plan 106 alternative: drop the `MAX_DRIFT_DELTA` constant entirely; require the CLI flag** — breaks the canonical-script invocation. The constant-as-default pattern preserves the canonical invocation while enabling operator tuning.

**Test count.** 4 + 4 + 5 = **13 new hermetic tests** across the 3 plans.

**Conventions for the executor.** All 3 plans:
- Touch **only** the listed files; no incidental edits.
- 104 is metadata-only — alembic hash unchanged, runtime schema unchanged.
- 105 enables future autogen correctness; historical migrations (0002 + 0006) remain valid because they were hand-authored.
- 106 stays hermetic: the script does NOT import `gw2_analytics_api.health`'s Pydantic models (which would couple it to the FastAPI app); the inline `_validate_drift_shape` is the canonical Lite pattern.

"""


def main() -> int:
    text = README.read_text(encoding="utf-8")
    if V0934_HEADER in text:
        print(f"[skip] {V0934_HEADER!r} already present; no-op.")
        return 0

    if V0934_ANCHOR not in text:
        print(f"[error] anchor {V0934_ANCHOR!r} not found; abort.", file=sys.stderr)
        return 1

    replacement = SECTION_TEMPLATE + V0934_ANCHOR
    updated = text.replace(V0934_ANCHOR, replacement, 1)
    README.write_text(updated, encoding="utf-8")
    print(f"[ok] inserted {V0934_HEADER!r} (anchor: {V0934_ANCHOR!r}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
