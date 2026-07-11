# Plan 066 — v0.9.21: dedupe `_iter_skills` and `_compute_post_skills_offset` via shared `_iter_skill_records` helper

## Drift base

`44ea862`. Refactor only — additive, no migration. The
behavioural contract is preserved byte-for-byte.

## Surface

`libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py`:
- `_iter_skills(data, offset, count)` (the Skill record iterator)
- `_compute_post_skills_offset(data)` (the byte-offset
  computation used by `parse_events` to skip past the skill
  table)

`libs/gw2_evtc_parser/tests/test_parser.py` (for the
regression tests).

## Finding

`_iter_skills` (lines ~325-373) and
`_compute_post_skills_offset` (lines ~378-405) walk the same
data with the same logic but produce different outputs:

- `_iter_skills` yields `Skill` records (id + decoded name).
- `_compute_post_skills_offset` yields the byte offset where
  the event stream starts.

Both functions:
1. Check `count == 0` → return early.
2. Loop `for skill_index in range(count)`.
3. Check `cursor + _SKILL_HEADER_STRUCT.size > end` →
   log a warning + return (truncation).
4. Unpack `skill_id, name_len` from the header.
5. Check `name_len > MAX_SKILL_NAME_BYTES` → log a warning
   + return (oversized name).
6. Compute `record_size = _SKILL_HEADER_STRUCT.size + name_len + 1`.
7. Check `cursor + record_size > end` → log a warning +
   return (body truncation).
8. Advance `cursor += record_size` (or yield `Skill(...)`).

The 7 steps are duplicated. A bug fix in any of them (e.g.,
a new safety bound for `name_len` after a future arcdps
release, or a new warning level for oversize skills) would
need to be mirrored in both functions. Drift risk is real:
a future maintainer who fixes `_iter_skills` but forgets
`_compute_post_skills_offset` would create a silent
divergence between the skill table (parsed correctly) and
the event stream offset (computed incorrectly).

## Fix

1. Extract a private helper `_iter_skill_records` that yields
   the parsed `(skill_id, name_len, name)` triple for each
   skill record, with the truncation/oversize checks at one
   site:

   ```python
   def _iter_skill_records(
       data: bytes, offset: int, count: int
   ) -> Iterator[tuple[int, int, str]]:
       """Yield ``(skill_id, name_len, name)`` for each skill record.

       Stops early on truncation or oversized name_len
       (with a warning log); the yielded count may be less
       than ``count``. This is the single source of truth for
       the skill table walk; both ``_iter_skills`` (the public
       ``Skill`` record iterator) and
       ``_compute_post_skills_offset`` (the byte-offset
       computation for the event stream) use this helper.
       """
       if count == 0:
           return
       cursor = offset
       end = len(data)
       for skill_index in range(count):
           if cursor + _SKILL_HEADER_STRUCT.size > end:
               logger.warning(
                   "Truncated skill table at skill %d: ...",
                   skill_index,
               )
               return
           skill_id, name_len = _SKILL_HEADER_STRUCT.unpack_from(
               data, cursor
           )
           if name_len > MAX_SKILL_NAME_BYTES:
               logger.warning(
                   "Skill %d at offset %d has name_len=%d ...",
                   skill_index,
                   cursor,
                   name_len,
               )
               return
           record_size = _SKILL_HEADER_STRUCT.size + name_len + 1
           if cursor + record_size > end:
               logger.warning(
                   "Truncated skill body at skill %d offset %d: ...",
                   skill_index,
                   cursor,
                   record_size,
               )
               return
           name_bytes = data[
               cursor + _SKILL_HEADER_STRUCT.size
               : cursor + _SKILL_HEADER_STRUCT.size + name_len
           ]
           name = name_bytes.decode("utf-8", errors="replace")
           yield skill_id, name_len, name
           cursor += record_size
   ```

2. Refactor `_iter_skills` to consume the helper:

   ```python
   def _iter_skills(
       data: bytes, offset: int, count: int
   ) -> Iterator[Skill]:
       for skill_id, _name_len, name in _iter_skill_records(
           data, offset, count
       ):
           yield Skill(id=skill_id, name=name)
   ```

3. Refactor `_compute_post_skills_offset` to consume the
   helper and compute the end-of-skill-table offset by
   re-walking the records with a `cursor` accumulator:

   ```python
   def _compute_post_skills_offset(data: bytes) -> int:
       """Return the byte offset where the event stream starts."""
       if len(data) < HEADER_SIZE:
           return len(data)
       unpacked_header = _HEADER_STRUCT.unpack_from(data, 0)
       agent_count = int(unpacked_header[5])
       skill_count = int(unpacked_header[6])
       cursor = HEADER_SIZE + agent_count * AGENT_SIZE
       end = len(data)
       for skill_id, name_len, _name in _iter_skill_records(
           data, cursor, skill_count
       ):
           cursor += _SKILL_HEADER_STRUCT.size + name_len + 1
           if cursor > end:
               return end
       return cursor
   ```

   The `cursor += _SKILL_HEADER_STRUCT.size + name_len + 1`
   line is intentionally re-computed (the helper yields
   `(skill_id, name_len, name)` but doesn't track the next
   offset). This 1-line re-computation is simpler than threading
   a "next_offset" through the helper.

## Why not a `Iterator[tuple[int, int, int, int, str]]` (5-tuple)

Yielding 5 values is error-prone (callers forget the order).
Yielding 3 values (`(skill_id, name_len, name)`) is canonical
Python; the helper consumers can ignore `name_len` if they
don't need it (the public `Skill` record doesn't carry
`name_len`).

## Why not `Iterator[Skill]` directly

The byte-offset consumer needs `(skill_id, name_len, name)`
to compute the cursor advance, not the `Skill` Pydantic
model. Yielding `Skill` would force the byte-offset consumer
to construct a `Skill` instance just to read the `id` and
`name` (the `name_len` is the critical bit for the cursor
advance).

## Risks

- The 3 log messages in `_iter_skill_records` are byte-for-byte
  identical to the 3 in `_iter_skills` (the original function).
  Test fixtures that match the log messages (e.g., `caplog`
  in the existing tests) would still pass.
- The `cursor` accumulator in `_compute_post_skills_offset`
  re-computes `record_size` from `name_len` (the helper
  yields it). This is O(1) per skill; for N=1000 skills it's
  O(N) = 1000 operations, identical to the original function.
- The 2 `try/except` blocks are unchanged (no error handling
  changes).
- The `if count == 0: return` early return is preserved in
  both the helper and the consumers.

## Tests

1. `test_iter_skill_records_yields_same_triples_as_iter_skills`
   — feed a canonical EVTC blob (with 5 skills) to both
   `_iter_skills` and `_iter_skill_records`; assert the
   `(skill_id, name)` pairs match (ignoring `name_len`).
2. `test_iter_skill_records_stops_on_truncation` — feed a
   truncated blob; assert `_iter_skill_records` yields
   fewer than `count` triples and emits the
   "Truncated skill table" warning.
3. `test_iter_skill_records_stops_on_oversized_name` — feed
   a blob with a skill whose `name_len` exceeds
   `MAX_SKILL_NAME_BYTES`; assert the helper stops at that
   record and emits the "name_len exceeding safety bound"
   warning.
4. `test_compute_post_skills_offset_uses_helper` — feed a
   canonical blob; assert the byte offset is identical
   between the original and refactored versions (no
   behavioural change).
5. `test_compute_post_skills_offset_returns_end_on_truncation`
   — feed a truncated blob; assert the returned offset
   is the truncation point (not `len(data)`).
6. `test_parse_events_offset_matches_iter_skills_end` — call
   `parse_events` on a canonical blob; assert the first
   event's `time_ms` is non-zero (sanity check that the
   offset is past the skill table, not in the middle of it).

## Rejected alternatives

- **Inline `_compute_post_skills_offset` into `parse_events`**:
  tempting (the function is only used in one place). The
  offset computation is non-trivial (the skill table walk);
  inlining would clutter `parse_events` (already a
  100-line function).
- **Add a `next_offset` field to the helper's yield tuple**:
  tempting (eliminates the re-computation in
  `_compute_post_skills_offset`). The `name_len + 1` is O(1)
  per skill; the re-computation cost is negligible. The
  3-tuple yield is more Pythonic than a 4-tuple.
- **Use `functools.partial` to bind `data, offset, count` to
  the helper**: out of scope (the helper needs the consumer's
  loop body; partial doesn't help).
- **Switch to a dataclass `_SkillRecord`** instead of a
  3-tuple: out of scope (the helper is private; the 3-tuple
  is the canonical Python "internal record" idiom for a
  function-private helper).
- **Move `_iter_skill_records` to a new
  `libs/gw2_evtc_parser/_skill_table.py` module**: out of
  scope (the helper is private to the parser; the module
  is small enough that 1 file is appropriate).
