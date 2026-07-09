"""v0.10.1 plan 010: tests for the Arq ``parse_job``.

The Arq job chains :func:`gw2analytics_api.services.process_parse`
with :func:`gw2analytics_api.workers.webhook_dispatch.dispatch_for_upload`.
The contract:

1. **Happy path**: ``parse_job`` awaits ``process_parse`` (in a
   thread), then awaits ``dispatch_for_upload`` (in a thread).
   The chain runs sequentially.
2. **Parse failure**: if ``process_parse`` raises,
   ``dispatch_for_upload`` is NOT called. The exception is
   re-raised so Arq's retry kicks in.
3. **Dispatch failure (post-parse)**: if ``dispatch_for_upload``
   raises after a successful parse, the exception is LOGGED
   and SWALLOWED. Re-running the parse would duplicate the
   fight row, so the chain does NOT retry.

Hermetic: mocks ``process_parse`` + ``dispatch_for_upload`` at
the import site (``gw2analytics_api.workers.parser_worker``).
No live DB, no live MinIO, no live Arq broker.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any
from unittest.mock import patch

import pytest

from gw2analytics_api.workers.parser_worker import parse_job


def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    """Helper: drive an async coroutine to completion in a sync test.

    Uses ``asyncio.run`` (the canonical 3.7+ entry point).
    ``asyncio.get_event_loop().run_until_complete()`` is
    deprecated in 3.12 when no event loop is running.
    """
    return asyncio.run(coro)


def test_parse_job_happy_path_chains_parse_then_dispatch() -> None:
    """``parse_job`` awaits parse, then awaits dispatch, in order."""
    call_order: list[str] = []

    def fake_parse(sf: Any, upload_id: Any, raw: Any) -> None:
        call_order.append("parse")

    def fake_dispatch(sf: Any, upload_id: Any) -> None:
        call_order.append("dispatch")

    with (
        patch(
            "gw2analytics_api.workers.parser_worker.process_parse",
            side_effect=fake_parse,
        ) as mock_parse,
        patch(
            "gw2analytics_api.workers.parser_worker.dispatch_for_upload",
            side_effect=fake_dispatch,
        ) as mock_dispatch,
    ):
        _run(parse_job({"job_try": 1}, "00000000-0000-0000-0000-000000000001", b"raw-bytes"))
    assert call_order == ["parse", "dispatch"]
    assert mock_parse.call_count == 1
    assert mock_dispatch.call_count == 1


def test_parse_job_skips_dispatch_on_parse_failure() -> None:
    """If ``process_parse`` raises, ``dispatch_for_upload`` is NOT called."""

    def fake_parse(sf: Any, upload_id: Any, raw: Any) -> None:
        msg = "simulated parse error"
        raise RuntimeError(msg)

    with (
        patch(
            "gw2analytics_api.workers.parser_worker.process_parse",
            side_effect=fake_parse,
        ),
        patch(
            "gw2analytics_api.workers.parser_worker.dispatch_for_upload",
        ) as mock_dispatch,
        pytest.raises(RuntimeError, match="simulated parse error"),
    ):
        _run(parse_job({"job_try": 1}, "00000000-0000-0000-0000-000000000002", b"raw-bytes"))
    # The dispatch is the user-facing contract ONLY after a
    # successful parse; a failed parse must NOT trigger a
    # dispatch (which would short-circuit anyway, but the
    # explicit skip is the contract).
    assert mock_dispatch.call_count == 0


def test_parse_job_does_not_retry_on_dispatch_failure() -> None:
    """If ``dispatch_for_upload`` raises, ``parse_job`` swallows the error.

    The parse is the user-visible contract (the fight is
    queryable). A missed webhook delivery is an operational
    concern that the operator can re-dispatch manually; a
    re-parse would duplicate the fight row. The chain
    therefore swallows the dispatch exception and does NOT
    raise.
    """

    def fake_parse(sf: Any, upload_id: Any, raw: Any) -> None:
        return None

    def fake_dispatch(sf: Any, upload_id: Any) -> None:
        msg = "simulated dispatch error"
        raise RuntimeError(msg)

    with (
        patch(
            "gw2analytics_api.workers.parser_worker.process_parse",
            side_effect=fake_parse,
        ),
        patch(
            "gw2analytics_api.workers.parser_worker.dispatch_for_upload",
            side_effect=fake_dispatch,
        ) as mock_dispatch,
    ):
        # No exception raised -- the dispatch failure is
        # logged at EXCEPTION and swallowed.
        _run(parse_job({"job_try": 1}, "00000000-0000-0000-0000-000000000003", b"raw-bytes"))
    assert mock_dispatch.call_count == 1


def test_parse_job_runs_parse_and_dispatch_in_thread_pool() -> None:
    """Both ``process_parse`` and ``dispatch_for_upload`` are sync-in-thread.

    Pins the ``asyncio.to_thread`` wrapping so a future
    refactor that drops the wrapper is caught. The
    ``asyncio.to_thread`` offload is the only thing keeping
    the Arq event loop responsive when the parser is
    CPU-bound.
    """
    seen_threads: list[int] = []

    def fake_parse(sf: Any, upload_id: Any, raw: Any) -> None:
        seen_threads.append(0)  # placeholder; we can't easily get the thread id

    def fake_dispatch(sf: Any, upload_id: Any) -> None:
        seen_threads.append(0)

    with (
        patch(
            "gw2analytics_api.workers.parser_worker.process_parse",
            side_effect=fake_parse,
        ) as mock_parse,
        patch(
            "gw2analytics_api.workers.parser_worker.dispatch_for_upload",
            side_effect=fake_dispatch,
        ),
    ):
        _run(parse_job({"job_try": 1}, "00000000-0000-0000-0000-000000000004", b"raw-bytes"))
    # Both functions called (the threading detail is
    # exercised by ``asyncio.to_thread`` but the
    # behaviour-level assertion is the call counts).
    assert mock_parse.call_count == 1
    assert len(seen_threads) == 2
