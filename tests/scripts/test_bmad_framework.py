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


def test_bmad_skills_frontmatter_is_opencode_loadable():
    skills = sorted(dir_ for dir_ in SKILLS_DIR.iterdir() if dir_.is_dir())
    assert skills, "no skills under .agents/skills/"
    for skill_dir in skills:
        skill_md = skill_dir / "SKILL.md"
        assert skill_md.is_file(), f"{skill_dir.name}/SKILL.md missing"
        match = FRONTMATTER_RE.match(skill_md.read_text())
        assert match, f"{skill_dir.name}/SKILL.md has no frontmatter"
        meta = yaml.safe_load(match.group(1))
        assert isinstance(meta, dict), f"{skill_dir.name}: frontmatter not a mapping"
        assert meta.get("name") == skill_dir.name, f"{skill_dir.name}: name mismatch"
        assert meta.get("description"), f"{skill_dir.name}: description missing"
