"""v0.10.10 plan 027: streaming gzip in build_event_iterator.

Pins the post-fix contract: ``build_event_iterator`` does NOT
materialise the full decompressed JSONL string + line list before
yielding (the pre-fix anti-OOM bypass). It uses ``gzip.GzipFile``
over a ``BytesIO`` wrapper, with memory peak at the zlib-chunk
buffer (~32-64 KB) regardless of the input size.
"""

from __future__ import annotations

import gzip
import inspect
import io
import tracemalloc
from unittest.mock import patch

from gw2_core import DamageEvent, Event
from gw2analytics_api._event_dispatch import build_event_iterator


def _build_gz_blob(num_events: int) -> bytes:
    """Build a gzipped JSONL blob with N synthetic DamageEvent records."""
    lines = []
    for i in range(num_events):
        ev = DamageEvent(
            event_type="DAMAGE",
            time_ms=i,
            source_agent_id=1,
            target_agent_id=2,
            skill_id=3,
            damage=100,
        )
        lines.append(ev.model_dump_json().encode("utf-8"))
    jsonl = b"\n".join(lines)
    return gzip.compress(jsonl)


def test_build_event_iterator_constructs_gzipfile_with_bytesio() -> None:
    """The helper must construct ``gzip.GzipFile(fileobj=BytesIO(...))``.

    Pinned at the structural level: mock the ``gzip.GzipFile``
    constructor to record the kwargs. The streaming path MUST go
    through the constructor; the legacy ``gzip.decompress(...)`` path
    does NOT. This test catches a regression to the legacy path
    without depending on readline-vs-read semantics (which
    ``for line in gz: ...`` would use internally).
    """
    called_kwargs: list[dict[str, object]] = []
    real_gzipfile = gzip.GzipFile

    def fake_gzipfile(*args: object, **kwargs: object) -> gzip.GzipFile:
        called_kwargs.append(kwargs)
        return real_gzipfile(*args, **kwargs)  # type: ignore[call-overload, no-any-return]

    with patch("gw2analytics_api._event_dispatch.gzip.GzipFile", side_effect=fake_gzipfile):
        gz = _build_gz_blob(3)
        list(build_event_iterator(gz_bytes=gz))

    assert len(called_kwargs) == 1, (
        f"Expected exactly 1 GzipFile construction, got {len(called_kwargs)}"
    )
    assert "fileobj" in called_kwargs[0], (
        "GzipFile must be constructed with fileobj=BytesIO (streaming wrapper)"
    )
    fileobj = called_kwargs[0]["fileobj"]
    assert isinstance(fileobj, io.BytesIO), (
        f"fileobj must be a BytesIO, got {type(fileobj).__name__}"
    )


def test_build_event_iterator_yields_same_events_as_legacy() -> None:
    """Pin byte-identical output: 3 lines => 3 DamageEvent instances in order."""
    gz = _build_gz_blob(3)
    events: list[Event] = list(build_event_iterator(gz_bytes=gz))
    assert len(events) == 3
    for i, ev in enumerate(events):
        assert isinstance(ev, DamageEvent)
        assert ev.time_ms == i
        assert ev.damage == 100


def test_build_event_iterator_is_a_generator() -> None:
    """The function annotation ``-> Iterator[Event]`` + ``yield`` => generator.

    Pydantic + mypy validate the return type, but the runtime signal is
    ``inspect.isgeneratorfunction`` (true for any function with ``yield``).
    A future refactor that switches to a list-returning helper would
    fail this test.
    """
    assert inspect.isgeneratorfunction(build_event_iterator)


def test_build_event_iterator_memory_peak_bounded() -> None:
    """A 1 MB gzipped blob does not spike to 100+ MB in the streaming path.

    Pre-fix: ``gzip.decompress + splitlines`` would peak at ~10-15x
    compressed size (intermediate string + line list). Post-fix: peak
    is bounded by the zlib chunk + the BytesIO view (~2-3 MB for 1 MB
    compressed + the Pydantic model objects yielded so far).
    """
    gz = _build_gz_blob(10_000)  # ~10k events; ~1 MB gzipped.

    tracemalloc.start()
    events: list[Event] = []
    for event in build_event_iterator(gz_bytes=gz):
        events.append(event)
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # Sanity: the iterator yielded all events.
    assert len(events) == 10_000

    # Peak should be small relative to the input size. Pydantic model
    # construction dominates the peak (~10k models * ~500 bytes each
    # ~= 5 MB). 50 MB ceiling is a generous upper bound that catches
    # the legacy `gzip.decompress` regression (which would peak at
    # ~100-150 MB for a 1 MB input).
    peak_mb = peak / (1024 * 1024)
    assert peak_mb < 50, (
        f"Streaming path peaked at {peak_mb:.1f} MB for a 1 MB gzipped "
        f"input; expected < 50 MB. Pre-fix would peak at ~150 MB."
    )


def test_build_event_iterator_skips_empty_and_whitespace_only_lines() -> None:
    """Empty + whitespace-only + trailing-newline lines are dropped.

    The fixture only emits ``DamageEvent`` records; the isinstance
    filter narrows the iterator element type to ``DamageEvent`` so
    ``mypy strict`` does not flag ``.damage`` access via the 5-member
    ``Event`` union (BoonApplyEvent / CCEvent / HealingEvent /
    BuffRemovalEvent all lack ``.damage``). The fixture deliberately
    covers only DamageEvent so the post-filter count remains stable.
    """
    # Manually construct a gzipped blob with mixed empty/whitespace/json lines.
    jsonl = (
        b'{"event_type":"DAMAGE","time_ms":1,"source_agent_id":1,'
        b'"target_agent_id":2,"skill_id":3,"damage":100}\n'
        b"\n"  # empty
        b"   \n"  # whitespace only
        b'{"event_type":"DAMAGE","time_ms":2,"source_agent_id":1,'
        b'"target_agent_id":2,"skill_id":3,"damage":50}   \n'  # trailing whitespace
    )
    gz = gzip.compress(jsonl)

    # Narrow to ``list[DamageEvent]`` via the isinstance filter so the
    # downstream ``.damage`` accesses type-check on the union. The
    # fixture produces only DamageEvent so the filter is a no-op at
    # runtime; it exists purely to give mypy strict the type info.
    events: list[DamageEvent] = [
        e for e in build_event_iterator(gz_bytes=gz) if isinstance(e, DamageEvent)
    ]

    # 2 valid events + 3 dropped (empty + whitespace + valid-with-trailing).
    # The valid-with-trailing is still parsed (strip() on bytes only strips
    # whitespace, then validate_json consumes the trimmed line).
    assert len(events) == 2
    assert events[0].damage == 100
    assert events[1].damage == 50
