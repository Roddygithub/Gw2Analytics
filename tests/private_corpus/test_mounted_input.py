"""Checks executed by closed private profiles inside the service namespace."""

import os
from pathlib import Path

import pytest


def test_mounted_input_is_readable_and_read_only() -> None:
    value = os.environ.get("GW2_PRIVATE_INPUT")
    if value is None:
        pytest.skip("only executed by the private service profile")
    input_dir = Path(value)
    assert input_dir.is_dir()
    assert any(input_dir.iterdir())
    with pytest.raises(OSError):
        (input_dir / "must-not-write").write_text("blocked", encoding="utf-8")
