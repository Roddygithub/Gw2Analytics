# Plan 100 (v0.9.32) — `__main__.py::cmd_inspect_zip` streaming fix (no full-entry decompression)

## Files touched
- `libs/gw2_evtc_parser/src/gw2_evtc_parser/__main__.py` (1-line change in `cmd_inspect_zip`: `zf.read(name)[:16]` → `zf.open(name).read(16)`)

## Findings (audit)

- `__main__.py::cmd_inspect_zip` line 92 calls `head = zf.read(name)[:16]`.
- The Python `zipfile.ZipFile.read(name)` method explicitly DELETES the entire entry (decompresses it fully into memory), then takes a slice of the first 16 bytes. The docstring on `zf.read` confirms: "Return the bytes of the file `name` in the archive ... extracts the entire archive entry into memory".
- For a `.zevtc` archive whose single compressed entry is a 80-120 MB EVTC file (typical Phase 6+ arcdps logs), `inspect-zip` decompresses ~100 MB into RAM JUST to display the first 16 bytes, then drops 99.99984% of the bytes. On a small VM or in CI, this OOMs (default colab VMs have 1-4 GB RAM).
- The CLI's documented purpose is "Dump the zip layout of a .zevtc file" — a quick HEAD peek — but the implementation costs the consumer the FULL EVTC bytes. The CLI is unusable on large logs without enough memory headroom.
- The fix: `zf.open(name)` returns a `ZipExtFile` (a streaming file-like). `zf.open(name).read(16)` reads only 16 bytes from the stream and discards the rest. This is the canonical Python stdlib pattern for "peek at the head of a zip entry".
- Real-world impact today: this CLI is used by analyst-tier debugging (does this log file look structurally valid before kicking off a parse?); analysts routinely work with 50-200 MB logs because of squad-scale WvW fights. The OOM blocks a common workflow without an obvious workaround.

## Fix

1. `__main__.py::cmd_inspect_zip` line ~92 — replace:

   ```python
   if info.file_size > 0:
       head = zf.read(name)[:16]
       print(f"    head: {head!r}")
   ```

   with:

   ```python
   if info.file_size > 0:
       # Stream-read only the head bytes; don't decompress the
       # whole entry into RAM (a single .zevtc entry can be
       # 100+ MB of compressed EVTC bytes).
       with zf.open(name) as entry:
           head = entry.read(16)
       print(f"    head: {head!r}")
   ```

2. NO change to other methods.

3. NO change to `_load_payload` (in `cmd_dump_agents`) — that path needs the FULL EVTC bytes to feed `PythonEvtcParser.parse(...)`. The streaming fix is scoped to the inspector.

## Tests (4 hermetic, NEW file `libs/gw2_evtc_parser/tests/test_main_inspect_zip.py`)

- `test_inspect_zip_does_not_call_full_read_on_head` — `monkeypatch` `zipfile.ZipFile.read`, call `cmd_inspect_zip` on a tiny test zip, assert `mock_read.call_count == 0` (the streaming `open` path doesn't trigger `read`). Confirms the fix is in place.
- `test_inspect_zip_emits_correct_head_bytes` — build a tiny in-memory `.zevtc` containing one entry "evtc.bin" with bytes `b"EVTC20250925..."`; call `cmd_inspect_zip` against it; capture stdout; assert `'head: b"EVTC20250925..."'` appears (case-correct head peek).
- `test_inspect_zip_skips_empty_entries` — build a zip with one entry "empty.bin" of `file_size=0`; assert the head peek is skipped (no malformed truncation). Defensive: catches a future regression where `if info.file_size > 0` is dropped.
- `test_inspect_zip_correctly_handles_badzipfile` — pass a corrupt file path; stdout stderr must contain "ERROR" + the parse error message; exit code must be 2 (the existing semantic for bad-zip files).

## Rejected alternatives

- **Cap the head peek to N bytes via a `MAX_HEAD_BYTES` constant** — `read(16)` already caps; the issue is the underlying `zf.read()` call that pulls the FULL entry. The streaming `zf.open` is the right fix. REJECTED.
- **Use `zf.open(name, 'r')` and `entry.read(16)` with `pypdf`-style buffer chunking** — overengineering for a 16-byte peek. The stdlib `ZipExtFile.read(N)` is the canonical pattern. REJECTED.
- **Skip the head peek entirely; show only entry metadata (name, size, compression)** — removes a useful debugging affordance (the head peek is for "does this look like a real EVTC?"). The streaming fix keeps the affordance. REJECTED.
- **Replace `zf.read()` with `gzip.decompress(zf.read(...))`** — misreads the file format; `inspect-zip` operates on raw zip entries, not gzipped streams. The CLI already accepts `.zevtc` (which is a zip) — there's no further decompression layer. REJECTED.
- **Make `inspect-zip` an opt-in lazy mode (`--no-head` flag) so callers that want the head peek can keep the old behaviour** — preserves a known-bad path; the streaming is universally better. REJECTED.

## Dependency graph

- Independent: touches `__main__.py` line ~92 only.
- Parallel-safe with plans 098 / 099 (different file regions: 098 touches `__init__.py` + `pyproject.toml`; 099 touches `interface.py` docstring).
- Pattern-aligned with `parser.py::_read_all`'s streaming fix (per plan 067 v0.9.21's `MAX_EVTC_BYTES` cap). The CLI inspector is now a small-budget streaming consumer; the parser's read path is the high-budget consumer; both share the stdlib `with zf.open(...) as entry` pattern.
