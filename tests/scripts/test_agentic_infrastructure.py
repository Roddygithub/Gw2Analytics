"""Contracts for the intentionally small Codex/Herdr project integration."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_codex_defaults_are_economic_and_agentic() -> None:
    config = tomllib.loads((ROOT / ".codex/config.toml").read_text())
    assert config["model"] == "gpt-5.6-terra"
    assert config["model_reasoning_effort"] == "medium"
    assert config["agents"]["enabled"] is True
    assert config["agents"]["default_subagent_model"] == "gpt-5.6-luna"
    assert config["agents"]["default_subagent_reasoning_effort"] == "low"


def test_only_normal_local_data_protection_remains() -> None:
    agents = (ROOT / "AGENTS.md").read_text()
    assert "ni token, ni sudoers, ni executor dédié" in agents
    assert not (ROOT / "ops/private-corpus").exists()
    assert not (ROOT / "ops/admin").exists()
    assert not (ROOT / "tools/install-private-corpus-executor.sh").exists()
    assert not (ROOT / "tools/install-gw2analytics-admin.sh").exists()


def test_single_agentic_guide_defines_routing_handoffs_and_bmad() -> None:
    guide = (ROOT / "docs/agentic/README.md").read_text()
    for phrase in ("Herdr + Codex", "Luna", "Terra", "Sol", "reasoning", "BMAD", "handoff"):
        assert phrase in guide


def test_lead_persists_continuous_execution() -> None:
    lead = (ROOT / ".codex/agents/gw2analytics_lead.toml").read_text()
    assert "CONTINUOUS EXECUTION" in lead
    assert "sans rendre la main" in lead
