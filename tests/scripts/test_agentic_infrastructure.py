import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CODEX_DIR = ROOT / ".codex"
AGENTS_DIR = CODEX_DIR / "agents"
AGENTIC_DOCS = ROOT / "docs" / "agentic"

EXPECTED_AGENTS = {
    "gw2analytics_lead": ("gpt-5.6-terra", "medium"),
    "explorer": ("gpt-5.6-luna", "medium"),
    "implementer": ("gpt-5.6-terra", "medium"),
    "reviewer": ("gpt-5.6-terra", "high"),
    "specialist": ("gpt-5.6-sol", "high"),
}


def load_toml(path: Path) -> dict:
    return tomllib.loads(path.read_text())


def test_project_codex_defaults_are_cost_conscious_and_bounded() -> None:
    config = load_toml(CODEX_DIR / "config.toml")

    assert config["model"] == "gpt-5.6-terra"
    assert config["model_reasoning_effort"] == "medium"
    assert config["agents"] == {
        "enabled": True,
        "max_concurrent_threads_per_session": 2,
        "default_subagent_model": "gpt-5.6-luna",
        "default_subagent_reasoning_effort": "medium",
    }


def test_custom_agent_profiles_are_complete_and_constrained() -> None:
    profiles = {
        path.stem: load_toml(path)
        for path in AGENTS_DIR.glob("*.toml")
    }

    assert set(profiles) == set(EXPECTED_AGENTS)
    for name, (model, effort) in EXPECTED_AGENTS.items():
        profile = profiles[name]
        assert profile["name"] == name
        assert profile["description"]
        assert profile["developer_instructions"]
        assert profile["model"] == model
        assert profile["model_reasoning_effort"] == effort

    assert profiles["explorer"]["sandbox_mode"] == "read-only"
    assert profiles["reviewer"]["sandbox_mode"] == "read-only"
    assert profiles["specialist"]["sandbox_mode"] == "read-only"
    assert profiles["implementer"]["sandbox_mode"] == "workspace-write"


def test_agentic_docs_define_level_one_recovery_and_governance() -> None:
    required = {
        "README.md",
        "architecture.md",
        "routing-policy.md",
        "communication-protocol.md",
        "autonomy-policy.md",
        "worktrees-herdr.md",
        "backlog.md",
        "current-state.md",
    }
    assert required <= {path.name for path in AGENTIC_DOCS.iterdir()}

    assert "Level 1" in (AGENTIC_DOCS / "autonomy-policy.md").read_text()
    assert "Git/GitHub Governance & Delivery Architecture" in (
        AGENTIC_DOCS / "backlog.md"
    ).read_text()
    assert "Herdr, subagents Codex et Ultra ne sont jamais imbriqués" in (
        AGENTIC_DOCS / "routing-policy.md"
    ).read_text()
    assert "énumérer" in (ROOT / "AGENTS.md").read_text()
