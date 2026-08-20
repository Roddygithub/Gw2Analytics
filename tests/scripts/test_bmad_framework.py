# ruff: noqa: S603
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
BMAD_SCRIPTS = ROOT / "_bmad" / "scripts"
SKILLS_DIR = ROOT / ".agents" / "skills"
MANIFEST_PATH = ROOT / "_bmad" / "_config" / "manifest.yaml"
EXPECTED_CODEX_SKILL_COUNT = 49
# This inventory is pinned to the official BMAD 6.11.0 Codex installation used
# by this repository. Keep it explicit so an installer upgrade cannot silently
# remove a canonical skill or reintroduce a legacy IDE integration.
EXPECTED_CODEX_SKILLS = frozenset(
    {
        "bmad-advanced-elicitation",
        "bmad-agent-analyst",
        "bmad-agent-architect",
        "bmad-agent-dev",
        "bmad-agent-pm",
        "bmad-agent-ux-designer",
        "bmad-architecture",
        "bmad-brainstorming",
        "bmad-build",
        "bmad-build-auto",
        "bmad-checkpoint-preview",
        "bmad-code-review",
        "bmad-correct-course",
        "bmad-create-architecture",
        "bmad-create-epics-and-stories",
        "bmad-create-prd",
        "bmad-create-story",
        "bmad-customize",
        "bmad-deep-recon",
        "bmad-dev-auto",
        "bmad-dev-story",
        "bmad-document-project",
        "bmad-domain-research",
        "bmad-edit-prd",
        "bmad-editorial-review",
        "bmad-editorial-review-prose",
        "bmad-editorial-review-structure",
        "bmad-forge-idea",
        "bmad-generate-project-context",
        "bmad-help",
        "bmad-market-research",
        "bmad-party-mode",
        "bmad-prd",
        "bmad-prfaq",
        "bmad-product-brief",
        "bmad-project-context",
        "bmad-qa-generate-e2e-tests",
        "bmad-quick-dev",
        "bmad-retrospective",
        "bmad-review",
        "bmad-review-adversarial-general",
        "bmad-review-edge-case-hunter",
        "bmad-review-verification-gap",
        "bmad-spec",
        "bmad-sprint-planning",
        "bmad-sprint-status",
        "bmad-technical-research",
        "bmad-ux",
        "bmad-validate-prd",
    }
)

FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?", re.DOTALL)


@pytest.mark.parametrize(
    "script",
    ["resolve_config.py", "resolve_customization.py", "render_skill.py", "memlog.py"],
)
def test_bmad_framework_script_is_invokable(script):
    proc = subprocess.run(
        [
            sys.executable,
            str(BMAD_SCRIPTS / script),
            "--help",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_bmad_framework_resolve_config_merges_project():
    proc = subprocess.run(
        [sys.executable, str(BMAD_SCRIPTS / "resolve_config.py"), "--project-root", str(ROOT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    config = json.loads(proc.stdout)
    assert config["core"]["project_name"] == "Gw2Analytics"
    assert "bmad-agent-analyst" in config["agents"]


def test_bmad_skills_frontmatter_is_codex_discoverable():
    skills = {path.name: path for path in SKILLS_DIR.iterdir() if path.is_dir()}
    assert len(EXPECTED_CODEX_SKILLS) == EXPECTED_CODEX_SKILL_COUNT
    assert set(skills) == EXPECTED_CODEX_SKILLS
    for skill_name, skill_dir in sorted(skills.items()):
        skill_md = skill_dir / "SKILL.md"
        assert skill_md.is_file(), f"{skill_dir.name}/SKILL.md missing"
        match = FRONTMATTER_RE.match(skill_md.read_text())
        assert match, f"{skill_dir.name}/SKILL.md has no frontmatter"
        meta = yaml.safe_load(match.group(1))
        assert isinstance(meta, dict), f"{skill_dir.name}: frontmatter not a mapping"
        assert meta.get("name") == skill_name, f"{skill_dir.name}: name mismatch"
        assert meta.get("description"), f"{skill_dir.name}: description missing"


def test_bmad_manifest_is_codex_only_without_legacy_opencode_integration():
    manifest = yaml.safe_load(MANIFEST_PATH.read_text())

    assert manifest["installation"]["version"] == "6.11.0"
    assert manifest["ides"] == ["codex"]
    assert not (ROOT / ".opencode" / "commands").exists()
    assert not (ROOT / "opencode.json").exists()
    assert not (ROOT / "opencode.jsonc").exists()
