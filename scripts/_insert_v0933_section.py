#!/usr/bin/env python3
"""Idempotent helper: insert the v0.9.33 audit section into plans/README.md.

Pattern matches _insert_v0927_section.py through _insert_v0932_section.py:
writes the section template literal to file if and only if the
v0.9.33 header is NOT already present, and places it just before
"## v0.9.32 audit (current)" so the section-order invariant (newest
always closest to the top of the closed history block) holds. Refuses
to re-run on consecutive invocations.
"""
from __future__ import annotations

import sys
from pathlib import Path

README = Path("plans/README.md")
V0933_HEADER = "## v0.9.33 audit (current)"
V0933_ANCHOR = "## v0.9.32 audit (current)"


SECTION_TEMPLATE = """## v0.9.33 audit (current)

**Author:** senior-advisor read-only audit pass. **Status:** current cycle.

**Scope.** `web/src/components/*` (PlayerTimelineLegend, CsvDownloadButton, PlayerSearchBar, FightsGrid, PlayersGrid, SkillUsageTable, SquadRollupsGrid, EventWindowsChart, PerFightTimelineSection) + `web/src/lib/*` (env.ts, csv.ts, api.ts) — the shared React components + the lib utility surface never audited in depth. v0.9.7 covered the 7 page.tsx; v0.9.22 covered layout.tsx + CSS; v0.9.25 peripherally touched ag-grid-setup.ts via plan 078; v0.9.13 covered the test infrastructure (vitest + playwright + setup.ts + mock-server.mjs). The 12 files in this scope are the shared runtime surface consumed by every page.

| Plan | File(s) touched | Risk | LOC delta |
| --- | --- | --- | --- |
| **101** | `web/src/lib/csv.ts` + 4 components | low — interface merge from `SquadRollupColumn` + `CsvColumn` to unified `RollupColumn<TRow>` (with backward-compat `CsvColumn` type alias); no runtime behaviour change | +20, -12 |
| **102** | `web/src/app/globals.css` + 2 components | low — extract `#f59e0b` warm-orange strip colour from `PlayerTimelineLegend.tsx` into the canonical `--strip` CSS token; add the matching third legend swatch in `EventWindowsChart.tsx` (documentation-only, no data change) | +5, -2 |
| **103** | `web/src/lib/env.ts` + `web/.env.example` | low-medium — rename env var to Next.js-canonical `NEXT_PUBLIC_API_BASE_URL` (works BOTH server + client) + add production fail-fast guard for the previously-silent `"http://localhost:8000"` fallback | +25, -8 |

**Dependency graph.** All three plans touch DISJOINT file regions: 101 affects type definitions (lib/csv.ts) + 4 consumers; 102 affects the global CSS colour tokens + 2 inline-styled components; 103 affects the env-resolution module + the .env.example doc. PRs can land concurrently.

**Cross-cutting thematics**:

- **DRY (Plan 101)**: same column-spec concept was duplicated across `lib/csv.ts::CsvColumn` + `components/SquadRollupsGrid.tsx::SquadRollupColumn` (only `width` and AG-Grid-rendering defaults differ). Merged into `RollupColumn<TRow>`.
- **Canonical tokens (Plan 102)**: extracted the hardcoded `#f59e0b` hex literal into the global `--strip` CSS var, following the `plan 070 v0.9.22` DRY utility extraction pattern.
- **Canonical conventions (Plan 103)**: aligns env var resolution with the Next.js convention (`NEXT_PUBLIC_*` prefix for client-bundled vars) + adds a production fail-fast guard for the silent localhost fallback. Closes the gap `plan 033 v0.9.7` documented but never wired.

**Rejected alternatives (11 total across the 3 plans).** Highlights:

- **Plan 101 alternative: keep the two interfaces distinct, add a `csvOf(gridColumn)` adapter** — adds a runtime adapter without removing the duplication. The two surfaces ARE the same concept. REJECTED.
- **Plan 101 alternative: hoist `RollupColumn` to a new `web/src/lib/columns.ts` module** — adds a new file for a 4-field interface; the console pulse is to keep this adjacent to its primary consumer (`lib/csv.ts`). REJECTED.
- **Plan 102 alternative: replace the THREE colours with a single `Palette` object** — overengineering for 3 hex literals; the canonical token system (CSS vars) is the lower-cost fix. REJECTED.
- **Plan 103 alternative: drop the silent `"http://localhost:8000"` fallback entirely (require the env var in dev too)** — breaks local-dev DX (every contributor would need to create a `.env.local` just to run `pnpm dev`). The dev fallback + production fail-fast is the canonical Next.js pattern. REJECTED.
- **Plan 103 alternative: add a runtime warning instead of throwing in production** — silent warnings vs loud throws; the production-misconfig foot-gun deserves the loud fail. Runtime warning would be silently logged in the operator's hosting platform, often ignored. REJECTED.

**Test count.** 5 + 4 + 5 = **14 new hermetic tests** across the 3 plans.

**Conventions for the executor.** All 3 plans:
- Touch **only** the listed files; no incidental edits.
- 101 ends with a backward-compat `CsvColumn<TRow> = RollupColumn<TRow>` type alias so existing imports keep working.
- 102 adds the `--strip` token to the current `:root { ... }` block in `globals.css`; the third `<span>` legend entry in `EventWindowsChart.tsx` is documentation-only (the chart's bars don't render strip data today because `EventBucket.buff_removal_total` doesn't exist yet per plan 083).
- 103 changes the env resolution at module load time — the `lib/api.ts` consumer sees a unified canonical export name `API_BASE_URL`, no import-path changes required.

"""


def main() -> int:
    text = README.read_text(encoding="utf-8")
    if V0933_HEADER in text:
        print(f"[skip] {V0933_HEADER!r} already present; no-op.")
        return 0

    if V0933_ANCHOR not in text:
        print(f"[error] anchor {V0933_ANCHOR!r} not found; abort.", file=sys.stderr)
        return 1

    replacement = SECTION_TEMPLATE + V0933_ANCHOR
    updated = text.replace(V0933_ANCHOR, replacement, 1)
    README.write_text(updated, encoding="utf-8")
    print(f"[ok] inserted {V0933_HEADER!r} (anchor: {V0933_ANCHOR!r}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
