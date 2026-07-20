"""Lightweight tests for scripts/dev-web-bg.sh and scripts/dev-api-bg.sh.

These tests do not start any real servers; they only verify shell syntax,
help output, and safe read-only subcommands (status/stop).
"""
import os
import subprocess

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
WEB_SCRIPT = os.path.join(REPO_ROOT, "scripts", "dev-web-bg.sh")
API_SCRIPT = os.path.join(REPO_ROOT, "scripts", "dev-api-bg.sh")


def _run(args, check=True):
    res = subprocess.run(
        args,
        capture_output=True,
        text=True,
        check=False,
    )
    if check:
        assert res.returncode == 0, f"{args} failed: {res.stderr}"
    return res


def test_web_script_syntax():
    _run(["bash", "-n", WEB_SCRIPT])


def test_api_script_syntax():
    _run(["bash", "-n", API_SCRIPT])


def test_web_script_help():
    res = _run([WEB_SCRIPT, "--help"])
    assert "Usage:" in res.stdout
    assert "tmux session" in res.stdout


def test_api_script_help():
    res = _run([API_SCRIPT, "--help"])
    assert "Usage:" in res.stdout
    assert "tmux session" in res.stdout


def test_web_script_status_no_server():
    res = _run([WEB_SCRIPT, "--status"], check=False)
    assert res.returncode == 0
    # No dev server should be running in the test environment.
    assert "(no tmux session" in res.stdout


def test_api_script_status_no_server():
    res = _run([API_SCRIPT, "--status"], check=False)
    assert res.returncode == 0
    assert "(no tmux session" in res.stdout

