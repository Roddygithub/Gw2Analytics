#!/usr/bin/env python3
"""Idempotent helper: insert the v0.9.29 audit section into plans/README.md.

Pattern matches the _insert_v0927_section.py + _insert_v0928_section.py
helpers: write the section template literal to stdout-by-side-effect if and
only if the v0.9.29 header is NOT already in the file, and place it just
before the "## v0.9.22 audit (closed)" section so the section-order
invariant (newest before oldest) is preserved. Refuses to re-run on
consecutive invocations: a second call prints a "no-op (already present)"
banner and exits 0 so the basher+grep pipe in the parent turn stays clean.
"""
from __future__ import annotations

import sys
from pathlib import Path

README = Path("plans/README.md")
V0929_HEADER = "## v0.9.29 audit (current)"
V0929_ANCHOR = "## v0.9.22 audit (closed)"


SECTION_TEMPLATE = """## v0.9.29 audit (current)

**Author:** senior-advisor read-only audit pass. **Status:** current cycle.

**Scope.** `libs/gw2_core/src/gw2_core/__init__.py` + `libs/gw2_core/src/gw2_core/models.py` + `libs/gw2_core/pyproject.toml` — the foundational data-model library, never audited in depth (plan 037 referenced `gw2_core` as the source-of-truth for `disambiguate_elite_spec` but that function wasn't shipped; plan 042 migrated 3 sibling libs to `importlib.metadata.version()`; `gw2_core` is the only library still doing the literal `__version__ = "0.X.Y"` thing).

| Plan | File(s) touched | Risk | LOC delta |
| --- | --- | --- | --- |
| **089** | `libs/gw2_core/src/gw2_core/__init__.py` + `libs/gw2_core/pyproject.toml` | low — canonical `importlib.metadata` pattern (replicated across 4 sibling libs via plans 042 / 054 / 077) | +7, -1 |
| **090** | `libs/gw2_core/src/gw2_core/models.py` | medium — new public surface (`disambiguate_elite_spec`) + dispatch table; closes the "import fails" hazard for plan 065 parser call-site | +54, -2 |
| **091** | `libs/gw2_core/src/gw2_core/models.py` | low — `AliasChoices` adds a 2nd accepted wire key, doesn't drop the first | +8, -2 |

**Dependency graph.** All three plans touch disjoint file regions:
089 touches `__init__.py` + `pyproject.toml`; 090 touches the `EliteSpec` enum block in `models.py`; 091 touches the `AccountInfo` model field. PRs can land in any order or concurrently. Plan 090 is the only OUTBOUND edge: it's REQUIRED-BY plan 065 v0.9.21 (the parser call-site fix that imports `disambiguate_elite_spec`) — without 090, plan 065 ships an import that resolves to `ImportError`.

**Rejected alternatives (15 total across the 3 plans).** Highlights:

- **Plan 089 alternative: edit the literal `__version__` to "0.5.0" and forget about it** — defeats the entire point of dynamic resolution and re-opens the drift on the next release. The 4 sibling libs all moved to dynamic for this exact reason. REJECTED.
- **Plan 090 alternative: bake the disambiguation into `EliteSpec.from_raw(raw, profession)` as a classmethod** — awkward (enums don't take external params in their constructor) and hides the dispatch table from `repr(EliteSpec)`.
- **Plan 090 alternative: move the dispatch table to `libs/gw2_evtc_parser` instead of `gw2_core`** — conceptually backwards: the parser imports game data FROM `gw2_core` (per `__init__.py`'s module docstring); the dispatch IS game data.
- **Plan 090 alternative: forbid the bare `EliteSpec(raw)` cast at runtime** (raise `TypeError`) — breaks the parser's read path BEFORE the helper is called; the docstring + parser-side plan 065 enforcement are the right layer.
- **Plan 091 alternative: drop the alias entirely and rename the field back to plain `world_id` (no wire alias)** — breaking change for all callers sending `{"world": ...}`. Today the library offers a compatibility shim; removing it is a regression. REJECTED.
- **Plan 091 alternative: use `model_config[populate_by_name] = True` instead of `AliasChoices`** — `populate_by_name` lets you use the Python-name as input but DOES NOT support accepting MULTIPLE wire keys. The dual-key requirement is exactly what `AliasChoices` is for.
- **Plan 091 alternative: leave as-is — "the API hasn't broken yet"** — fine today, but tech debt. The 2023-2024 v2 API modernisation wave ArenaNet ran on other endpoints (e.g. `worlds` schema consolidation) sets the precedent; `accounts.world` → `accounts.world_id` is a guaranteed-future schema change.
- **Plan 091 alternative: use `Field(alias=AliasChoices(...))` (the old combined `alias` parameter)** — `validation_alias` + `serialization_alias` are more explicit; latest Pydantic v2 emits a `DeprecationWarning` when a dict is passed to the combined `alias=` slot with two keys.

**Test count.** 5 + 6 + 4 = **15 new hermetic tests** across the 3 plans.

**Conventions for the executor.** All 3 plans:
- Touch **only** the listed files; no incidental edits.
- Are additive-only except plan 089 which RETIRES the stale literal `__version__ = "0.5.0"` (the dynamic lookup replaces it, not augments it).
- Re-use the canonical `gw2_core` import style (`from pydantic import ...`, `from __future__ import annotations`); no new top-level deps.
- Match the docstring ↔ implementation ↔ test invariant via the 15 new hermetic tests below.

"""


def main() -> int:
    text = README.read_text(encoding="utf-8")
    if V0929_HEADER in text:
        # No-op on re-run; the parent's basher pipe expects exit 0 either way.
        print(f"[skip] {V0929_HEADER!r} already present; no-op.")
        return 0

    if V0929_ANCHOR not in text:
        print(f"[error] anchor {V0929_ANCHOR!r} not found; abort.", file=sys.stderr)
        return 1

    replacement = SECTION_TEMPLATE + V0929_ANCHOR
    updated = text.replace(V0929_ANCHOR, replacement, 1)
    README.write_text(updated, encoding="utf-8")
    print(f"[ok] inserted {V0929_HEADER!r} (anchor: {V0929_ANCHOR!r}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
