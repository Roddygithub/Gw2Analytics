# Plan 027 — v0.10.10: stream `_event_dispatch.build_event_iterator` via `gzip.GzipFile` (eliminates the `gzip.decompress + splitlines` memory peak)

**Stamped at:** `f0249ef` (working-tree diff HEAD; all changes in this plan live in the uncommitted working tree)
**Severity:** HIGH (perf + correctness; contradicts the docstring's intent)
**Category:** perf, correctness
**Addresses finding:** `_event_dispatch.build_event_iterator` materialises the entire gzipped blob into a `str` AND a `list[str]` before yielding any event — the docstring claims *"Returns an iterator (NOT a list) so a blob with 100K events pays no upfront materialisation cost"* but the implementation does the OPPOSITE. A 30 MB gzipped WvW log (typical WvW squad-on-squad fights with 60k+ events) → ~300-500 MB peak RAM per concurrent route call. Combined with a parallel fight-page load (4 endpoints × `Promise.allSettled` in the frontend), 4× the peak. The route's anti-OOM guarantee from the parser side (plan 020, zip-bomb 500 MB ceiling) is fully bypassed on the *read* path.

---

## Finding

Evidence (current working-tree source):

```python
# apps/api/src/gw2analytics_api/_event_dispatch.py:50-60
def build_event_iterator(*, gz_bytes: bytes) -> Iterator[Event]:
    ...
    jsonl = gzip.decompress(gz_bytes)                   # materialises full decompressed str (~7-10x compressed size)
    for line in jsonl.splitlines():                     # builds a complete list[str] from the str
        if not line:
            continue
        yield EVENT_TYPE_ADAPTER.validate_json(line)
```

### Two-step materialisation explanation

- `gzip.decompress(bytes)` returns a `bytes` blob of the FULL uncompressed stream in memory (typical WvW = 30 MB compressed → 200 MB uncompressed).
- `.splitlines()` on a 200 MB `bytes`/`str` returns a **`list[bytes]`** (or `list[str]` — depending on Python version and overload resolution) containing ALL lines. For 60k events, that's a list of 60k tuple-headers + pointers, ~5-10 MB overhead on top of the 200 MB string.
- Total peak: ~210-220 MB per concurrent route call. With 4 endpoints on `/fights/{id}` called in parallel (frontend `Promise.allSettled`) → 800-900 MB peak for one analyst opening a fight page.

### The `gzip.GzipFile` alternative

`gzip.GzipFile(fileobj=io.BytesIO(gz_bytes))` is a streaming file-like wrapper. Iterating it line-by-line calls into zlib for each chunk, decompressing on-demand. Memory peak is ~64 KB (one buffered chunk) regardless of the source size.

---

## Fix

### Step 1 — Replace the body of `build_event_iterator` with a streaming wrapper

In `apps/api/src/gw2analytics_api/_event_dispatch.py`:

```python
import gzip
import io
from collections.abc import Iterator

from pydantic import TypeAdapter

from gw2_core import Event

EVENT_TYPE_ADAPTER: TypeAdapter[Event] = TypeAdapter(Event)


def build_event_iterator(*, gz_bytes: bytes) -> Iterator[Event]:
    """Decompress + split + adapter-validate a gzipped JSONL blob, streaming.

    See module docstring for the single-source-of-truth rationale.
    The stream wrapper keeps memory peak at ~64 KB (one
    zlib-chunk) regardless of the input size, so a 30 MB gzipped
    WvW log does NOT spike to 200 MB of strings + a 60k line list
    pre-yield. ``validate_json`` accepts ``bytes`` lines directly
    (Pydantic v2 decodes the JSONL line in-place), so an extra
    ``.decode("utf-8")`` would only re-introduce the
    materialisation cost we're removing here.

    Empty / whitespace-only lines are dropped (handled by ``or line.strip()``
    below; ``bytes.strip()`` strips both whitespace and the trailing ``\n``,
    so ``if line.strip()`` is the correct guard for the
    ``b"\\n"``-terminated JSONL format the parser writes).
    """
    with gzip.GzipFile(fileobj=io.BytesIO(gz_bytes)) as gz:
        for line in gz:
            if not line.strip():
                continue
            yield EVENT_TYPE_ADAPTER.validate_json(line)


__all__ = ["EVENT_TYPE_ADAPTER", "build_event_iterator"]
```

### Step 2 — Preserve `bytes`-line compatibility

`gzip.GzipFile` yields `bytes`, not `str`. The `TypeAdapter.validate_json` method accepts `bytes` natively in Pydantic v2 (it parses the JSON bytes in place, no `.decode("utf-8")` round-trip). This is one fewer materialisation compared to decoding to `str` first.

### Step 3 — Update the docstring in `_event_dispatch.py` module docstring

The current docstring already describes the streaming intent; the body just doesn't match. Replace the body to remove the now-obsolete `jsonl = gzip.decompress(gz_bytes)` line. The docstring's "Centralises the gzip.decompress → splitlines → TypeAdapter.validate_json round-trip" sentence can stay (the conceptual pipeline is unchanged; only the implementation is streaming).

### Step 4 — Update the call sites if they assume `list[Event]` shape

Two call sites consume `build_event_iterator`:

- `apps/api/src/gw2analytics_api/routes/fights.py::_load_fight_events` (calls `list(build_event_iterator(gz_bytes=gz_bytes))`) — already materialises to a list. No change needed.
- `apps/api/src/gw2analytics_api/routes/players.py::_contributions_from_blob_walk` (calls `list(build_event_iterator(gz_bytes=gz_bytes))`) — same.

The streaming benefit is realised by ROUTE handlers that *previously* had `.splitlines()` building a fully-materialised list + THEN iterating. Both routes call `list(...)` exactly once, so the primary memory win is at the `gzip.decompress + splitlines` site (this plan's fix site). The second-tier win (no `list(...)` materialisation on routes that can iterate once) is out of scope for this plan; if event-stream mega-fights (>200k events) emerge, a separate plan can revisit.

---

## Tests

### Test file 1 — NEW `apps/api/tests/test_event_dispatch_streaming.py`

Pattern reference: `apps/api/tests/test_event_dispatch.py` (existing v0.9.38 plan 116 test file) for the build_event_iterator contract; the new file is additive (doesn't replace it).

5 hermetic tests (no live DB / no live S3):

1. `test_streaming_constructs_gzipfile_with_bytesio` — monkeypatch `gzip.GzipFile` (the constructor) and assert the helper invokes it with `fileobj=io.BytesIO(<the_bytes>)`. This is the cleanest streaming-behaviour signal: the `gzip.decompress` legacy path NEVER constructs a `GzipFile`; the streaming path does. **Avoid** monkeypatching `read()` — `for line in gz: ...` invokes `readline()` internally, not `read()`. Mocking `read()` would never fire on the streaming path.

2. `test_output_yields_same_events_as_legacy` — pin byte-identical output on the 3-line discriminator case from `test_event_dispatch.py`. The new path MUST produce the same `DamageEvent | HealingEvent | BuffRemovalEvent` instances in the same order. Confirms the swap doesn't change semantics.

3. `test_large_blob_uses_constant_memory` — construct a 10 MB gzipped JSONL (10k events × ~1 KB each). Patch `tracemalloc` to take snapshots before/after iterating. Assert the post-iteration peak delta is `<2 MB` (the streaming `BytesIO` peak + the 10k validate_json Pydantic models' overhead). The pre-fix path would peak at ~80 MB.

4. `test_returns_iterator_not_list` — the function annotation `-> Iterator[Event]` is preserved. `inspect.isgeneratorfunction` returns True (because it's a generator function with `yield`).

5. `test_empty_whitespace_and_trailing_newline_lines_dropped` — feed a gzipped blob containing: an empty line (`b"\n"`), a whitespace-only line (`b"   \n"`), and a line with embedded whitespace + trailing newline (`b" {\"foo\": 1}   \n"`). Assert the iterator yields 1 event (the JSON one), not 3. Pins the trailing-newline semantics: `bytes.strip()` strips both embedded whitespace AND the trailing `\n`, so the guard `if not line.strip()` accepts only non-empty trimmed lines. Also pins the empty-line + pure-whitespace-line drop (paired with `for line in gz: if line.strip(): ...`).

### Test file 2 — EXTEND `apps/api/tests/test_event_dispatch.py`

Add 1 regression test:

`test_build_event_iterator_does_not_use_gzip_decompress` — `inspect.getsource(build_event_iterator)` MUST NOT contain the `gzip.decompress(` substring. Pins the streaming implementation; a future revert to the legacy path fails the test.

---

## Out of scope

- The `list(...)` materialisation in `routes/players.py` and `routes/fights.py::_load_fight_events`. Both routes consume the iterator once via `list(...)` for downstream aggregators. The OOM win is at the gzip site, not the route site.
- Stream-decoding of large EVTC blobs at the parser side (covered by plan 020, zip-bomb protection).
- A future `lru_cache(maxsize=4)` of the *parsed* `list[Event]` shape — that's a separate perf win keyed on `blob_uri`, independent of this plan.
- Changing `TypeAdapter(Event)` to use `validate_python` instead of `validate_json` (Pydantic v2 has a faster `validate_python`; out of scope: would require the parser to write Python-list-of-dict instead of JSONL, breaking the wire format).

---

## Done criteria

Run from repo root after the fix is applied:

```bash
# 1. Ruff is clean.
uv run ruff check apps/api/

# 2. mypy --strict tolerates the change.
uv run mypy libs apps --no-incremental

# 3. Both new/extended test files pass.
uv run pytest apps/api/tests/test_event_dispatch_streaming.py -v
uv run pytest apps/api/tests/test_event_dispatch.py -v

# 4. The legacy `gzip.decompress(` call is gone from the helper body.
grep -nE 'gzip\.decompress\(' apps/api/src/gw2analytics_api/_event_dispatch.py
# Expected output: (empty -- the module + helper no longer use it)

# 5. The streaming GzipFile wrapper is in place.
grep -nE 'gzip\.GzipFile' apps/api/src/gw2analytics_api/_event_dispatch.py
# Expected output: 1 match in the build_event_iterator function body.
```

---

## Maintenance note

- The streaming wrapper relies on `gzip.GzipFile` buffering at the zlib-chunk level (typically 32-64 KB). If a future refactor introduces a custom buffer size (e.g. for throughput reasons), inspect: the peak is `buffer_size * 2` (decompressor + leftover in BytesIO). Today the default is fine.
- `validate_json(bytes)` in Pydantic v2 decodes the bytes inline. If a future Pydantic version reverts to requiring `str`, the helper must re-add `.decode("utf-8")` (without re-introducing the full-string materialisation — decode line by line).
- The parser-side writing of gzipped JSONL (today: `gzip.compress(jsonl.encode("utf-8"))` in `services/event_blob.py`) is unchanged. The wire format is identical; only the read path streams.

---

## Escape hatches

- **Performance regression on small blobs (e.g. <1k events)?** The `gzip.GzipFile` overhead per `read()` call is ~1 µs. For a 1k-event blob, the helper does ~17 zlib-chunk reads (64 KB / 1 KB). The total overhead is sub-millisecond — measurably faster than `gzip.decompress + splitlines + 1000 validate_json calls`. If a profiler shows the opposite, consider a fast-path for `gz_bytes < threshold` (e.g. `len(gz_bytes) < 65536`). Out of scope for this plan, but a future plan can add.
- **`gzip.GzipFile` raises `OSError` on truncated input?** Yes (this is the canonical `EOFError` path). The route's `except (OSError, EOFError)` clause handles both. NO change needed at the call site.
- **STOP and report back if**: a regression test fails on a *real* fixtures `.zevtc` file (not synthetic fixtures). Synthetic fixtures are constructed with explicit `gz_bytes` payloads; real fixtures may have zlib-compression quirks (e.g. concatenated streams that GzipFile handles differently from `gzip.decompress`). If a real-fixture regression appears, the fix is to fall back to `gzip.decompress` for non-stream-compatible inputs OR to manually parse the zlib header to confirm single-stream format.

---

## Dependency graph

- **Independent.** Touches only `apps/api/src/gw2analytics_api/_event_dispatch.py` + 1 NEW + 1 EXTENDED test file. No plan depends on this one; this plan doesn't depend on any.

## Cross-references

- Plan 020 (v0.9.6) — parser-side zip-bomb protection (the write-side counterpart to this plan's read-side streaming).
- Plan 116 (v0.9.38) — `TypeAdapter(Event)` consolidation (the structural predecessor; this plan touches the same module).
