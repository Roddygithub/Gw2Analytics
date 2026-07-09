#!/usr/bin/env python3
"""Idempotent helper: insert the v0.9.30 audit section into plans/README.md.

Pattern matches _insert_v0927_section.py through _insert_v0929_section.py:
writes the section template literal to file if and only if the
v0.9.30 header is NOT already present, and places it just before
"## v0.9.29 audit (current)" so the section-order invariant (newest
always closest to the top of the closed history block) holds. Refuses
to re-run on consecutive invocations.
"""
from __future__ import annotations

import sys
from pathlib import Path

README = Path("plans/README.md")
V0930_HEADER = "## v0.9.30 audit (current)"
V0930_ANCHOR = "## v0.9.29 audit (current)"


SECTION_TEMPLATE = """## v0.9.30 audit (current)

**Author:** senior-advisor read-only audit pass. **Status:** current cycle.

**Scope.** `libs/gw2_api_client/src/gw2_api_client/{__init__.py, client.py, exceptions.py}` + `libs/gw2_api_client/pyproject.toml` — the 5th and last workspace library (HTTP client wrapping the GW2 v2 REST API) never audited in depth. The 4 sibling libraries (`gw2_core`, `gw2_evtc_parser`, `gw2_analytics`, `gw2analytics_api`) were all covered by earlier passes; `gw2_api_client` was the holdout.

| Plan | File(s) touched | Risk | LOC delta |
| --- | --- | --- | --- |
| **092** | `libs/gw2_api_client/src/gw2_api_client/__init__.py` | low — `importlib.metadata` pattern (replicated across the other 4 libs via plans 042 / 054 / 077 / 089); no `pyproject.toml` change because there's no drift today | +7, -1 |
| **093** | `libs/gw2_api_client/src/gw2_api_client/client.py` + `exceptions.py` | low — semantic rename of `_MAX_RATE_LIMIT_RETRIES` -> `_MAX_RATE_LIMIT_ATTEMPTS` (off-by-one footgun prevention) + removal of soft-dead `auth_required` flag in private `_get_with_retries` helper. PUBLIC Protocol surface unchanged. | +12, -16 |
| **094** | `libs/gw2_api_client/src/gw2_api_client/client.py` | medium — strip `/v2` from `_BASE_URL` (single-source-of-truth) + attach Authorization header per-request (closes the API-key-leak hazard on the public `/v2/worlds` endpoint). PUBLIC Protocol signatures unchanged. | +14, -5 |

**Dependency graph.** All three plans touch disjoint file regions: 092 touches `__init__.py`; 093 + 094 both touch `client.py` BUT touch disjoint regions (093 = `_get_with_retries` + `_MAX_RATE_LIMIT_ATTEMPTS` rename; 094 = `_BASE_URL` constant + `__init__` constructor + `_auth_headers` helper + call-sites in `account_get` / `worlds_get`). Pair-suggested ordering: 092 alone; 093 + 094 as ONE single-PR on `client.py` to avoid two PRs editing the same file in the same release window.

**Rejected alternatives (15 total across the 3 plans).** Highlights:

- **Plan 092 alternative: leave the literal at `"0.1.0"` since there's no drift today** — fine today, but releases drift without a test-layer invariant. The 4 sibling libs all moved to dynamic for the same reason; leaving `gw2_api_client` static would be the ONE library in the workspace that breaks the 5-library pattern.
- **Plan 092 alternative: bump the literal to `"1.0.0"` without touching `pyproject.toml`** — introduces drift that the future test can't catch (no test fixture). The dynamic lookup is what enforces the invariant.
- **Plan 093 alternative: keep `_MAX_RATE_LIMIT_RETRIES` with a longer docstring explaining the off-by-one hazard** — idiomatic Python (PEP 8: short, meaningful names) prefers the rename to the LLM-eating docstring. The replacement name `_MAX_RATE_LIMIT_ATTEMPTS` is self-explanatory.
- **Plan 093 alternative: add a typed `GuildWars2AuthError` exception subclass to make the `auth_required` distinction meaningful** — bigger design change (new public exception surface, cross-library impact on `apps/api` `except` clauses). Out of scope for this audit pass; the minimal fix is to drop the soft-dead flag.
- **Plan 094 alternative: build two httpx clients (one with Authorization, one without) and pick per-request** — doubles the connection pool, complicates the `aclose` lifecycle, and adds memory overhead per client instance. Per-request header attachment is the simpler fix.
- **Plan 094 alternative: hoist the API version (`/v2`) into a NEW constant `_API_VERSION = "v2"` used in BOTH `_BASE_URL` AND per-call URLs** — doubles up the constant surface without changing the fragility. The single-source-of-truth fix is to put the version in ONE place (the per-call URL is the more discoverable one).
- **Plan 094 alternative: leave `_BASE_URL` + per-call URLs with the duplicated `/v2`** — fine today but tech debt; the moment someone adds a v3 endpoint or a parameterized URL helper, the duplication bites. The strip is a 1-line fix with a 6-line test payoff.
- **Plan 094 alternative: add `httpx.Transport` middleware to strip the Authorization header at the wire layer** — invisible-to-the-caller; surprising for future contributors reading the code. The per-request dictionary kwarg is the standard httpx pattern.

**Test count.** 5 + 6 + 7 = **18 new hermetic tests** across the 3 plans.

**Conventions for the executor.** All 3 plans:
- Touch **only** the listed files; no incidental edits.
- Re-use the canonical `importlib.metadata` import style applied by plans 042 / 054 / 077 / 089; no new top-level deps.
- Match the 5-library workspace convention via the 18 new hermetic tests below.
- Plan 094's per-request Authorization pattern propagates as the recommended idiom for any future endpoint additions in the same library.

"""


def main() -> int:
    text = README.read_text(encoding="utf-8")
    if V0930_HEADER in text:
        print(f"[skip] {V0930_HEADER!r} already present; no-op.")
        return 0

    if V0930_ANCHOR not in text:
        print(f"[error] anchor {V0930_ANCHOR!r} not found; abort.", file=sys.stderr)
        return 1

    replacement = SECTION_TEMPLATE + V0930_ANCHOR
    updated = text.replace(V0930_ANCHOR, replacement, 1)
    README.write_text(updated, encoding="utf-8")
    print(f"[ok] inserted {V0930_HEADER!r} (anchor: {V0930_ANCHOR!r}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
