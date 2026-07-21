# Plan 138: Revision-aware event decoding + pre-scan spawn helpers

> **Executor instructions**: This is a future-sprint plan. Captures
> the rev0/rev1 split + `STATE_CHANGE_SPAWN` pre-scan pattern from
> a public GW2 community reference implementation's `parse_event_rev0/rev1` helpers for the
> `libs/gw2_evtc_parser` package. Do NOT copy code verbatim —
> re-implement with our Protocol contract preserved.

> **Drift check (run first)**: `git diff --stat HEAD~1..HEAD -- libs/gw2_evtc_parser/src/gw2_evtc_parser/`
> On drift, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: MEDIUM (rev0 format is fragile; bit-shifts can mis-align)
- **Depends on**: none (parser-internal)
- **Category**: tech-debt / parser correctness
- **Planned at**: commit `c935acb`, 2026-07-10 (documentation only)

## Why this matters

Two patterns from a public GW2 community reference implementation worth porting:

1. **Revision-aware decoding** — arcdps added a 4-byte `map_id` field
   to the EVTC header in rev >= 1. Our current parser hard-codes the
   25-byte header layout (`HEADER_SIZE = 25`) which assumes the
   new-rev layout. Pre-rev1 logs (rare, mostly historical archives)
   would be mis-parsed. a public GW2 community reference implementation's `parse_header()` returns a
   dict with `revision` + `header_size` so callers branch cleanly.

2. **`STATE_CHANGE_SPAWN` pre-scan** — the hot loop's
   `src_master_instid` attribution needs a fully-populated
   `tag_agent_map` BEFORE the first combat event. If a player's
   SPAWN event appears LATER than their first combat event (a
   real arcdps quirk on mid-fight joins / respawns), the master
   instid resolution falls through. The pre-scan closes this
   under-1% gap by walking the event stream once before the main
   loop, only reading 3 fields per record (saves ~2M dataclass
   allocations on a 2M-event log).

## Source calibration (do not copy code)

a public GW2 community reference implementation `parser.py` distinguishes rev0 vs rev1 via:

```python
def parse_header(data: bytes) -> dict[str, Any]:
    magic = data[0:4].decode("ascii")
    if magic != "EVTC":
        raise ValueError(f"Not an EVTC file (magic: {magic!r})")
    build = data[4:12].decode("ascii", errors="replace")
    revision = data[12]
    combat_id = struct.unpack_from("<H", data, 13)[0]
    agent_count = struct.unpack_from("<I", data, 16)[0]
    header_size = 20  # default for rev0
    map_id: int | None = None
    if revision >= 1 and len(data) >= 24:
        map_id = struct.unpack_from("<I", data, 20)[0]
        header_size = 24
    return {"build": build, "revision": revision, ...}
```

WARNING (documentation only — DO NOT copy the bit-shifts):
```python
# rev0: pack as <qqqiiIHHHH13B7x>
#   time(q), src_agent(q), dst_agent(q),
#   value(i), buff_dmg(i),
#   overstack_value(i)&0xFFFF | (skillid<<16)&0xFFFF packed into I,
#   src_instid(H), dst_instid(H), src_master_instid(H), dst_master_instid(H),
#   iff(B), buff(B), result(B), is_activation(B), is_buffremove(B),
#   is_ninety(B), is_fifty(B), is_moving(B), is_statechange(B),
#   is_flanking(B) + 7 padding bytes
# The bit-shifts on `int(vals[5] >> 16) & 0xFFFF` for skillid are
# fragile. Test fixtures MUST lock the offsets.
```

Our current parser only handles rev1 (the 64-byte event record with
`_EVENT_STRUCT = struct.Struct("<QQQiiIIHHHbbbbbbbbIIbb")`). Adding
a rev0 fallback is forward-looking — the format is documented but
almost never seen in production.

The pre-scan snippet (DO NOT copy verbatim — re-implement with our `range`/`iter_events` style):

```python
# a public GW2 community reference implementation pre-scan:
_spawn_statechange_off = 56 if revision >= 1 else 54
_spawn_src_fmt = "<Q8x4x4x4x4xH" if revision >= 1 else "<q8x4x4x4xH"
pre_offset = event_offset
while pre_offset + event_size <= len(data):
    is_statechange = data[pre_offset + _spawn_statechange_off]
    if is_statechange == STATE_CHANGE_SPAWN:
        src_agent, src_instid = struct.unpack_from(_spawn_src_fmt, data, pre_offset + 8)
        ...
```

## Current state

`libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py` has:
- `_HEADER_STRUCT = struct.Struct("<4s8sBHBI IB")` (25-byte header,
  rev1-only)
- `_EVENT_STRUCT = struct.Struct("<QQQiiIIHHHbbbbbbbbIIbb")` (64-byte
  revocation, rev1-only)
- `_compute_post_skills_offset(data)` — walks the skill table to
  find the event-stream start. Already iterates the data correctly.

There is no `pre_scan_spawn()` helper today. The agents map is
populated from the agent block (96-byte records) at parse time, so
the pre-scan would NOT change that flow — only the
`tag_agent_map: dict[int, int]` for `src_master_instid → src_addr`
resolution.

## Repo conventions

- Helpers in `libs/gw2_evtc_parser/src/gw2_evtc_parser/`
  (alongside `parser.py`, `interface.py`, `exceptions.py`,
  `__main__.py`, `__init__.py`).
- Pure functions where possible; stateful iteration stays inside
  the parser class.
- New module `rev.py` for revision-coupled code so the core
  `parser.py` stays rev1-only (matches the v0.10.3 simplification
  plan in 098-v0932-gw2-evtc-parser-version-importlib-metadata-40-drift.md).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Lint | `uv run ruff check libs/gw2_evtc_parser/src/gw2_evtc_parser/rev.py` | exit 0 |
| Typecheck | `uv run mypy --no-incremental libs/gw2_evtc_parser/src/gw2_evtc_parser/rev.py` | exit 0 |
| Tests | `uv run pytest libs/gw2_evtc_parser/tests/test_rev.py -v` | all pass |

## Scope

**In scope** (when executed):
- `libs/gw2_evtc_parser/src/gw2_evtc_parser/rev.py` (NEW) — `decode_header(data) -> HeaderInfo`, `decode_event_rev0(data, offset) -> tuple`, `decode_event_rev1(data, offset) -> tuple`, `pre_scan_spawn(data, event_offset, revision) -> dict[int, int]`
- `libs/gw2_evtc_parser/tests/test_rev.py` (NEW) — hermetic tests on synthetic byte arrays
- POSSIBLY: thread into `PythonEvtcParser.parse_events` to populate `tag_agent_map` from the pre-scan BEFORE the main loop

**Out of scope**:
- Schema / DB changes
- Anything that copies a public GW2 community reference implementation source wholesale — re-implement with our consistency conventions
- Live network calls (a public GW2 community reference implementation's `_fetch_profession_name` is a
  known antipattern)
- The `gw2_analytics` aggregations (those live in plan 135-137)

## Steps (for future executor)

### Step 1: `rev.py` — header decoding

```python
@dataclass(frozen=True)
class HeaderInfo:
    build: str
    revision: int
    combat_id: int
    agent_count: int
    skill_count: int
    map_id: int | None  # rev >= 1 only
    header_size: int  # 20 for rev0, 24 for rev1 (we use 25 internally — verify)

def decode_header(data: bytes) -> HeaderInfo: ...
```

Raises `EvtcParseError` (existing exception type) on: bad magic, ASCII-decode failure on build bytes.

### Step 2: `decode_event_rev0`

Replicate the a public GW2 community reference implementation bit-shift pattern (with Pydantic v2 validation on the output tuple). Use a fixed `struct.Struct` per a public GW2 community reference implementation's `<qqqiiIHHHH13B7x` layout, but document the offsets explicitly per the a public GW2 community reference implementation calibration note (the offset miscount risk is real; fixture tests are the only way to lock it).

### Step 3: `decode_event_rev1`

Mirror the existing `_EVENT_STRUCT.unpack_from` in a free function (no implicit state refactor needed).

### Step 4: `pre_scan_spawn`

Pure function that walks `data[event_offset:]` in 64-byte strides (or whatever the event record size is per revision), reads only `is_statechange` byte at offset 56 (or 54 for rev0), and bails on `STATE_CHANGE_SPAWN` matches. Returns `dict[int, int]` (inst_id → addr).

### Step 5: Wire into `parse_events`

If the parser is updated to use the pre-scan, the change is:
- Call `pre_scan_spawn(data, event_offset, revision)` once before the main loop.
- Pass the resulting `tag_agent_map` to the existing per-event loop as a closure capture or generator parameter.

NO call site changes outside the parser — the public Protocol is unchanged.

## Test plan

- 5 NEW hermetic tests in `test_rev.py`:
  1. `decode_header` on a 25-byte synth header (rev1) returns `HeaderInfo(header_size=25, map_id=...)`.
  2. `decode_header` on a 21-byte synth header (rev0) returns `HeaderInfo(header_size=20, map_id=None)`.
  3. `decode_event_rev0` on a 64-byte synth event returns the correct tuple (locks the bit-shift layout).
  4. `decode_event_rev1` on a 64-byte synth event returns the same tuple shape as the a public GW2 community reference implementation rev0 result (modulo extension).
  5. `pre_scan_spawn` on a synthetic blob with 1 SPAWN event returns `{inst_id: addr}` matching.

## Done criteria

- [ ] `uv run ruff check libs/gw2_evtc_parser/src/gw2_evtc_parser/rev.py` exits 0
- [ ] `uv run mypy --no-incremental libs/gw2_evtc_parser/src/gw2_evtc_parser/rev.py` exits 0
- [ ] `uv run pytest libs/gw2_evtc_parser/tests/test_rev.py -v` — all tests pass
- [ ] No files outside the in-scope list are modified
- [ ] `plans/README.md` status row updated

## STOP conditions

- If a real rev0 .zevtc is unavailable for fixture generation, the
  rev0 path is documented but the implementation is gated on
  "until a real rev0 fixture arrives". A future maintainer can
  contact the arcdps community for sample rev0 logs.
- If the `is_statechange` byte offset calibration (56 / 54 per
  a public GW2 community reference implementation) is wrong on a real .zevtc, the pre-scan returns
  spurious agents. The test fixture MUST lock the offset.

## Maintenance notes

- The pre-scan is bounded — it walks the event stream ONCE in a
  pure-read loop. For a 2M-event log (~128 MB raw), the runtime cost
  is ~50 ms (3 field reads per record, no allocations). Per a public GW2 community reference implementation's
  calibration, this closes the "less than 1% gap" where mid-fight
  joins were missed by the master-instid attribution.
- The pre-scan is OPTIONAL: the parser MUST continue to work without
  it (fallback behavior unchanged). The plan is forward-compat
  cleanup, not a bug fix.
- Don't copy a public GW2 community reference implementation's bit-shift dance verbatim. The
  `_fetch_profession_name` style "trust the offset comments" is
  exactly the kind of fragile-by-design pattern we want to avoid.
  Use `_EVENT_STRUCT` instances (Pydantic-validated output) instead.
