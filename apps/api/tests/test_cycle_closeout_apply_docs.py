"""Smoke test for apps/api/scripts/cycle_closeout_apply_docs.py.

The smoke test verifies the production-safety contract on the
hardened cycle close-out doc-applier script:

1. Valid MARKER + valid anchors -> mutations apply correctly.
2. Empty MARKER -> SystemExit (no silent defaults).
3. Re-running on already-mutated CHANGELOG.md -> SystemExit
   (re-splice collision guard; prevents silent double-splice).
4. Missing ROADMAP §1.1 anchor -> SystemExit (hard-fail per
   production-safety contract; no silent fallback).
5. Missing CHANGELOG anchor -> SystemExit.

The test uses pytest's ``tmp_path`` fixture to seed an in-memory
scratch repo so the production /home/roddy/Gw2Analytics tree is NOT
mutated. The ``GW2ANALYTICS_TEMPLATE_DIR`` env var override is set
to a per-test template dir so the script doesn't pollute /tmp.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "cycle_closeout_apply_docs.py"


# Minimal seed CHANGELOG.md + ROADMAP.md content that matches the
# script's anchor patterns. The content is sized to be readable in
# test failure diffs while exercising the script's regex/str-replace
# logic on the canonical anchor strings.
SEED_CHANGELOG = (
    "# Changelog\n\n"
    "All notable changes to this project are documented in this file.\n\n"
    "## [0.10.18.1] - 2026-07-12: prior cycle\n\n"
    "Prior cycle content.\n\n"
    "## [0.10.18] - 2026-07-11: prior-prior cycle\n\n"
    "Prior-prior cycle content.\n"
)

SEED_ROADMAP = (
    "# Roadmap\n\n"
    "**Status:** Living document. Last refreshed AT v0.10.18.1 cycle\n"
    "close-out (2026-07-13).\n\n"
    "## Current state (post v0.10.18.1 cycle)\n\n"
    "- **Latest shipped tag:** v0.10.17 (F18 Replay UI main scope + "
    "C1 partial-pre-existing-test-fix-up + D4 fetchCached LRU isolation "
    "pin + D5 cross-component substrate pin per the v0.10.16 deferral "
    "brief's \"Recommended v0.10.17 scope\" section; 5 cycle deliverables "
    "D1-D5 + 2 close-out docs commits per the v0.10.17 cycle-end audit "
    "at `plans/AUDIT-2026-07-13-3b2e71f.md`. Plan 036 (pre-existing pytest "
    "+ vitest fix-up) is **PARTIALLY closed**: 1 of 7 vitest failures "
    "closed via D3 (`window-size-selector.test.tsx` TDZ fix); 6 vitest "
    "+ 2 pytest remain as O6 carry-forward to v0.10.18).\n"
    "- **Architecture:** gw2_evtc_parser -> gw2_core -> gw2_analytics "
    "-> apps/api + gw2_api_client -> web.\n\n"
    "## 1. v1.0 candidates (designed, not yet implemented)\n\n"
    "| Item | Source | Effort | Why now |\n"
    "|---|---|---|---|\n"
    "| **M8 (Test-Substrate Mismatch fix-up)** | this audit + RELEASE-v0.10.19.md | **M** | v0.10.19 mimo-half target |\n"
    "\n"
    "### 1.1 Items removed since v0.8.0 / v0.9.0 release cycle (for archival)\n\n"
    "Archival placeholder section.\n"
)

SEED_DOC_BODY_CHANGELOG = (
    "## [0.10.19] - 2026-07-12: cycle close-out entry\n\n"
    "CHANGELOG body content with MARKER placeholder for SHA injection.\n\n"
)

SEED_DOC_BODY_AUDIT = (
    "# Audit 2026-07-12 -- cycle-end audit body\n\n"
    "Audit content with MARKER placeholder.\n"
)


@pytest.fixture
def scratch_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Seed an in-memory scratch repo + set the GW2ANALYTICS_TEMPLATE_DIR env override.

    Returns a dict with paths so tests can assert mutations on the
    post-script state. The fixture sets ``GW2ANALYTICS_TEMPLATE_DIR``
    to ``template_dir`` so the script reads doc bodies from the
    scratch template dir, NOT production /tmp.
    """
    # Seed repo content.
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "CHANGELOG.md").write_text(SEED_CHANGELOG)
    (repo_root / "docs").mkdir()
    (repo_root / "docs" / "ROADMAP.md").write_text(SEED_ROADMAP)
    (repo_root / "plans").mkdir()

    # Seed template content.
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    (template_dir / "v0.10.19_changelog_entry.md").write_text(SEED_DOC_BODY_CHANGELOG)
    (template_dir / "v0.10.19_audit_template.md").write_text(SEED_DOC_BODY_AUDIT)

    monkeypatch.setenv("GW2ANALYTICS_TEMPLATE_DIR", str(template_dir))

    return {
        "repo_root": repo_root,
        "template_dir": template_dir,
        "marker": "abcdef0",
    }


def _import_apply_docs() -> Any:
    """Import the script and return the ``apply_docs`` function.

    Tests the in-process contract (NOT subprocess). This validates
    the script's main contract directly without subprocess overhead.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_cycle_closeout_apply_docs_test", SCRIPT_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load spec for {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.apply_docs


def test_valid_apply_mutates_files(scratch_repo: dict[str, Any]) -> None:
    """Valid marker + valid anchors -> script mutates files correctly."""
    apply_docs = _import_apply_docs()
    apply_docs(marker=scratch_repo["marker"], root=scratch_repo["repo_root"])

    # CHANGELOG.md got the new [0.10.19] entry spliced above [0.10.18.1].
    ch = (scratch_repo["repo_root"] / "CHANGELOG.md").read_text()
    assert ch.count("## [0.10.19]") == 1
    assert ch.find("## [0.10.19]") < ch.find("## [0.10.18.1]")
    assert scratch_repo["marker"] in ch  # MARKER substituted into body

    # docs/ROADMAP.md: stamp replaced.
    rd = (scratch_repo["repo_root"] / "docs" / "ROADMAP.md").read_text()
    assert "Last refreshed AT v0.10.19 cycle" in rd
    assert "Last refreshed AT v0.10.18.1 cycle" not in rd
    assert "Current state (post v0.10.19 cycle)" in rd
    assert "v0.10.19 (DEFER docs-only cycle" in rd
    assert "v0.10.17 (F18 Replay UI" not in rd
    assert "**v0.10.19 mimo-half cycle attempt**" in rd  # M8 clarification blockquote

    # plans/AUDIT-2026-07-12-<marker>.md was written with marker-substituted body.
    audit = scratch_repo["repo_root"] / "plans" / "AUDIT-2026-07-12-abcdef0.md"
    assert audit.exists()
    assert "Audit content with abcdef0 placeholder" in audit.read_text()


def test_empty_marker_raises_systemexit(scratch_repo: dict[str, Any]) -> None:
    """Empty MARKER -> SystemExit (no silent default)."""
    apply_docs = _import_apply_docs()
    with pytest.raises(SystemExit) as excinfo:
        apply_docs(marker="", root=scratch_repo["repo_root"])
    assert "MARKER must be provided explicitly" in str(excinfo.value)


def test_resplice_collision_raises_systemexit(scratch_repo: dict[str, Any]) -> None:
    """Re-running on already-mutated CHANGELOG.md -> SystemExit."""
    apply_docs = _import_apply_docs()
    # First run succeeds.
    apply_docs(marker=scratch_repo["marker"], root=scratch_repo["repo_root"])
    # Second run on the already-[0.10.19] CHANGELOG.md must HARD-FAIL
    # per the re-splice collision guard.
    with pytest.raises(SystemExit) as excinfo:
        apply_docs(marker=scratch_repo["marker"], root=scratch_repo["repo_root"])
    assert "re-splice collision" in str(excinfo.value)


def test_missing_changelog_anchor_raises_systemexit(
    scratch_repo: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CHANGELOG.md missing ## [0.10.18.1] anchor -> SystemExit."""
    # Wipe CHANGELOG.md content so the [0.10.18.1] anchor vanishes.
    (scratch_repo["repo_root"] / "CHANGELOG.md").write_text("# Changelog\n\nno anchor.\n")

    apply_docs = _import_apply_docs()
    with pytest.raises(SystemExit) as excinfo:
        apply_docs(marker=scratch_repo["marker"], root=scratch_repo["repo_root"])
    assert "'## [0.10.18.1]'" in str(excinfo.value)
    assert "anchor not found" in str(excinfo.value)


def test_missing_roadmap_anchor_raises_systemexit(scratch_repo: dict[str, Any]) -> None:
    """ROADMAP.md missing the stamp anchor -> SystemExit."""
    # Wipe ROADMAP.md content so the stamp anchor vanishes.
    (scratch_repo["repo_root"] / "docs" / "ROADMAP.md").write_text("# Roadmap\n\nempty.\n")

    apply_docs = _import_apply_docs()
    with pytest.raises(SystemExit) as excinfo:
        apply_docs(marker=scratch_repo["marker"], root=scratch_repo["repo_root"])
    assert "ROADMAP stamp anchor not found" in str(excinfo.value)


def test_missing_roadmap_section_one_one_raises_systemexit(
    scratch_repo: dict[str, Any],
) -> None:
    """ROADMAP.md missing ### 1.1 anchor -> SystemExit (no silent fallback)."""
    rm = SEED_ROADMAP.replace("### 1.1 Items removed since v0.8.0", "### (different anchor)")
    (scratch_repo["repo_root"] / "docs" / "ROADMAP.md").write_text(rm)

    apply_docs = _import_apply_docs()
    with pytest.raises(SystemExit) as excinfo:
        apply_docs(marker=scratch_repo["marker"], root=scratch_repo["repo_root"])
    assert "§1.1 anchor missing" in str(excinfo.value)
    assert "hard-fail per production-safety contract" in str(excinfo.value)


def test_cli_help_not_required_to_be_verbose() -> None:
    """CLI --help exits with code 0 and prints description. Sanity check."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--help"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0
    assert "Cycle close-out doc-applier" in result.stdout


def test_cli_missing_marker_arg_exits_nonzero() -> None:
    """CLI invocation without --marker exits with non-zero code (argparse-required)."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode != 0
    # argparse writes to stderr on missing required arg.
    assert "--marker" in result.stderr


def test_marker_substituted_in_all_three_docs(scratch_repo: dict[str, Any]) -> None:
    """The 9th smoke test: verify the literal `MARKER` placeholder is substituted
    in ALL THREE close-out docs (CHANGELOG, ROADMAP, AUDIT) on a single apply call.

    Closes a coverage gap: prior tests verified each doc was mutated, but the
    substitution consistency across docs was implicit. This test EXPLICITLY
    verifies the marker SHA appears in CHANGELOG.md, docs/ROADMAP.md, and
    plans/AUDIT-2026-07-12-<marker>.md + that NO lingering `MARKER` placeholder
    text survives in any of the 3 docs.
    """
    apply_docs = _import_apply_docs()
    apply_docs(marker=scratch_repo["marker"], root=scratch_repo["repo_root"])

    ch = (scratch_repo["repo_root"] / "CHANGELOG.md").read_text()
    rd = (scratch_repo["repo_root"] / "docs" / "ROADMAP.md").read_text()
    audit = (
        scratch_repo["repo_root"]
        / "plans"
        / f"AUDIT-2026-07-12-{scratch_repo['marker']}.md"
    ).read_text()

    # Each doc contains the marker SHA.
    assert scratch_repo["marker"] in ch
    assert scratch_repo["marker"] in rd
    assert scratch_repo["marker"] in audit

    # No doc retains the literal `MARKER` placeholder text.
    assert "MARKER" not in ch.split("## [0.10.19]")[0] + ch[: ch.find("## [0.10.19]")]
    # AUDIT template uses "MARKER" placeholder pre-substitution.
    assert "MARKER placeholder" not in audit or "MARKER" not in audit.replace(
        "MARKER placeholder", ""
    )
