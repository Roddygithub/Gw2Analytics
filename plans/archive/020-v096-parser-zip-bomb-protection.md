# Plan 020 — v0.9.6: zip-bomb protection in `parser._first_entry`

**Author:** senior-advisor audit (improve skill, standard effort) — deep audit of libs/* + web/* (the excluded surfaces from prior passes).
**Drift base:** `44ea862`.
**Repo root:** `/home/roddy/Gw2Analytics`.
**Audience:** executor model with NO prior context.

---

## Why this matters

`libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py::_first_entry` (line 382) calls `zf.read(names[0])` with **no uncompressed-size pre-check**. A maliciously crafted `.zevtc` archive (a 42-byte zip header claiming an uncompressed size of 4 GB of zeros) decompresses inside `zf.read()` and pins the worker process memory → DoS via OOM. The fix: a 2-line pre-check using `ZipFile.getinfo(name).file_size` + a sane bound (500 MB).

This is the canonical "zip-bomb" defense (the same pattern `python -m zipfile -l` uses; cf. CVE-2019-9631 for the historical context).

---

## Files IN scope

- `libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py` (`_first_entry` + NEW `_MAX_ZIP_ENTRY_UNCOMPRESSED_SIZE`).
- `libs/gw2_evtc_parser/tests/test_parser_zip_bomb.py` — **NEW** (1 test).

## Files NOT in scope

- The 96-byte agent-record reader (`_iter_agents`); per-record bounds already enforced via `MAX_AGENTS`.
- The cbtevent reader (`parse_events`); the records are fixed-size 64 bytes + truncation is already lenient.
- `read_zevtc_archive` (the on-disk variant) — uses the same `_first_entry`, so the bound applies.

---

## Current code (read from `44ea862`)

### `parser.py::_first_entry` (around line 380-385)

```python
def _first_entry(zf: zipfile.ZipFile) -> bytes:
    """Return the bytes of the first entry in an open zip."""
    names = zf.namelist()
    if not names:
        raise EvtcParseError("zevtc has no entries (empty zip)")
    return zf.read(names[0])
```

---

## Step-by-step

### Step 1 — Define the bound + add the pre-check

In `parser.py`, near the existing `MAX_AGENTS` / `MAX_SKILLS` constants (around line 105):

```python
#: Maximum uncompressed size for a single .zevtc zip entry.
#: Defends against zip-bomb DoS: a 42-byte zip header can claim a
#: 4 GB uncompressed payload (zip-bomb convention). We refuse to
#: extract any entry whose declared uncompressed size exceeds
#: this bound. 500 MB is well above the realistic upper bound for
#: a single GW2 combat log (a 5-minute WvW raid is typically
#: 1-10 MB); 500 MB accommodates the longest possible fights
#: with headroom.
_MAX_ZIP_ENTRY_UNCOMPRESSED_SIZE: Final[int] = 500 * 1024 * 1024  # 500 MB
```

### Step 2 — Update `_first_entry`

REPLACE the existing `_first_entry` body with:

```python
def _first_entry(zf: zipfile.ZipFile) -> bytes:
    """Return the bytes of the first entry in an open zip.

    v0.9.6 plan 020: refuse to extract any entry whose declared
    uncompressed size exceeds ``_MAX_ZIP_ENTRY_UNCOMPRESSED_SIZE``
    (zip-bomb DoS defence). ``ZipFile.getinfo(...).file_size`` is
    the declared uncompressed size on the central directory --
    reading it does NOT materialise the payload, so the check is
    O(1).
    """
    names = zf.namelist()
    if not names:
        raise EvtcParseError("zevtc has no entries (empty zip)")
    name = names[0]
    info = zf.getinfo(name)
    if info.file_size > _MAX_ZIP_ENTRY_UNCOMPRESSED_SIZE:
        raise EvtcParseError(
            f"zip entry {name!r} declared uncompressed size "
            f"({info.file_size} bytes) exceeds safety bound "
            f"({_MAX_ZIP_ENTRY_UNCOMPRESSED_SIZE} bytes); "
            f"refusing to extract (zip-bomb protection)"
        )
    return zf.read(name)
```

### Step 3 — Tests

`libs/gw2_evtc_parser/tests/test_parser_zip_bomb.py` (NEW):

```python
"""v0.9.6 plan 020: zip-bomb protection in parser._first_entry."""
from __future__ import annotations

import io
import zipfile

import pytest

from gw2_evtc_parser.exceptions import EvtcParseError
from gw2_evtc_parser.parser import read_zevtc_bytes


def test_zip_with_oversized_entry_raises_before_extraction():
    """A .zevtc claiming a 4 GB uncompressed entry is rejected."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        # A 42-byte zip header claiming 4 GB uncompressed. We
        # do NOT actually write 4 GB of data -- the pre-check
        # rejects on the central directory's declared size.
        zf.writestr(
            zipfile.ZipInfo("huge.evtc"),
            data=b"\x00" * 0,  # 0 bytes actual; declared size is what matters
        )
    # The zip now has a central directory entry claiming a
    # specific file_size. To make the test deterministic, we
    # patch the file_size on the ZipInfo.
    data = buf.getvalue()
    # Re-open and override the file_size on the entry to 4 GB.
    buf2 = io.BytesIO()
    with zipfile.ZipFile(buf2, "w") as zf:
        info = zipfile.ZipInfo("huge.evtc")
        info.file_size = 4 * 1024 * 1024 * 1024  # 4 GB
        zf.writestr(info, data=b"\x00" * 16)
    with pytest.raises(EvtcParseError) as exc:
        read_zevtc_bytes(buf2.getvalue())
    assert "zip-bomb protection" in str(exc.value)
    assert "exceeds safety bound" in str(exc.value)
```

---

## Verification commands

```bash
uv run ruff check libs
uv run mypy --no-incremental libs
uv run pytest libs/gw2_evtc_parser/tests/test_parser_zip_bomb.py -v
uv run pytest libs/gw2_evtc_parser/tests/ -v
# Expected: existing 545+ tests pass + 1 new test passes.
```

A worktree `git diff` against `44ea862` must show ONLY:
- `libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py` (add constant + update `_first_entry`).
- `libs/gw2_evtc_parser/tests/test_parser_zip_bomb.py` (NEW, 1 test).

## Maintenance note

- The 500 MB bound is a starting heuristic. Real `.zevtc` files for typical WvW raids are 1-10 MB; 500 MB accommodates the longest possible fights (e.g. an 8-hour continuous raid) with 50-500x headroom. Lift via a module-level constant if needed; do not lift to >2 GB without a perf analysis.
- `ZipFile.getinfo(name).file_size` returns the declared uncompressed size from the central directory — it does NOT read the payload, so the check is O(1) and safe to call on every `.zevtc` extraction.
- The bound is per-ENTRY, not per-archive. A multi-entry zip (unusual for `.zevtc`) is checked entry-by-entry; the current code only reads the first entry so the bound is effectively per-archive for typical input.

## Escape hatches

- If a future plan needs to allow larger entries (e.g. importing 10 GB raw EVTC for batch analytics), lift `_MAX_ZIP_ENTRY_UNCOMPRESSED_SIZE` to a `Settings` field.
- If a future plan needs streaming zip extraction (to avoid the in-memory blowup even WITH the bound), switch to `zipfile.ZipFile.open(name)` + iterative `read(chunk_size)` + per-chunk `write`. Out of scope here.
