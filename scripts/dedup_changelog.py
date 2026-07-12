#!/usr/bin/env python3
"""Remove 5 duplicate/misplaced sections from CHANGELOG.md.

Pattern: splitlines(keepends=True) + CUT ranges + rebuild.
Same approach as commit 7117564 (Phase B round 4).
"""

from __future__ import annotations

import re
from pathlib import Path


def main() -> int:
    changelog = Path("CHANGELOG.md")
    lines = changelog.read_text().splitlines(keepends=True)
    total_before = len(lines)

    # Find all ## [version] headers with their line numbers (1-indexed)
    headers: list[tuple[int, str]] = []
    for i, line in enumerate(lines, 1):
        if re.match(r"^## \[", line):
            headers.append((i, line.strip()))

    # Identify the 5 sections to remove (1-indexed line numbers, inclusive start)
    # These are the duplicate/misplaced sections at the BOTTOM of the file:
    #
    # Line 3961: ## [0.4.0] - Phase 1 parser misplaced (should be earlier)
    # Line 3980: ## [0.5.0-web] duplicate of line 3035
    # Line 4080: ## [0.5.0-parser] duplicate of line 3135
    # Line 4155: ## [0.1.0] - Phase 3 analytics duplicate of line 3873
    # Line 4200: ## [0.2.0] - Phase 3 depth misplaced (should be earlier)

    # Verify expected headers exist at expected lines
    header_map = dict(headers)
    expected = {
        3961: "[0.4.0]",
        3980: "[0.5.0-web]",
        4080: "[0.5.0-parser]",
        4155: "[0.1.0]",
        4200: "[0.2.0]",
    }
    for line_no, prefix in expected.items():
        actual = header_map.get(line_no)
        if actual is None or prefix not in actual:
            msg = f"Expected {prefix} at line {line_no}, got {actual}"
            raise ValueError(msg)

    # Build cut ranges (1-indexed, inclusive start, exclusive end)
    # Each section runs from its header line to the line BEFORE the next header
    # (or end of file for the last section)
    cut_starts = [3961, 3980, 4080, 4155, 4200]
    cut_ranges: list[tuple[int, int]] = []
    for idx, start in enumerate(cut_starts):
        end = cut_starts[idx + 1] if idx + 1 < len(cut_starts) else total_before + 1
        cut_ranges.append((start, end))

    # Build set of 0-indexed lines to remove
    cut_set: set[int] = set()
    for start, end in cut_ranges:
        for i in range(start - 1, end - 1):
            cut_set.add(i)

    # Keep lines NOT in cut_set
    kept = [line for i, line in enumerate(lines) if i not in cut_set]
    changelog.write_text("".join(kept))

    removed = len(cut_set)
    print(f"Removed {removed} lines ({total_before} -> {len(kept)})")
    print(f"Cut ranges: {cut_ranges}")

    # Verify: count remaining ## [version] headers
    remaining = sum(1 for line in kept if re.match(r"^## \[", line))
    print(f"Remaining version headers: {remaining} (was {len(headers)})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
