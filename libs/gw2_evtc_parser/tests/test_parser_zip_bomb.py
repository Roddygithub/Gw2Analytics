"""v0.9.6 plan 020: zip-bomb protection in parser._first_entry."""
from __future__ import annotations

import io
import zipfile
from unittest.mock import patch

import pytest

from gw2_evtc_parser.exceptions import EvtcParseError
from gw2_evtc_parser.parser import read_zevtc_bytes


def test_zip_with_oversized_entry_raises_before_extraction() -> None:
    """A .zevtc whose entry exceeds the safety bound is rejected."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("huge.evtc", data=b"\x00" * 16)

    # Patch the safety bound to 1 byte so the small test entry
    # exceeds it. This exercises the pre-extraction check without
    # needing a real multi-gigabyte zip payload.
    with (
        patch(
            "gw2_evtc_parser.parser._MAX_ZIP_ENTRY_UNCOMPRESSED_SIZE",
            1,
        ),
        pytest.raises(EvtcParseError) as exc,
    ):
        read_zevtc_bytes(buf.getvalue())

    assert "zip-bomb protection" in str(exc.value)
    assert "exceeds safety bound" in str(exc.value)
