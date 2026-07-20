"""Parser performance benchmarks against real WvW .zevtc files.

Measures parse time for real arcdps WvW combat logs of different sizes
and asserts they complete within reasonable time budgets.

File sizes (compressed .zevtc → decompressed EVTC bytes, event count):
  - ``20250928-230925.zevtc``    ~28 KB  →   ~150-300 KB EVTC   (577 events)
  - ``20251206-003232.zevtc``    ~657 KB →   ~3-5 MB EVTC       (many events)
  - ``20251206-005550.zevtc``    ~2.7 MB →   ~12-18 MB EVTC     (very large)

The 1-second threshold for the 28 KB file is generous (real parsing takes
<100 ms on a dev machine) so CI agents with slower CPUs don't flake.
The 5-second threshold for large files accommodates the 2.7 MB fixture
(~200-400 ms measured on a dev machine).
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from gw2_evtc_parser import PythonEvtcParser, read_zevtc_archive

#: Root directory containing all WvW log subdirectories.
WVW_DIR = Path("/home/roddy/Projects/WvW/WvW (1)")

#: (relative_path, label, event_count_floor, time_limit_s)
FIXTURES: list[tuple[str, str, int, float]] = [
    (
        "Ess Kitable/20250928-230925.zevtc",
        "28 KB (577 ev)",
        100,
        1.0,
    ),
    (
        "Ber Zerk Er/20251206-003232.zevtc",
        "657 KB large",
        1_000,
        5.0,
    ),
    (
        "Ber Zerk Er/20251206-005550.zevtc",
        "2.7 MB very large",
        5_000,
        5.0,
    ),
]


def _load_and_decompress(path: str) -> bytes:
    """Read and decompress a .zevtc archive, returning raw EVTC bytes."""
    full_path = WVW_DIR / path
    if not full_path.exists():
        pytest.skip(f"Fixture {path!r} not found at {full_path}")
    return read_zevtc_archive(full_path)


class TestParserPerformance:
    """Benchmark the parser's hot loop against real WvW .zevtc files."""

    @pytest.mark.parametrize(
        ("rel_path", "label", "event_floor", "limit_s"),
        FIXTURES,
        ids=[f[0].rsplit("/", 1)[-1] for f in FIXTURES],
    )
    def test_parse_time_under_threshold(
        self, rel_path: str, label: str, event_floor: int, limit_s: float
    ) -> None:
        """Parsing a WvW .zevtc file completes within its time budget."""
        raw_evtc = _load_and_decompress(rel_path)
        parser = PythonEvtcParser()

        t0 = time.perf_counter()
        events = list(parser.parse_events(raw_evtc))
        elapsed = time.perf_counter() - t0

        compressed = (WVW_DIR / rel_path).stat().st_size
        decompressed = len(raw_evtc)

        assert elapsed < limit_s, (
            f"Parsing {label} ({rel_path}, "
            f"{compressed / 1024:.0f} KB compressed → "
            f"{decompressed / 1024:.0f} KB decompressed) "
            f"took {elapsed:.3f}s, expected < {limit_s}s"
        )
        assert len(events) >= event_floor, (
            f"Parsing {label} ({rel_path}) yielded {len(events)} events, expected >= {event_floor}"
        )

        print(
            f"\n  [perf] {label}: {compressed / 1024:.0f} KB compressed → "
            f"{decompressed / 1024:.0f} KB decompressed → "
            f"{len(events)} events in {elapsed:.3f}s"
        )

    def test_parse_time_deterministic(self) -> None:
        """Three consecutive parses of the same file take roughly the same time."""
        raw_evtc = _load_and_decompress("Ess Kitable/20250928-230925.zevtc")
        parser = PythonEvtcParser()

        times: list[float] = []
        for _ in range(3):
            t0 = time.perf_counter()
            list(parser.parse_events(raw_evtc))
            times.append(time.perf_counter() - t0)

        fastest = min(times)
        slowest = max(times)
        assert slowest < fastest * 2.0, (
            f"Parse time varied too much across 3 runs: "
            f"{[f'{t:.3f}s' for t in times]} "
            f"(fastest={fastest:.3f}s, slowest={slowest:.3f}s)"
        )

    def test_parse_large_fixture_yields_events(self) -> None:
        """The largest available fixture produces a meaningful event count."""
        raw_evtc = _load_and_decompress("Ber Zerk Er/20251206-005550.zevtc")
        parser = PythonEvtcParser()

        events = list(parser.parse_events(raw_evtc))
        compressed = (WVW_DIR / "Ber Zerk Er/20251206-005550.zevtc").stat().st_size

        print(
            f"\n  [perf] 2.7 MB fixture: {len(events)} events, "
            f"{compressed / 1024:.0f} KB compressed → "
            f"{len(raw_evtc) / 1024:.0f} KB decompressed"
        )
        # A real WvW fight of this size should yield thousands of events.
        assert len(events) >= 5_000, (
            f"Large fixture yielded only {len(events)} events; "
            f"expected >= 5_000 for a 2.7 MB compressed log"
        )
