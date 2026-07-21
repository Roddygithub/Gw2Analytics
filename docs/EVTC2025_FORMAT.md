# EVTC2025+ Binary Format

This document describes the binary format of arcdps `.zevtc` log files for builds
dated **2025 or later** (`yyyymmdd >= 20250101`). The parser in
`libs/gw2_evtc_parser` auto-detects the format at parse time; consumers do not
need to pre-declare the version.

---

## 1. Detection

Build strings are exactly 8 ASCII digits (`yyyymmdd`). The parser's
`_build_version_from_build_str` extracts the year: if `year >= 2025`, the
EVTC2025+ layout is used; otherwise the legacy format applies.

```python
# From parser.py
is_evtc_2025 = build_int >= 2025_00_00
```

---

## 2. File Structure

Every `.zevtc` is a ZIP file containing a single entry `fight.evtc`:

```
[ZIP header]
  fight.evtc:
    [Header      — 24 bytes]
    [Agent table — N × 96 bytes (EVTC2025+) or N × (24 + 72) bytes (legacy)]
    [Skill table — M × 68 bytes (EVTC2025+, no count prefix)]
    [Event stream — E × 64 bytes (standard) or E × 56 bytes (events-optimized)]
```

---

## 3. Header (24 bytes)

| Offset | Size | Type   | Field           |
|--------|------|--------|-----------------|
| 0      | 4    | `4s`   | Magic (`EVTC`)  |
| 4      | 8    | `8s`   | Build version (ASCII `yyyymmdd`) |
| 12     | 1    | `B`    | Unused          |
| 13     | 2    | `H`    | Encounter ID    |
| 14     | 1    | `B`    | Unused          |
| 15     | 4    | `I`    | Agent count     |
| 19     | 4    | `I`    | Skill count     |

**Legacy difference**: the legacy header is 25 bytes (includes a trailing `I`
language field at offset 20). EVTC2025+ eliminates it.

**Struct format**: `"<4s8sBHBII"` (24 bytes)

---

## 4. Agent Table

### EVTC2025+ Layout (96 bytes per record)

| Offset | Size  | Type   | Field              |
|--------|-------|--------|--------------------|
| 0      | 4     | `I`    | Agent ID (uint32)  |
| 4      | 4     | `I`    | Profession         |
| 8      | 4     | `I`    | Elite spec         |
| 12     | 4     | `I`    | Unknown            |
| 16     | 4     | `I`    | Unknown            |
| 20     | 4     | `I`    | Unknown            |
| 24     | 64    | `64s`  | Name (null-padded) |
| 88     | 4     | `I`    | Unknown            |
| 92     | 4     | `I`    | Event address (uint32) |

**Key difference from legacy**: the agent ID is a **uint32** (`addr` field),
NOT uint64. The event address at byte +92 replaces the legacy per-agent event
pointer derived from `agent_id`.

**Struct format**: `"<IIIIII64sII"` (96 bytes)

### Legacy Layout (96 bytes per record)

| Offset | Size  | Type   | Field              |
|--------|-------|--------|--------------------|
| 0      | 8     | `Q`    | Agent ID (uint64)  |
| 8      | 4     | `I`    | Profession         |
| 12     | 4     | `I`    | Elite spec         |
| 16     | 2     | `h`    | Unknown            |
| 18     | 2     | `h`    | Unknown            |
| 20     | 2     | `h`    | Unknown            |
| 22     | 2     | `h`    | Unknown            |
| 24     | 72    | `72s`  | Name (null-padded) |

**Struct format**: `"<QIIhhhh72s"` (96 bytes)

---

## 5. Skill Table

### EVTC2025+ Layout (68 bytes per record, NO count prefix)

| Offset | Size  | Type   | Field              |
|--------|-------|--------|--------------------|
| 0      | 4     | `I`    | Skill ID (uint32)  |
| 4      | 64    | `64s`  | Name (null-padded) |

The skill table has **no leading count prefix** in EVTC2025+. Records are
consecutive 68-byte blocks. The parser determines the skill count from the
header and reads `skill_count × 68` bytes.

**Struct format**: `"<I64s"` (68 bytes)

### Legacy Layout (variable-size records)

| Offset | Size  | Type   | Field              |
|--------|-------|--------|--------------------|
| 0      | 4     | `I`    | Skill ID           |
| 4      | 4     | `I`    | Name length (bytes)|
| 8      | N     | `Ns`   | Name + NUL         |

Records are variable-size (8 + name_len bytes). Preceded by a `uint32` count
prefix.

### Detection Heuristic

`_detect_skill_format` reads the 4 bytes after the agent table. If those 4 bytes
form a count value consistent with the space between the agent table end and the
event stream start, the legacy format (with count prefix) is assumed. Otherwise
EVTC2025+ (no prefix, fixed 68-byte records) is used.

---

## 6. Event Stream

### Standard Event (64 bytes)

| Offset | Size  | Type   | Field               |
|--------|-------|--------|---------------------|
| 0      | 8     | `Q`    | Time (ms)           |
| 8      | 8     | `Q`    | Source agent ID     |
| 16     | 8     | `Q`    | Target agent ID     |
| 24     | 4     | `i`    | Value (damage/heal) |
| 28     | 4     | `i`    | Buff damage         |
| 32     | 4     | `I`    | Overstack value     |
| 36     | 4     | `I`    | Skill ID            |
| 40     | 2     | `H`    | Buff ID             |
| 42     | 2     | `H`    | Result              |
| 44     | 2     | `H`    | Activation          |
| 46     | 2     | `H`    | Is statechange      |
| 48     | 16    | `16B`  | Padding / flags     |

**Struct format**: `"<QQQiiIIHHHH16B"` (64 bytes)

### Events-Optimized Layout (56 bytes)

A denser encoding used when `is_statechange == 0` and the result byte is
0 (standard damage/heal events). Fields are packed more tightly.

| Offset | Size  | Type   | Field               |
|--------|-------|--------|---------------------|
| 0      | 8     | `Q`    | Time (ms)           |
| 8      | 8     | `Q`    | Source agent ID     |
| 16     | 8     | `Q`    | Target agent ID     |
| 24     | 4     | `i`    | Value               |
| 28     | 4     |       | Padding             |
| 32     | 4     | `I`    | Overstack value     |
| 36     | 4     |       | Padding             |
| 40     | 1     | `b`    | Buff ID             |
| 41     | 1     | `b`    | Result              |
| 42     | 1     | `b`    | Activation          |
| 43     | 1     |       | Padding             |
| 44     | 1     | `b`    | Is statechange      |
| 45     | 4     |       | Padding             |
| 49     | 1     | `b`    | Is buff remove      |
| 50     | 6     |       | Padding             |

**Struct format**: `"<QQQii 4x I 8x bbbx b 3x b 7x"` (56 bytes)

### Legacy Event (64 bytes)

| Offset | Size  | Type   | Field               |
|--------|-------|--------|---------------------|
| 0      | 8     | `Q`    | Time (ms)           |
| 8      | 8     | `Q`    | Source agent ID     |
| 16     | 8     | `Q`    | Target agent ID     |
| 24     | 4     | `i`    | Value               |
| 28     | 4     |       | Padding             |
| 32     | 4     | `I`    | Overstack value     |
| 36     | 4     |       | Padding             |
| 40     | 1     | `b`    | Buff ID             |
| 41     | 1     | `b`    | Result              |
| 42     | 1     | `b`    | Activation          |
| 43     | 1     | `b`    | Is statechange      |
| 44     | 1     | `b`    | Is flanking         |
| 45     | 1     | `b`    | Is shields          |
| 46     | 1     | `b`    | Is offcycle         |
| 47     | 1     | `b`    | Padding             |
| 48     | 4     | `I`    | Padding             |
| 52     | 4     | `I`    | Padding             |
| 56     | 1     | `b`    | Is buff remove      |
| 57     | 1     | `b`    | Padding             |
| 58     | 6     |       | Padding             |

**Struct format**: `"<QQQii 4x I 7x bbb 2x b 11x"` (64 bytes)

---

## 7. State Change Events

Events with `is_statechange != 0` carry additional semantic meaning. The
`statechange_dispatch.py` module maps state change byte values to event types:

| Byte | Event            |
|------|------------------|
| 4    | DeathEvent       |
| 5    | DownEvent        |
| 18   | BuffApplyEvent   |
| 19   | PositionEvent    |

State changes are parsed identically in both legacy and EVTC2025+ layouts;
the struct differences only affect the byte-level packing.

---

## 8. Key Architectural Decisions

1. **Agent ID truncation**: EVTC2025+ agents use uint32 IDs. The legacy uint64
   IDs are NOT forward-compatible — values ≥ 2³² will overflow in the 2025+
   layout. The parser handles this by using the legacy format for any build
   string with a non-digit suffix (e.g. hex-derived suffixes from test fixtures).

2. **Event interleaving**: Standard and events-optimized structs may be
   interleaved within a single stream. The parser detects the variant per-event
   based on `is_statechange` and `result` byte values.

3. **No skill count prefix**: The skill table in EVTC2025+ omits the legacy
   `uint32` count prefix. The parser reads `header.skill_count × 68` bytes
   directly, falling back to legacy detection when the byte after the agent
   table looks like a valid count value.

---

## 9. Implementation Reference

- `libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py` — main parser
- `libs/gw2_evtc_parser/src/gw2_evtc_parser/statechange_dispatch.py` — state change dispatch
- `libs/gw2_core/src/gw2_core/models.py` — Pydantic event models

---
*Last updated: 2026-07-21 — based on parser v0.6.0*
