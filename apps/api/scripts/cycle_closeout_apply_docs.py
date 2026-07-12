#!/usr/bin/env python3
"""Cycle close-out doc-applier.

Hardened production-safe successor to ``/tmp/v0.10.19_apply_docs.py``
(archived to the canonical location at
``apps/api/scripts/cycle_closeout_apply_docs.py``).

Production-safety contract:
1. No ``assert`` statements (they're stripped under ``python -O``).
   All anchor checks use ``if X not in Y: raise SystemExit(msg)``.
2. No silent fallbacks for missing anchors. The script HARD-FAILS
   with ``SystemExit(msg)`` if any anchor is missing — a fragmented
   ROADMAP / double-spliced CHANGELOG is worse than a loud crash.
3. MARKER is required (passed via ``--marker`` argparse argument).
   No default; the script refuses to run without an explicit
   cycle-window marker SHA.

Usage::

    python apps/api/scripts/cycle_closeout_apply_docs.py --marker cd6e9ad

The script reads 3 pre-authored doc bodies from ``/tmp`` and writes
them to the canonical git tree paths. The cycle-end audit filename
is the cycle-end date + the marker SHA::

    plans/AUDIT-2026-07-<cycle-end-date>-<marker-sha>.md

The pre-authored doc bodies MUST be staged at::

    /tmp/v0.10.<n>.<m>_changelog_entry.md
    /tmp/v0.10.<n>.<m>_audit_template.md

(driven by the cycle-major.minor.patch version). The literal token
``MARKER`` in each body is substituted with the actual marker SHA
before write.

ROADMAP.md is mutated in place via 4 surgical edits (no /tmp file):
1. stamp-refresh -> current cycle anchor + cycle-end date.
2. "Current state" section heading rewrite.
3. "Latest shipped tag" line rewrite to the new cycle.
4. §1.2 v1.0 candidates table clarification comment append.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# Canonical repo root. Override via ``GW2ANALYTICS_ROOT`` env var for
# in-memory scratch-repo tests (see apps/api/tests/test_cycle_closeout_apply_docs.py).
DEFAULT_ROOT = Path("/home/roddy/Gw2Analytics")


class _CyleCloseOutError(SystemExit):
    """Subclass so 'grep -n _CyleCloseOutError' finds script-side exits."""


def _abort(msg: str) -> _CyleCloseOutError:
    """Build a SystemExit carrying ``msg``.

    Returns the SystemExit instance so callers can ``raise _abort(...)``
    uniformly without losing the exit-code visibility at interactive
    invocation. The SystemExit's ``code`` field is the message string
    (Python 3.10's RuntimeError-style message handling).
    """
    return _CyleCloseOutError(msg)


def apply_docs(marker: str, root: Path, audit_date: str = "2026-07-12") -> None:  # noqa: PLR0915
    """Apply the 3 close-out docs to the working tree.

    Parameters
    ----------
    marker:
        Short SHA of the cycle-window marker commit. Required; must
        be the same SHA used in the annotated tag + the cycle-end
        audit filename.
    root:
        Path to the repository root. Tests override this for in-memory
        scratch-repo fixtures.
    """
    if not marker:
        raise _abort("MARKER must be provided explicitly (no silent defaults).")

    # Template root override for test isolation. The smoke test in
    # apps/api/tests/test_cycle_closeout_apply_docs.py sets this env
    # var to a pytest tmp_path so it doesn't pollute /tmp during test
    # runs. Production usage leaves this unset, defaulting to /tmp
    # where the cycle close-out workflow stages pre-authored bodies
    # before invoking the script.
    template_root = Path(
        os.environ.get("GW2ANALYTICS_TEMPLATE_DIR", "/tmp"),  # noqa: S108
    )

    # ---- 1. CHANGELOG [0.10.<n+1>] entry splice ----
    changelog_ext_path = template_root / "v0.10.19_changelog_entry.md"
    if not changelog_ext_path.exists():
        raise _abort(f"CHANGELOG entry body not found at {changelog_ext_path}")
    changelog_path = root / "CHANGELOG.md"

    ch_ext = changelog_ext_path.read_text()
    ch_ext = ch_ext.replace("MARKER", marker)
    ch_ext = re.sub(r"^\[[^\]]+\]:\s+.*\n", "", ch_ext, flags=re.MULTILINE).rstrip() + "\n\n"

    ch_main = changelog_path.read_text()
    anchor = "## [0.10.18.1]"
    idx = ch_main.find(anchor)
    if idx == -1:
        raise _abort(f"CHANGELOG.md: {anchor!r} anchor not found")

    ch_new = ch_main[:idx] + ch_ext + ch_main[idx:]

    # Production-safety guard 3: prevent silent double-splice.
    if ch_new.count("## [0.10.19]") != 1:
        raise _abort("CHANGELOG [0.10.19] entry count != 1 after splice (re-splice collision?)")

    changelog_path.write_text(ch_new)

    # ---- 2. ROADMAP 4 surgical edits ----
    roadmap_path = root / "docs" / "ROADMAP.md"
    rd = roadmap_path.read_text()

    # (2a) Stamp refresh.
    old_stamp = "Last refreshed AT v0.10.18.1 cycle\nclose-out (2026-07-13)."
    new_stamp = "Last refreshed AT v0.10.19 cycle\nclose-out (2026-07-12)."
    if old_stamp not in rd:
        raise _abort("ROADMAP stamp anchor not found (already closed-out?)")
    rd = rd.replace(old_stamp, new_stamp, 1)

    # (2b) Section heading rewrite.
    old_section = "Current state (post v0.10.18.1 cycle)"
    new_section = "Current state (post v0.10.19 cycle)"
    if old_section not in rd:
        raise _abort("ROADMAP Current-state-section anchor not found")
    rd = rd.replace(old_section, new_section, 1)

    # (2c) Latest-shipped-tag regex rewrite.
    new_latest_tag = (
        f"- **Latest shipped tag:** v0.10.19 (DEFER docs-only cycle: "
        f"3 close-out docs at marker=`{marker}` per "
        f"plans/AUDIT-2026-07-12-`{marker}`.md). The **v0.10.19 "
        f"mimo-half** cycle attempted M8 (per "
        f"`plans/RELEASE-v0.10.19.md`) but DEFERRED to v0.10.20 "
        f"after 6 iterations on `conftest.py`'s "
        f"`_disable_dotenv_for_tests` autouse fixture exhausted "
        f"the signature-shape budget against pydantic-settings' "
        f"actual call style. 3 residual failures persisted out of "
        f"the 11 M8 K-cluster failures per this cycle's CHANGELOG "
        f"`[0.10.19]` entry; v0.10.18.1 "
        f"(`plans/AUDIT-2026-07-13-2ffafc75.md`) is the canonical "
        f"K1+K2+K3 discoverer. Cycle close-out close-out cycle "
        f"stamps: `## [0.10.19]` CHANGELOG entry spliced + "
        f"`plans/RELEASE-v0.10.19.md` (M8 fix-up PRIMARY plan) + "
        f"`docs/v0.10.19-combat-readout-spike.md` (F17 sizing) + "
        f"`plans/AUDIT-2026-07-13-RETROSPECTIVE-V01017-V010181.md` "
        f"(closure thread retrospective) + "
        f"`plans/AUDIT-2026-07-12-{marker}.md` (this cycle's "
        f"close-out audit).\n"
    )

    pattern_latest_tag = re.compile(
        r"(- \*\*Latest shipped tag:\*\*.*?)(?=\n- \*\*Architecture:\*\*)",
        re.DOTALL,
    )
    if pattern_latest_tag.search(rd) is None:
        raise _abort(
            "ROADMAP Latest-shipped-tag regex did not match (architecture anchor missing?)"
        )
    rd = pattern_latest_tag.sub(lambda _m: new_latest_tag, rd, count=1)

    # Production-safety guard 4: make silent regex misses loud.
    if "v0.10.19 (DEFER docs-only cycle" not in rd:
        raise _abort("Latest-tag regex did NOT replace the prior paragraph")
    if "v0.10.17 (F18 Replay UI" in rd:
        raise _abort("v0.10.17 paragraph survived the Latest-tag regex")

    # (2d) §1.2 M8 clarification blockquote.
    m8_clarification = (
        "\n> **v0.10.19 mimo-half cycle attempt**: 6 iterations on "
        f"`conftest.py`'s `_disable_dotenv_for_tests` autouse "
        f"fixture exhausted the signature-budget against "
        f"pydantic-settings actual call style; 3 residual failures "
        f"persisted out of the 11 K-cluster per "
        f"`CHANGELOG [0.10.19]`. Forward-defer to v0.10.20 per "
        f"`plans/AUDIT-2026-07-12-{marker}.md` §2. NO "
        f"production-code regression; bucket K = Test-Substrate "
        f"Mismatch.\n"
    )
    anchor_post_section = "### 1.1 Items removed since v0.8.0"
    # Production-safety guard 2: no silent fallback for missing §1.1 anchor.
    if anchor_post_section not in rd:
        raise _abort(
            "ROADMAP §1.1 anchor missing; cannot append M8 clarification "
            "(hard-fail per production-safety contract)"
        )
    rd = rd.replace(anchor_post_section, m8_clarification + anchor_post_section, 1)

    roadmap_path.write_text(rd)

    # ---- 3. AUDIT file write ----
    audit_template_path = template_root / "v0.10.19_audit_template.md"
    if not audit_template_path.exists():
        raise _abort(f"AUDIT template body not found at {audit_template_path}")
    audit_path = root / "plans" / f"AUDIT-{audit_date}-{marker}.md"

    au = audit_template_path.read_text()
    au = au.replace("MARKER", marker)
    au = re.sub(r"^\[[^\]]+\]:\s+.*\n", "", au, flags=re.MULTILINE).rstrip() + "\n"

    audit_path.write_text(au)
    print(f"AUDIT written: {audit_path} ({len(au.splitlines())} lines)")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Parses args + dispatches to ``apply_docs``."""
    parser = argparse.ArgumentParser(
        description=(
            "Cycle close-out doc-applier. Applies the 3 close-out docs to the git working tree."
        ),
    )
    parser.add_argument(
        "--marker",
        type=str,
        required=True,
        help=(
            "Short SHA of the cycle-window marker commit "
            "(required; no default for production-safety)."
        ),
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_ROOT,
        help=(
            f"Repository root path (default: {DEFAULT_ROOT}; "
            f"override with GW2ANALYTICS_ROOT env var)."
        ),
    )
    parser.add_argument(
        "--audit-date",
        type=str,
        default="2026-07-12",
        help=("Cycle-end date for the AUDIT filename (YYYY-MM-DD). Default: 2026-07-12."),
    )
    args = parser.parse_args(argv)

    root = Path(os.environ.get("GW2ANALYTICS_ROOT", args.root))
    apply_docs(marker=args.marker, root=root, audit_date=args.audit_date)
    return 0


if __name__ == "__main__":
    sys.exit(main())
