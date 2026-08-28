"""Contracts for the intentionally small Codex/Herdr project integration."""

import os
import subprocess
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
    assert "ni une\n  nouvelle intervention humaine" in agents
    assert not (ROOT / "ops/private-corpus").exists()
    assert not (ROOT / "ops/admin").exists()
    assert not (ROOT / "tools/install-private-corpus-executor.sh").exists()
    assert not (ROOT / "tools/install-gw2analytics-admin.sh").exists()


def test_single_agentic_guide_preserves_routing_and_defines_gw2a_lifecycle() -> None:
    guide = (ROOT / "docs/agentic/README.md").read_text()
    for phrase in ("Herdr + Codex", "Luna", "Terra", "Sol", "reasoning", "BMAD", "handoff"):
        assert phrase in guide
    for phrase in ("gw2a", "exit", "status", "stop", "restart", "Already inside GW2Analytics"):
        assert phrase in guide


def test_lead_persists_continuous_execution() -> None:
    lead = (ROOT / ".codex/agents/gw2analytics_lead.toml").read_text()
    assert "CONTINUOUS EXECUTION" in lead
    assert "sans rendre la main" in lead
    assert "ne constitue jamais HUMAN ACTION REQUIRED" in lead


def test_gitignore_protects_local_wvw_corpus() -> None:
    gitignore = (ROOT / ".gitignore").read_text()
    assert "/WvW/" in gitignore


GW2A = ROOT / "ops/gw2a/gw2a"
GW2A_ATTACH = ROOT / "ops/gw2a/gw2a-attach"
GW2A_PANE_SHELL = ROOT / "ops/gw2a/gw2a-pane-shell"


def _write_executable(path: Path, contents: str) -> None:
    path.write_text(contents)
    path.chmod(0o755)


def _write_attach_bash_env(tmp_path: Path, state: str | None) -> Path:
    bash_env = tmp_path / "attach-mocks.sh"
    if state is None:
        herdr_body = "return 19"
    elif state == "absent":
        herdr_body = """if [[ "$1" == session && "$2" == list ]]; then
    printf '%s\\n' '{"sessions":[{"default":true,"name":"default","running":true}]}'
elif [[ "$1" == session && "$2" == stop ]]; then
    printf 'stop %s\\n' "$3" >> "$GW2A_TEST_LOG"
else
    printf 'start %s\\n' "$2" >> "$GW2A_TEST_LOG"
fi"""
    else:
        herdr_body = f"""if [[ "$1" == session && "$2" == list ]]; then
    printf '%s\\n' '{{"sessions":[{{"default":true,"name":"default","running":true}},'\\
'{{"default":false,"name":"gw2analytics","running":{state}}}]}}'
elif [[ "$1" == session && "$2" == stop ]]; then
    printf 'stop %s\\n' "$3" >> "$GW2A_TEST_LOG"
else
    printf 'start %s\\n' "$2" >> "$GW2A_TEST_LOG"
fi"""
    bash_env.write_text(
        f"""herdr() {{
    : > "$GW2A_TEST_HERDR_MOCK_USED"
    {herdr_body}
}}

jq() {{
    local sessions
    sessions="$(cat)"
    if [[ "$sessions" == *'"name":"gw2analytics","running":true'* ]]; then
        return 0
    fi
    if [[ "$sessions" == *'"name":"gw2analytics","running":false'* ]]; then
        return 1
    fi
    return 4
}}

docker() {{
    return 0
}}

# `exec herdr` would otherwise bypass a shell function.  Any other executable
# is a harness failure rather than an escape to the host environment.
exec() {{
    if [[ "$1" != herdr ]]; then
        printf 'unexpected exec: %s\\n' "$1" >&2
        return 97
    fi
    herdr "${{@:2}}"
}}
"""
    )
    return bash_env


def _run_attach(tmp_path: Path, state: str, command: str) -> subprocess.CompletedProcess[str]:
    log = tmp_path / "commands.log"
    mock_used = tmp_path / "herdr-mock-used"
    environment = os.environ | {
        "BASH_ENV": str(_write_attach_bash_env(tmp_path, state)),
        "GW2A_TEST_LOG": str(log),
        "GW2A_TEST_HERDR_MOCK_USED": str(mock_used),
        "GW2A_TEST_REPO_ROOT": str(ROOT),
        "HERDR_SESSION": "test-harness-must-not-use-host",
        "HERDR_SOCKET_PATH": str(tmp_path / "host-herdr-must-not-be-used.sock"),
    }
    result = subprocess.run(  # noqa: S603 - controlled wrapper contract test
        ["/bin/bash", str(GW2A_ATTACH), command],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    result.commands = log.read_text() if log.exists() else ""  # type: ignore[attr-defined]
    result.herdr_mock_used = mock_used.exists()  # type: ignore[attr-defined]
    return result


def _run_attach_with_unavailable_herdr(
    tmp_path: Path, command: str
) -> subprocess.CompletedProcess[str]:
    mock_used = tmp_path / "herdr-mock-used"
    environment = os.environ | {
        "BASH_ENV": str(_write_attach_bash_env(tmp_path, None)),
        "GW2A_TEST_HERDR_MOCK_USED": str(mock_used),
        "GW2A_TEST_REPO_ROOT": str(ROOT),
        "HERDR_SESSION": "test-harness-must-not-use-host",
        "HERDR_SOCKET_PATH": str(tmp_path / "host-herdr-must-not-be-used.sock"),
    }
    result = subprocess.run(  # noqa: S603 - controlled wrapper contract test
        ["/bin/bash", str(GW2A_ATTACH), command],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    result.herdr_mock_used = mock_used.exists()  # type: ignore[attr-defined]
    return result


def test_gw2a_reentry_never_invokes_sudo(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    marker = tmp_path / "sudo-called"
    _write_executable(bin_dir / "id", "#!/bin/sh\necho gw2agent\n")
    _write_executable(bin_dir / "sudo", f"#!/bin/sh\ntouch {marker}\n")

    result = subprocess.run(  # noqa: S603 - controlled wrapper contract test
        ["/bin/bash", str(GW2A)],
        env=os.environ | {"PATH": f"{bin_dir}:{os.environ['PATH']}"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "Already inside GW2Analytics"
    assert not marker.exists()


def test_gw2a_returns_to_its_roddy_caller_after_the_gw2agent_client_exits(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(bin_dir / "id", "#!/bin/sh\necho roddy\n")
    _write_executable(bin_dir / "sudo", "#!/bin/sh\necho GW2AGENT_CLIENT\nexit 0\n")

    result = subprocess.run(  # noqa: S603 - controlled wrapper contract test
        [
            "/bin/bash",
            "-c",
            f"echo RODDY_BEFORE; {GW2A}; status=$?; echo RODDY_AFTER:$status",
        ],
        env=os.environ | {"PATH": f"{bin_dir}:{os.environ['PATH']}"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.splitlines() == ["RODDY_BEFORE", "GW2AGENT_CLIENT", "RODDY_AFTER:0"]


def test_gw2a_pane_exit_stops_its_session_and_preserves_the_exit_code(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    command_log = tmp_path / "herdr.log"
    _write_executable(bin_dir / "bash", "#!/bin/sh\necho GW2AGENT_SHELL\nexit 37\n")
    _write_executable(
        bin_dir / "herdr",
        f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {command_log}\n",
    )

    result = subprocess.run(  # noqa: S603 - controlled pane-shell contract test
        ["/bin/bash", str(GW2A_PANE_SHELL)],
        env=os.environ
        | {
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "GW2A_EXIT_MARKER": str(tmp_path / "exit-requested"),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 37
    assert result.stdout.strip() == "GW2AGENT_SHELL"
    assert command_log.read_text() == "session stop gw2analytics\n"


def test_gw2a_normalizes_only_the_marked_explicit_exit(tmp_path: Path) -> None:
    marker = tmp_path / "exit-requested"
    bash_env = tmp_path / "explicit-exit-mocks.sh"
    bash_env.write_text(
        """herdr() {
    if [[ "$1" == session && "$2" == list ]]; then
        printf '%s\\n' '{"sessions":[{"default":false,"name":"gw2analytics","running":false}]}'
    elif [[ "$1" == --session ]]; then
        : > "$GW2A_EXIT_MARKER"
        return 1
    else
        return 97
    fi
}

jq() {
    cat >/dev/null
    return 1
}
"""
    )

    result = subprocess.run(  # noqa: S603 - controlled wrapper contract test
        ["/bin/bash", str(GW2A_ATTACH), "start"],
        cwd=ROOT,
        env=os.environ
        | {
            "BASH_ENV": str(bash_env),
            "GW2A_EXIT_MARKER": str(marker),
            "GW2A_TEST_REPO_ROOT": str(ROOT),
            "HERDR_SOCKET_PATH": str(tmp_path / "host-herdr-must-not-be-used.sock"),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert not marker.exists()


def test_gw2a_parses_a_running_session_without_attaching(tmp_path: Path) -> None:
    result = _run_attach(tmp_path, "true", "start")

    assert result.returncode == 1
    assert "gw2a status' or 'gw2a restart" in result.stderr
    assert result.commands == ""
    assert result.herdr_mock_used  # type: ignore[attr-defined]


def test_gw2a_parses_a_stopped_session_from_real_herdr_json(tmp_path: Path) -> None:
    result = _run_attach(tmp_path, "false", "start")

    assert result.returncode == 0
    assert result.commands == "start gw2analytics\n"
    assert "Unable to parse" not in result.stderr
    assert result.herdr_mock_used  # type: ignore[attr-defined]


def test_gw2a_parses_an_absent_session_without_a_parsing_failure(tmp_path: Path) -> None:
    result = _run_attach(tmp_path, "absent", "start")

    assert result.returncode == 0
    assert result.commands == "start gw2analytics\n"
    assert "Unable to parse" not in result.stderr
    assert result.herdr_mock_used  # type: ignore[attr-defined]


def test_gw2a_restart_stops_then_starts_a_fresh_session(tmp_path: Path) -> None:
    result = _run_attach(tmp_path, "true", "restart")

    assert result.returncode == 0
    assert result.commands == "stop gw2analytics\nstart gw2analytics\n"
    assert result.herdr_mock_used  # type: ignore[attr-defined]


def test_gw2a_status_reports_herdr_identity_groups_and_docker(tmp_path: Path) -> None:
    result = _run_attach(tmp_path, "false", "status")

    assert result.returncode == 0
    assert "Herdr:" in result.stdout
    assert "Identity and groups:" in result.stdout
    assert "Docker: available" in result.stdout
    assert result.herdr_mock_used  # type: ignore[attr-defined]


def test_gw2a_stop_uses_herdr_and_handles_no_active_session(tmp_path: Path) -> None:
    inactive = _run_attach(tmp_path, "false", "stop")
    active = _run_attach(tmp_path, "true", "stop")

    assert inactive.returncode == 0
    assert inactive.stdout.strip() == "No active GW2Analytics session."
    assert inactive.commands == ""
    assert inactive.herdr_mock_used  # type: ignore[attr-defined]
    assert active.returncode == 0
    assert active.commands == "stop gw2analytics\n"
    assert active.herdr_mock_used  # type: ignore[attr-defined]


def test_gw2a_never_treats_an_unavailable_herdr_state_as_stopped(tmp_path: Path) -> None:
    for command in ("start", "stop", "restart"):
        result = _run_attach_with_unavailable_herdr(tmp_path, command)

        assert result.returncode == 2
        assert "Unable to inspect the GW2Analytics Herdr session." in result.stderr
        assert result.herdr_mock_used  # type: ignore[attr-defined]


def test_gw2a_sources_define_only_the_explicit_herdr_lifecycle() -> None:
    wrapper = GW2A.read_text()
    attach = GW2A_ATTACH.read_text()
    pane_shell = GW2A_PANE_SHELL.read_text()
    installer = (ROOT / "tools/install-gw2a-lifecycle.sh").read_text()

    assert "sudo -n -u gw2agent -- /usr/local/libexec/gw2a-attach" in wrapper
    assert "exec sudo -n -u gw2agent" not in wrapper
    assert "herdr session list --json" in attach
    assert 'herdr session stop "$session_name"' in attach
    assert 'herdr --session "$session_name"' in attach
    assert 'export SHELL="${GW2A_PANE_SHELL:-/usr/local/libexec/gw2a-pane-shell}"' in attach
    assert 'export GW2A_SESSION_NAME="$session_name"' in attach
    assert 'export GW2A_EXIT_MARKER="$exit_marker"' in attach
    assert 'readonly repo_root="${GW2A_TEST_REPO_ROOT:-/srv/gw2analytics/repo}"' in attach
    assert "bash --login" in pane_shell
    assert ': > "$exit_marker"' in pane_shell
    assert 'herdr session stop "$session_name"' in pane_shell
    # Every production invocation remains a shell-resolved `herdr` command:
    # the BASH_ENV function therefore intercepts it in the hermetic tests.
    assert "/herdr" not in attach
    assert "command herdr" not in attach
    for variable in (
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_STATE_HOME",
        "XDG_CACHE_HOME",
        "XDG_RUNTIME_DIR",
    ):
        assert f"export {variable}=" in attach
    assert "session attach" not in attach
    assert "kill" not in attach
    assert "pstree" not in attach
    assert "/usr/local/libexec/gw2a-pane-shell" in installer
    assert "/etc/systemd/user/gw2agent-herdr.service" in installer
