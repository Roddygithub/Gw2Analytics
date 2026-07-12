# Plan 031 — CHANGELOG pre-existing duplicate removal

**Stamped at:** `5cfd962` (origin/main HEAD at audit time)
**Severity:** LOW (documentation hygiene)
**Category:** docs, DRY
**Addresses finding:** The surgical repair at commit `7117564` (Phase B round 4) deliberately scoped to just the 3 misplaced v0.10.x sections. The 5 pre-existing duplicate sections (lines 3925 / 4025 / 4100 / 3906 / 4200 for `[0.5.0-web]` × 2 / `[0.5.0-parser]` × 2 / `[0.1.0]` × 2 / `[0.4.0]` misplaced / `[0.2.0]` misplaced) were intentionally left intact per the Scope decision.

---

## Finding

Evidence from `grep -nE '^## \[' CHANGELOG.md`:

| Line | Section | Status |
|------|---------|--------|
| 3035 | `## [0.5.0-web]` | First occurrence (correct) |
| 3135 | `## [0.5.0-parser]` | First occurrence (correct) |
| 3873 | `## [0.1.0]` — gw2_api_client | First occurrence (correct) |
| 3961 | `## [0.4.0]` — Phase 1 parser | **Misplaced** (should be earlier in the file) |
| 3980 | `## [0.5.0-web]` | **Duplicate** of line 3035 |
| 4080 | `## [0.5.0-parser]` | **Duplicate** of line 3135 |
| 4155 | `## [0.1.0]` — Phase 3 analytics | **Duplicate** of line 3873 (different content; both are valid `0.1.0` sections for different components) |
| 4200 | `## [0.2.0]` — Phase 3 depth | **Misplaced** (should be earlier in the file) |

The 5 duplicate/misplaced sections are at the BOTTOM of the file (lines 3961–4256), appended after the original chronological ordering was established.

---

## Fix

### Option B: Python script with `splitlines(keepends=True)` + CUT + INSERT

Same pattern as commit `7117564`:

```python
#!/usr/bin/env python3
"""Remove 5 duplicate/misplaced sections from CHANGELOG.md."""

from pathlib import Path

changelog = Path("CHANGELOG.md")
lines = changelog.read_text().splitlines(keepends=True)

# Identify the line ranges to remove (0-indexed)
# [0.5.0-web] duplicate: lines 3980-4079 (3980 is 1-indexed → 3979 0-indexed)
# [0.5.0-parser] duplicate: lines 4080-4154 (4079 0-indexed → 4153)
# [0.1.0] Phase 3 duplicate: lines 4155-4199 (4154 0-indexed → 4198)
# [0.4.0] misplaced: lines 3961-3979 (3960 0-indexed → 3978)
# [0.2.0] misplaced: lines 4200-4256 (4199 0-indexed → end)

# Cut ranges (1-indexed, inclusive start, exclusive end):
cuts = [
    (3961, 3980),   # [0.4.0] misplaced
    (3980, 4080),   # [0.5.0-web] duplicate
    (4080, 4155),   # [0.5.0-parser] duplicate
    (4155, 4200),   # [0.1.0] Phase 3 duplicate
    (4200, len(lines) + 1),  # [0.2.0] misplaced
]

# Build the output: keep everything NOT in the cut ranges
keep = []
cut_set = set()
for start, end in cuts:
    for i in range(start - 1, end - 1):
        cut_set.add(i)

for i, line in enumerate(lines):
    if i not in cut_set:
        keep.append(line)

changelog.write_text("".join(keep))
print(f"Removed {len(cut_set)} lines; new total: {len(keep)}")
```

### Step 1 — Run the dedup script

```bash
python3 scripts/dedup_changelog.py  # or inline the script
```

### Step 2 — Verify the sections are gone

```bash
grep -nE '^## \[0\.(1\.0|2\.0|4\.0|5\.0)\]' CHANGELOG.md
```

Should show only the first occurrences (lines ~3035, ~3135, ~3873).

### Step 3 — Commit

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): remove 5 pre-existing duplicate sections (plan 031)"
```

---

## Tests

- `grep -cE '^## \[' CHANGELOG.md` — the count should decrease by 4 (5 removed, but `[0.1.0]` has 2 legitimate entries for different components → 1 duplicate removed net).
- `wc -l CHANGELOG.md` — should be ~4256 - ~295 = ~3961 lines.
- Visual inspection: the remaining sections are in correct chronological order.

---

## Rejected alternatives

- **Manually delete each duplicate**: error-prone for 295 lines. The Python script is surgical and verifiable.
- **Regenerate the entire CHANGELOG from git log**: would lose the hand-written notes and formatting. The surgical approach preserves the curated content.
- **Merge the `[0.1.0]` duplicates into one section**: they are legitimately different components (gw2_api_client vs gw2_analytics). Keep both but ensure they're in chronological order.

---

## Dependency graph

- **Standalone.** No plan depends on this one; this plan doesn't depend on any.

---

## Notes for executors

- The cut ranges must be verified against the actual line numbers before running. Use `grep -n` to confirm.
- The `[0.4.0]` and `[0.2.0]` sections at the bottom are MISPLACED (they belong earlier in the file chronologically). The dedup removes them from the bottom; a future pass could re-insert them in the correct position, but that's out of scope for this plan.
- This is the cheap close-out for the audit cycle. LOW priority; can ship in any cycle.
