#!/usr/bin/env python3
"""Idempotent helper: insert the v0.9.36 audit section into plans/README.md.

Pattern matches _insert_v0927_section.py through _insert_v0935_section.py:
writes the section template literal to file if and only if the
v0.9.36 header is NOT already present, and places it just before
"## v0.9.35 audit (current)" so the section-order invariant (newest
always closest to the top of the closed history block) holds. Refuses
to re-run on consecutive invocations.
"""

from __future__ import annotations

import sys
from pathlib import Path

README = Path("plans/README.md")
V0936_HEADER = "## v0.9.36 audit (current)"
V0936_ANCHOR = "## v0.9.35 audit (current)"


SECTION_TEMPLATE = """## v0.9.36 audit (current)

**Author:** senior-advisor read-only audit pass. **Status:** current cycle.

**Scope.** `libs/gw2_analytics/src/gw2_analytics/aggregate.py` (the orchestrator) + `libs/gw2_analytics/tests/test_*.py` (the 10 test files in the ``libs/gw2_analytics/tests`` package, including the orchestrator's test + the 9 sibling aggregator tests). Per v0.9.17 plan 055 + v0.9.27 plans 083-085, the orchestrator + 2 of the 9 sibling aggregators + 3 sibling tests were touched at the surface level. The deeper DRY + invariant-enforcement surfaces (test fixture factories + cross-field pydantic v2 validators) were never audited.

| Plan | File(s) touched | Risk | LOC delta |
| --- | --- | --- | --- |
| **110** | NEW `libs/gw2_analytics/tests/_fixtures.py` + 2 modified test files | low — extract `_player` + `_npc` + `_fight` + `_FIXED_FIGHT_ID` to a shared `_fixtures` module. Local aliases preserve every call site; runtime byte-identical. | +90, -45 |
| **111** | NEW `libs/gw2_analytics/tests/_event_fixtures.py` + 5 modified test files | low-medium — consolidate `_damage` + `_heal` + `_strip` factories with 4 divergent parameter-naming conventions. Canonical-42-44 skill_id default + domain-named parameter style. Future ripple reductions for event-field additions. | +120, -55 |
| **112** | `libs/gw2_analytics/src/gw2_analytics/aggregate.py` | low — migrate `SingleFightAggregator._check_invariants` static method to ``@model_validator(mode="after")`` on the ``FightAggregate`` Pydantic model. Self-validating schema; closes the documented direct-construct defense-in-depth gap. | +30, -18 |

**Dependency graph.** All three plans touch DISJOINT file regions: 110 introduces a NEW `tests/_fixtures.py` + imports in 2 test files; 111 introduces a NEW `tests/_event_fixtures.py` + imports in 5 test files; 112 touches `aggregate.py` only. PRs can land concurrently.

**Cross-cutting thematics**:

- **Test fixture DRY (Plans 110 + 111)**: the synthetic ``_player``+``_npc``+``_fight`` triple was duplicated near-bytely across ``test_aggregate.py`` + ``test_multi_fight.py`` (Plan 110); the synthetic ``_damage``+``_heal``+``_strip`` events were duplicated with 4 divergent parameter-naming conventions (Plan 111) across ``test_target_dps.py`` + ``test_target_healing.py`` + ``test_target_buff_removal.py`` + ``test_squad_rollup.py`` + ``test_per_fight_timeline.py``.
- **Schema self-validation (Plan 112)**: a documented defense-in-depth test (``test_aggregate_rejects_empty_fight_id_via_model_construct``) already proves the schema is under-defended for direct ``model_construct(...)`` / ``model_validate(...)`` paths. The migration to ``@model_validator(mode="after")`` closes that documented gap AT THE SCHEMA level (the canonical pydantic v2 hook), not in the aggregator.

**Rejected alternatives (14 total across the 3 plans).** Highlights:

- **Plan 110 alternative: drop the `_player` / `_npc` / `_fight` aliases and rename every call site** — invasive (12-15 test call sites per file). The aliases preserve the call sites; the import block is the single change. REJECTED.
- **Plan 111 alternative: keep divergent skill_id defaults — "42 / 43 / 44 is arbitrary anyway"** — true, but the divergent values across files (``1/2/3`` in squad_rollup vs ``42/43/44`` in timeline) ARE the maintenance hazard. The canonical-42-44 is a defensible arbitrary that survives the consolidation. REJECTED.
- **Plan 111 alternative: use the `value` parameter-naming convention everywhere** — `value` is the cbtevent-layer name (the raw integer payload); the aggregator surfaces it as `damage` / `healing` / `buff_removal`. The canonical helper picks the DOMAIN convention. REJECTED.
- **Plan 112 alternative: keep the static method AND add a `@model_validator`** — dual enforcement is DRY violation (3 invariants declared twice). REJECTED.
- **Plan 112 alternative: move invariants to `MultiFightAggregator` (per plan 055 architecture)** — wrong location. The invariants are about the OUTPUT ``FightAggregate`` schema, not the cross-fight rollup. REJECTED.

**Test count.** 4 + 6 + 4 = **14 new hermetic tests** across the 3 plans.

**Conventions for the executor.** All 3 plans:
- Touch **only** the listed files; no incidental edits.
- 110 + 111 introduce private (``_`` prefix) helper modules; the test consumer keeps the canonical pattern (no `@pytest.fixture` decorator; module-level pure functions).
- 112 is a metadata-only-validated migration: the schema now self-validates; future direct ``FightAggregate.model_validate(...)`` paths (e.g. a future ORM-to-schema mapper) inherit the invariants automatically. Zero test strictly fails on the migration (the 3 invariants are still enforced; the surface that enforces them changed).

"""


def main() -> int:
    text = README.read_text(encoding="utf-8")
    if V0936_HEADER in text:
        print(f"[skip] {V0936_HEADER!r} already present; no-op.")
        return 0

    if V0936_ANCHOR not in text:
        print(f"[error] anchor {V0936_ANCHOR!r} not found; abort.", file=sys.stderr)
        return 1

    replacement = SECTION_TEMPLATE + V0936_ANCHOR
    updated = text.replace(V0936_ANCHOR, replacement, 1)
    README.write_text(updated, encoding="utf-8")
    print(f"[ok] inserted {V0936_HEADER!r} (anchor: {V0936_ANCHOR!r}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
