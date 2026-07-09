#!/usr/bin/env python3
"""Idempotent helper: insert the v0.9.32 audit section into plans/README.md.

Pattern matches _insert_v0927_section.py through _insert_v0931_section.py:
writes the section template literal to file if and only if the
v0.9.32 header is NOT already present, and places it just before
"## v0.9.31 audit (current)" so the section-order invariant (newest
always closest to the top of the closed history block) holds. Refuses
to re-run on consecutive invocations.
"""
from __future__ import annotations

import sys
from pathlib import Path

README = Path("plans/README.md")
V0932_HEADER = "## v0.9.32 audit (current)"
V0932_ANCHOR = "## v0.9.31 audit (current)"


SECTION_TEMPLATE = """## v0.9.32 audit (current)

**Author:** senior-advisor read-only audit pass. **Status:** current cycle.

**Scope.** `libs/gw2_evtc_parser/src/gw2_evtc_parser/{interface.py, __main__.py, exceptions.py, __init__.py}` + `libs/gw2_evtc_parser/pyproject.toml` — the CLI surface + the Parser Protocol surface + the exception tree + the package-level `__version__`. `parser.py` is the corpus per v0.9.21; the 4 files listed were the holdouts.

| Plan | File(s) touched | Risk | LOC delta |
| --- | --- | --- | --- |
| **098** | `libs/gw2_evtc_parser/src/gw2_evtc_parser/__init__.py` + `libs/gw2_evtc_parser/pyproject.toml` | low — `importlib.metadata` pattern (matches the 4 sibling libs via plans 042 / 054 / 077 / 089 / 092); includes a `pyproject.toml` bump `0.1.0` -> `0.5.0` (closing the WORST drift in the 5-library workspace). Note: plan 042 supposedly migrated this lib but did not ship; plan 098 closes the document-but-not-implemented gap. | +7, -1 |
| **099** | `libs/gw2_evtc_parser/src/gw2_evtc_parser/interface.py` | low — pure docstring update adding `BuffRemovalEvent` + the Phase 8 yields-BOTH-events explanation. No signature change; no behaviour change; no import change. | +30, -10 |
| **100** | `libs/gw2_evtc_parser/src/gw2_evtc_parser/__main__.py` | low-medium — `inspect-zip` OOM fix (`zf.read(name)[:16]` -> `zf.open(name).read(16)`); for 50-200 MB EVTC entries the CLI currently decompresses the entire entry into RAM just to display 16 head bytes. | +5, -2 |

**Dependency graph.** All three plans touch DISJOINT file regions: 098 touches `__init__.py` + `pyproject.toml`; 099 touches `interface.py` docstring; 100 touches `__main__.py` line ~92. PRs can land concurrently.

**Plan 042 reconciliation**: The historical commit log claims "v0.9.x plan 042 shipped gw2_evtc_parser migration to importlib.metadata". Reviewing the current `__init__.py` shows the migration NEVER SHIPPED — the literal `"0.5.0"` is still there. Plan 098 closes this gap retroactively. Recommended CHANGELOG entry (not required by this plan): one line noting "v0.9.32 plan 098 closes the v0.9.x plan-042 promised-but-never-shipped migration".

**Rejected alternatives (14 total across the 3 plans).** Highlights:

- **Plan 098 alternative: leave the drift; bump only the `__init__.py` literal to "0.1.0" to match pyproject** — the runtime literal `"0.5.0"` was someone's attempt to reflect the actual code state (Phase 8 events, etc.); reverting it to `0.1.0` reverses the documentation effort. REJECTED.
- **Plan 098 alternative: leave the drift; bump only `pyproject.toml` to "0.5.0" without touching `__init__.py`** — works for the next release but loses the test-layer invariant. REJECTED.
- **Plan 099 alternative: also update the implementation `parse_events` docstring in `parser.py` to match (DRY)** — cross-file dedup is a separate concern, recommended as a v0.9.x follow-up. Out of scope for this audit. REJECTED.
- **Plan 099 alternative: add a separate `parse_buff_strips(self, source) -> Iterator[BuffRemovalEvent]` method to the Protocol** — splits the API surface; legacy callers would have to switch method calls. The Phase 8 discriminated-union design is the cleaner single-method abstraction. REJECTED.
- **Plan 100 alternative: cap the head peek to N bytes via a `MAX_HEAD_BYTES` constant** — `read(16)` already caps; the issue is the underlying `zf.read()` call that pulls the FULL entry. The streaming `zf.open` is the right fix. REJECTED.
- **Plan 100 alternative: skip the head peek entirely; show only entry metadata** — removes a useful debugging affordance (the head peek is for "does this look like a real EVTC?"). The streaming fix keeps the affordance. REJECTED.

**Test count.** 5 + 3 + 4 = **12 new hermetic tests** across the 3 plans.

**Conventions for the executor.** All 3 plans:
- Touch **only** the listed files; no incidental edits.
- 098 matches the `importlib.metadata` import block pattern from the 4 sibling libs.
- 099 is documentation-only; the next person who reads `parse_events` will see the Phase 8 contract documented in the Protocol.
- 100 is a one-line streaming fix; the only behaviour change is that `inspect-zip <large>.zevtc` no longer OOMs.

"""


def main() -> int:
    text = README.read_text(encoding="utf-8")
    if V0932_HEADER in text:
        print(f"[skip] {V0932_HEADER!r} already present; no-op.")
        return 0

    if V0932_ANCHOR not in text:
        print(f"[error] anchor {V0932_ANCHOR!r} not found; abort.", file=sys.stderr)
        return 1

    replacement = SECTION_TEMPLATE + V0932_ANCHOR
    updated = text.replace(V0932_ANCHOR, replacement, 1)
    README.write_text(updated, encoding="utf-8")
    print(f"[ok] inserted {V0932_HEADER!r} (anchor: {V0932_ANCHOR!r}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
