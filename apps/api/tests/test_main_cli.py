"""Tests for the ``python -m gw2analytics_api`` CLI entrypoint.

Targets __main__.py (0% coverage, 7 lines, P3 from COVERAGE-90-PLAN).
"""

from __future__ import annotations

from unittest.mock import patch


def test_main_calls_uvicorn() -> None:
    """``main()`` invokes ``uvicorn.run()`` with the app and host/port."""
    with patch("uvicorn.run") as mock_run:
        from gw2analytics_api.__main__ import main

        main()
        mock_run.assert_called_once()
        call_args, call_kwargs = mock_run.call_args
        # First positional arg should be the FastAPI app
        assert call_args[0] is not None
        assert call_kwargs.get("host") == "127.0.0.1"
        assert call_kwargs.get("port") == 8000
