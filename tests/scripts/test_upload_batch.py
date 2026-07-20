"""Tests for scripts/upload-batch.sh.

Covers dry-run, normal upload, and progress-resume behavior against a
lightweight mock API server.
"""
import contextlib
import os
import socket
import subprocess
import time

import pytest

SCRIPT_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "upload-batch.sh")
)
MOCK_SERVER_PATH = os.path.join(os.path.dirname(__file__), "mock_upload_server.py")


def _wait_for_port(port: int, timeout: float = 5.0) -> None:
    """Poll until the mock server accepts connections."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError(f"Mock server did not start on port {port}")


@contextlib.contextmanager
def _start_mock_server(mode: str = ""):
    """Start the mock upload API on an ephemeral port.

    ``mode`` can be empty (always succeed) or "retry" (first 2 requests
    return rate_limited).
    """
    args = ["python3", MOCK_SERVER_PATH, "0"]
    if mode == "retry":
        args.append("retry")
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        port_line = proc.stdout.readline().strip()
        port = int(port_line)
        _wait_for_port(port)
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        proc.wait(timeout=5)


@pytest.fixture
def mock_server():
    """Start a local mock upload API on an ephemeral port."""
    with _start_mock_server() as url:
        yield url


@pytest.fixture
def mock_server_retry():
    """Start a mock API that returns rate_limited for the first 2 requests."""
    with _start_mock_server("retry") as url:
        yield url


@pytest.fixture
def zevtc_dir(tmp_path):
    """Create a tiny directory tree of dummy .zevtc files."""
    d1 = tmp_path / "session1"
    d1.mkdir()
    (d1 / "fight1.zevtc").touch()
    (d1 / "fight2.zevtc").touch()
    d2 = tmp_path / "session2"
    d2.mkdir()
    (d2 / "fight3.zevtc").touch()
    return tmp_path


def test_dry_run(zevtc_dir):
    """--dry-run lists files without hitting the network."""
    res = subprocess.run(
        [SCRIPT_PATH, "--dry-run", str(zevtc_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stderr
    assert "Dry-run complete" in res.stdout
    assert "Would upload:        3" in res.stdout


def test_dry_run_respects_progress_file(mock_server, zevtc_dir, tmp_path):
    """--dry-run skips already-completed files read from a progress file."""
    progress_file = tmp_path / "progress.txt"
    env = os.environ.copy()
    env["API_BASE"] = mock_server
    env["UPLOAD_PROGRESS_FILE"] = str(progress_file)

    # First run uploads all files and writes the progress file.
    subprocess.run(
        [SCRIPT_PATH, str(zevtc_dir)],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    # Add a new file that has not been uploaded yet.
    new_file = zevtc_dir / "session2" / "fight4.zevtc"
    new_file.touch()

    # Dry-run should report only the new file as pending.
    res = subprocess.run(
        [SCRIPT_PATH, "--dry-run", str(zevtc_dir)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stderr
    assert "Total files found: 4" in res.stdout
    assert "Would upload:        1" in res.stdout
    assert "Already done:        3" in res.stdout


def test_successful_upload(mock_server, zevtc_dir):
    """Normal run uploads all files against the mock API."""
    env = os.environ.copy()
    env["API_BASE"] = mock_server
    res = subprocess.run(
        [SCRIPT_PATH, str(zevtc_dir)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stderr
    assert "Uploaded:            3" in res.stdout
    assert "Failed:              0" in res.stdout


def test_progress_resume(mock_server, zevtc_dir, tmp_path):
    """A progress file causes already-uploaded files to be skipped."""
    env = os.environ.copy()
    env["API_BASE"] = mock_server
    env["UPLOAD_PROGRESS_FILE"] = str(tmp_path / "progress.txt")

    # First run: upload everything.
    subprocess.run(
        [SCRIPT_PATH, str(zevtc_dir)],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    # Second run: should skip all previously uploaded files.
    res = subprocess.run(
        [SCRIPT_PATH, str(zevtc_dir)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stderr
    assert "Already done:" in res.stdout and "3" in res.stdout
    assert "Files to upload:  0" in res.stdout


def test_python3_fallback(mock_server, zevtc_dir):
    """The script falls back to python3 when UPLOAD_DISABLE_JQ is set."""
    env = os.environ.copy()
    env["API_BASE"] = mock_server
    env["UPLOAD_DISABLE_JQ"] = "1"
    res = subprocess.run(
        [SCRIPT_PATH, str(zevtc_dir)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stderr
    assert "Uploaded:            3" in res.stdout
    assert "Failed:              0" in res.stdout


def test_retry_on_transient_error(mock_server_retry, zevtc_dir, tmp_path):
    """The script retries on rate_limited responses and eventually succeeds."""
    # The script sleeps for an exponentially increasing duration between
    # retries (1s, 2s, 4s, ...).  To keep this test fast and deterministic,
    # we prepend a no-op `sleep` executable to PATH so the backoff is
    # instantaneous while the retry logic still executes.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    sleep_bin = bin_dir / "sleep"
    sleep_bin.write_text("#!/bin/sh\nexit 0\n")
    sleep_bin.chmod(0o755)

    env = os.environ.copy()
    env["API_BASE"] = mock_server_retry
    env["UPLOAD_CONCURRENCY"] = "1"
    env["UPLOAD_MAX_RETRIES"] = "3"
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"

    res = subprocess.run(
        [SCRIPT_PATH, str(zevtc_dir)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stderr
    assert "RETRY" in res.stderr
    assert "Uploaded:            3" in res.stdout
    assert "Failed:              0" in res.stdout
