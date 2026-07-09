# Plan 067 — v0.9.21: `MAX_EVTC_BYTES` cap in `parser.py::_read_all` (defense-in-depth DoS protection)

## Drift base

`44ea862`. Drift cleanup only — additive, no migration.

## Surface

`libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py`:
- NEW module-level constant `MAX_EVTC_BYTES: Final[int] = 100 * 1024 * 1024`
- NEW check in `_read_all(source)` after the `data` is materialized

`libs/gw2_evtc_parser/tests/test_parser.py` (for the
hermetic regression tests).

## Finding

`_read_all(source)` (lines ~268-281) materialises the input
`bytes` or `BinaryIO.read()` into a single `bytes` object
without any upper bound:

```python
def _read_all(source: BinaryIO | bytes) -> bytes:
    if isinstance(source, bytes):
        return bytes(source)
    if hasattr(source, "read"):
        return source.read()
    msg = f"Expected bytes or BinaryIO, got {type(source).__name__}"
    raise TypeError(msg)
```

A malicious or pathological .zevtc of 1 GB OOMs the parser
because:
- The full bytes are loaded into memory before
  `_iter_fights` is called.
- The `MAX_AGENTS` + `MAX_SKILLS` + `MAX_SKILL_NAME_BYTES`
  safety bounds protect the agent + skill tables, but they
  protect the **structure** of the data, not the **size**
  of the input.
- A 1 GB EVTC with `agent_count=2, skill_count=2, event_stream=1GB`
  passes all the structure checks but allocates 1 GB for the
  event stream.

The API layer (per plan 048) caps the upload size at
`MAX_UPLOAD_BYTES = 30 MB` via the `UploadFile(max_size=...)`
parameter. The parser is therefore protected at the API
boundary. But:
- A direct library consumer (e.g., a CLI tool, a Jupyter
  notebook, an FaaS worker) bypasses the API layer.
- A test that creates a 100 MB fake .zevtc (e.g., to test
  the parser's behaviour on long event streams) hits the
  OOM without a clear error message.
- The parser is the **canonical** entry point for EVTC
  processing; the safety bound should live in the parser,
  not the API.

## Fix

1. **Add the constant** in the "Binary layout constants"
   section, alongside `MAX_AGENTS` + `MAX_SKILLS` +
   `MAX_SKILL_NAME_BYTES`:

   ```python
   #: Maximum bytes for the entire EVTC blob. arcdps
   #: caps canonical WvW raids at ~5-20 MB; the API layer
   #: (per plan 048) caps at 30 MB. The parser's cap is
   #: set to 100 MB to give direct library consumers
   #: (CLI tools, Jupyter notebooks, FaaS workers)
   #: headroom for processing larger fight archives
   #: without OOM. The cap is checked once in
   #: ``_read_all`` AFTER the bytes are materialised, so
   #: the error message includes the actual size.
   MAX_EVTC_BYTES: Final[int] = 100 * 1024 * 1024  # 100 MB
   ```

2. **Add the check** in `_read_all` after the data is
   materialised:

   ```python
   def _read_all(source: BinaryIO | bytes) -> bytes:
       if isinstance(source, bytes):
           data = bytes(source)
       elif hasattr(source, "read"):
           data = source.read()
       else:
           msg = f"Expected bytes or BinaryIO, got {type(source).__name__}"
           raise TypeError(msg)
       if len(data) > MAX_EVTC_BYTES:
           raise EvtcParseError(
               f"EVTC blob is {len(data)} bytes, exceeds safety bound "
               f"{MAX_EVTC_BYTES} bytes ({MAX_EVTC_BYTES // (1024 * 1024)} MB); "
               f"refusing to allocate. Split the blob or use the streaming "
               f"parse_events API for larger archives."
           )
       return data
   ```

3. **Document the new bound** in the module docstring's
   "Binary layout constants" section.

## Why 100 MB

- Canonical WvW raid: 5-20 MB. 100 MB is 5-20× the canonical.
- API cap: 30 MB (per plan 048). 100 MB is ~3× the API cap.
- A 100 MB blob is ~1.5M events (each event is 64 bytes); a
  very long multi-hour archive is plausible. 100 MB
  accommodates this without OOM.
- Larger caps (e.g., 1 GB) would risk OOM on containers with
  4 GB RAM; 100 MB is safe on the canonical 8 GB container.

## Why check in `_read_all` (not in `_iter_fights` or `parse_events`)

`_read_all` is the single chokepoint for materialising the
input bytes. The check is performed once, regardless of which
parser method is called (`parse()` + `parse_events()` both go
through `_read_all`). A check in `_iter_fights` would be
duplicated across `parse_events`.

The check is AFTER the materialisation (not before) because:
- For `bytes` input, the bytes are already in memory; checking
  the size before copying is a micro-optimisation.
- For `BinaryIO` input, the full `read()` is required to know
  the size; checking after is the natural place.

The error message includes the actual size + the bound + a
remediation hint ("split the blob or use the streaming
parse_events API"). The streaming API is a future enhancement
(not in this plan's scope).

## Risks

- The 100 MB cap is stricter than the API's 30 MB cap. A
  direct library consumer who processes a 50 MB archive
  (larger than the API cap) would pass; a 150 MB archive
  would fail. This is the intended behavior (the parser
  is more lenient than the API for direct use).
- The check is performed AFTER the data is in memory. A
  1 GB `BinaryIO.read()` allocates 1 GB before the check
  raises. The check is "defense in depth" (prevents the
  parser from OOM-ing on the agent + skill + event parsing
  after the data is loaded), not "memory pre-allocation
  protection" (the allocation has already happened).
- A future plan that adds a streaming parser (per
  `docs/ROADMAP.md` §2 "Rust + PyO3 parser binding") would
  not need the cap; the streaming parser processes the
  bytes incrementally. The cap is a Python-parser-specific
  backstop.

## Tests

1. `test_read_all_under_cap_passes` — feed a 50 MB `bytes`
   to `_read_all`; assert no exception; assert the returned
   bytes are the input.
2. `test_read_all_over_cap_raises` — feed a 200 MB `bytes`
   to `_read_all`; assert `EvtcParseError` is raised with
   a message that includes the actual size + the bound.
3. `test_read_all_at_cap_passes` — feed a 100 MB `bytes`
   to `_read_all`; assert no exception (the bound is
   inclusive, not exclusive).
4. `test_read_all_binary_io_over_cap_raises` — feed a
   200 MB `BinaryIO` (an `io.BytesIO` of 200 MB bytes) to
   `_read_all`; assert `EvtcParseError` is raised.
5. `test_parse_with_oversized_blob_raises` — feed a 200 MB
   `bytes` to `PythonEvtcParser.parse`; assert
   `EvtcParseError` is raised (the check in `_read_all`
   propagates through `parse`).
6. `test_parse_events_with_oversized_blob_raises` — same
   for `PythonEvtcParser.parse_events`.

## Rejected alternatives

- **Check in `parse()` and `parse_events()` separately (not
  in `_read_all`)**: out of scope (the check is duplicated
  in 2 places; `_read_all` is the single chokepoint).
- **Check via `os.environ.get("GW2_PARSER_MAX_BYTES")`**
  (operator-overridable cap): out of scope. The 100 MB cap
  is a safety bound, not a tunable. A future plan can add
  an env-var override if an operator requests it (similar
  to plan 040's `db_pool_size` env var).
- **Check via a pre-allocation size hint** (e.g.,
  `BinaryIO.seek(0, 2); tell()`): tempting (prevents the
  allocation). The `tell()` is not reliable for non-seekable
  streams; the post-allocation check is the canonical
  pattern.
- **Drop the cap entirely** (rely on the API's 30 MB cap):
  tempting (the API is the canonical entry point). Direct
  library consumers (CLI tools, Jupyter notebooks) bypass
  the API; the cap is the defense-in-depth backstop.
- **Set the cap to 1 GB** (accommodate very large archives):
  out of scope (1 GB is 2.5× the 4 GB container's
  memory budget for the parser; OOM risk).
- **Stream the event records** (per `docs/ROADMAP.md` §2
  "Rust + PyO3 parser binding"): out of scope (the streaming
  parser is a future Rust binding; the Python parser is
  memory-bound).
