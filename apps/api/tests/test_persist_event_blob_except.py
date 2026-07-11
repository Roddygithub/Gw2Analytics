"""v0.9.5 plan 019: _persist_event_blob except-narrowing regression tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from minio.error import S3Error

from gw2analytics_api.services.event_blob import _persist_event_blob


class _FakeUpload:
    id = "up-123"


def _make_s3_error() -> S3Error:
    response = MagicMock()
    return S3Error(response, "InternalError", "minio down", "resource", "request-1", "host-1")


def test_s3_error_is_swallowed_with_warning_log(monkeypatch: pytest.MonkeyPatch) -> None:
    """Genuine S3Error: blob stays NULL + log is WARNING-level."""

    def fake_put_events(fight_id: str, gz_bytes: bytes) -> str:
        raise _make_s3_error()

    def fake_parse_events(_self: object, evtc_bytes: bytes) -> list[object]:
        return [MagicMock(model_dump_json=lambda: "{}")]

    monkeypatch.setattr("gw2analytics_api.services.event_blob.put_events", fake_put_events)
    monkeypatch.setattr(
        "gw2analytics_api.services.event_blob.PythonEvtcParser.parse_events",
        fake_parse_events,
    )
    with patch("gw2analytics_api.services.event_blob.logger") as mock_log:
        _persist_event_blob(
            db=None,  # type: ignore[arg-type]
            upload=_FakeUpload(),  # type: ignore[arg-type]
            evtc_bytes=b"...",
            fight_id="FIGHT",
        )

    mock_log.exception.assert_called_once()


def test_attribute_error_propagates_to_caller() -> None:
    """Programming bug (AttributeError) is NOT swallowed; propagates UP."""

    def fake_parse_events(_self: object, evtc_bytes: bytes) -> list[object]:
        raise AttributeError("'NoneType' object has no attribute 'foo'")

    with (
        patch(
            "gw2analytics_api.services.event_blob.PythonEvtcParser.parse_events",
            fake_parse_events,
        ),
        pytest.raises(AttributeError),
    ):
        _persist_event_blob(
            db=None,  # type: ignore[arg-type]
            upload=_FakeUpload(),  # type: ignore[arg-type]
            evtc_bytes=b"...",
            fight_id="FIGHT",
        )
