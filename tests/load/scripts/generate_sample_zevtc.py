"""Generate a minimal valid .zevtc fixture for k6 upload tests.

Output: tests/load/fixtures/sample.zevtc (~50 bytes total).

The .zevtc wire format is a zip archive containing exactly one EVTC
blob. arcdps-tooling convention (per
``libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py::HEADER_SIZE``):

  bytes  0-3:   magic b"EVTC" (4 chars)
  bytes  4-11:  build version, 8 ASCII chars (e.g. b"20251001")
  byte  12:     rev (uint8, 0 for legacy)
  bytes 13-14:  encounter_id (uint16, 0 for empty)
  byte  15:     unused (uint8)
  bytes 16-19:  agent_count (uint32, 0 here)
  bytes 20-23:  skill_count (uint32, 0 here)
  byte  24:     language (uint8, 0 = en)

Total header: 25 bytes (HEADER_SIZE). No agents, no skills, no event
stream. arcdps writes a zip wrapper around a single EVTC entry named
``fight.evtc``; the upload route does
``zipfile.is_zipfile(data) -> ZipFile(data).read(first_entry)`` so we
wrap our 25-byte EVTC in a single-entry zip with zipfile.ZIP_STORED.

The fixture is valid for happy-path parser smoke tests (parse +
empty Fight record), but the per-event emulator will short-circuit on
``agent_count == 0`` events -- which is exactly what we want for a
synthetic load-test fixture (we don't want the parser competing for
CPU with the load driver).
"""

from __future__ import annotations

import struct
import zipfile
from pathlib import Path

HEADER_STRUCT: struct.Struct = struct.Struct("<4s8sBHBI IB")
DEFAULT_BUILD: bytes = b"20251001"


def _build_minimal_evtc_header() -> bytes:
    """Build the canonical 25-byte arcdps EVTC header with zero agents/skills."""
    return HEADER_STRUCT.pack(
        b"EVTC",  # magic
        DEFAULT_BUILD,  # build version (yymmdd style)
        0,  # rev
        0,  # encounter_id
        0,  # unused
        0,  # agent_count
        0,  # skill_count
        0,  # language
    )


def main() -> None:
    """Generate tests/load/fixtures/sample.zevtc with the canonical layout."""
    path = Path("tests/load/fixtures/sample.zevtc")
    path.parent.mkdir(parents=True, exist_ok=True)
    evtc_bytes = _build_minimal_evtc_header()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("fight.evtc", evtc_bytes)
    print(f"Generated {path} ({path.stat().st_size} bytes, inner EVTC={len(evtc_bytes)} bytes)")


if __name__ == "__main__":
    main()
