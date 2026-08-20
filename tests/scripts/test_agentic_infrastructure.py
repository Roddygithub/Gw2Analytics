import re
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

PRIVATE_CORPUS_ACTIONS = {
    "lecture": (r"ouvr", r"lecture", r"accèd"),
    "énumération": (r"énum",),
    "indexation": (r"index",),
    "modification": (r"modifi",),
}
REQUIRED_HANDOFF_FIELDS = {
    "task_id",
    "intent",
    "risk",
    "objective",
    "acceptance",
    "context_refs",
    "allowed_paths",
    "forbidden",
    "validation",
    "output",
}


def section(document: str, heading: str) -> str:
    match = re.search(
        rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", document, re.MULTILINE | re.DOTALL
    )
    assert match, f"Section absente : {heading}"
    return match.group(1)


def handoff_fields(document: str) -> dict[str, str]:
    match = re.search(r"```yaml\n(.*?)```", document, re.DOTALL)
    assert match, "Enveloppe YAML de handoff absente"
    return {
        key: value.strip()
        for key, value in re.findall(r"^(\w+):\s*(.+)$", match.group(1), re.MULTILINE)
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
    profiles = {path.stem: load_toml(path) for path in AGENTS_DIR.glob("*.toml")}

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

    for name, profile in profiles.items():
        instructions = profile["developer_instructions"]
        assert "WvW/" in instructions, name
        for action, patterns in PRIVATE_CORPUS_ACTIONS.items():
            assert any(re.search(pattern, instructions, re.IGNORECASE) for pattern in patterns), (
                f"{name} doit interdire {action} du corpus privé"
            )

    assert (
        "ne transforme jamais une discussion en écriture"
        in profiles["gw2analytics_lead"]["developer_instructions"]
    )
    assert "Reste indépendant de l'auteur" in profiles["reviewer"]["developer_instructions"]
    assert "Ne corrige aucun fichier" in profiles["reviewer"]["developer_instructions"]
    assert profiles["reviewer"]["sandbox_mode"] != profiles["implementer"]["sandbox_mode"]


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
    assert (
        "Git/GitHub Governance & Delivery Architecture" in (AGENTIC_DOCS / "backlog.md").read_text()
    )
    assert (
        "Herdr, subagents Codex et Ultra ne sont jamais imbriqués"
        in (AGENTIC_DOCS / "routing-policy.md").read_text()
    )
    assert "énumérer" in (ROOT / "AGENTS.md").read_text()


def test_agentic_guardrails_cover_fallback_handoff_and_ultra() -> None:
    config = load_toml(CODEX_DIR / "config.toml")
    profiles = {path.stem: load_toml(path) for path in AGENTS_DIR.glob("*.toml")}
    architecture = (AGENTIC_DOCS / "architecture.md").read_text()
    communication = (AGENTIC_DOCS / "communication-protocol.md").read_text()
    routing = (AGENTIC_DOCS / "routing-policy.md").read_text()
    worktrees = (AGENTIC_DOCS / "worktrees-herdr.md").read_text()

    # Les protections documentaires complètent les modes sandbox ; elles ne
    # remplacent pas les essais live read-only de la Phase 6.
    assert "Aucun fallback n'est configuré" in architecture
    assert set(config) == {"model", "model_reasoning_effort", "agents"}
    assert {profile["model"] for profile in profiles.values()} <= {
        "gpt-5.6-luna",
        "gpt-5.6-terra",
        "gpt-5.6-sol",
    }

    handoff = handoff_fields(communication)
    assert set(handoff) >= REQUIRED_HANDOFF_FIELDS
    assert handoff["forbidden"].startswith("WvW")
    assert all(handoff[field] for field in REQUIRED_HANDOFF_FIELDS)
    assert "jamais un dump" in communication
    assert "done`, `idle` ou `unknown` exigent toujours diff, validations et" in communication
    assert "review avant changement d'état canonique" in communication

    ultra = section(routing, "Critères d'Ultra")
    criteria = re.findall(r"^([1-4])\.\s+(.+?)(?=\n\d\. |\n\n|\Z)", ultra, re.MULTILINE | re.DOTALL)
    assert [number for number, _ in criteria] == ["1", "2", "3", "4"]
    assert "sous-problèmes indépendants" in criteria[0][1]
    assert "gain attendu mesurable" in criteria[1][1]
    assert "subagents Codex read-only ou Herdr/worktrees" in criteria[2][1]
    assert "plafond de coût approuvé" in criteria[3][1]
    assert "Ultra reste interdit" in ultra
    assert re.search(r"fan-out remplace toutes les\s+autres couches", ultra)

    parallelism = section(routing, "Parallélisme")
    strategies = [
        strategy.strip() for strategy in re.findall(r"^\d\.\s+([^:]+):", parallelism, re.MULTILINE)
    ]
    assert strategies == [
        "tâche simple",
        "exploration ou review réellement indépendantes",
        "deux flux d'écriture réellement indépendants",
        "Ultra exceptionnel",
    ]
    assert "ne sont jamais imbriqués" in parallelism

    recovery = section(worktrees, "Conflit, abandon et récupération")
    for stage in ("**Conflit :**", "**Abandon :**", "**Récupération :**", "**Nettoyage sûr :**"):
        assert stage in recovery
    assert "référence" in recovery
    assert "Herdr" in recovery and "preuve suffisante" in recovery
