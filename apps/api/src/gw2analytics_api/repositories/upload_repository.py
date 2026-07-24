"""Repository for ``Upload`` model."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from gw2analytics_api.models import Upload

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.orm import Session


__all__ = ["UploadRepository"]


class UploadRepository:
    """All DB access for uploads."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ── getters ──────────────────────────────────────────────

    def get_by_id(self, upload_id: UUID) -> Upload | None:
        return self._session.get(Upload, upload_id)

    def find_by_sha256(self, sha256: str) -> Upload | None:
        return self._session.execute(
            select(Upload).where(Upload.sha256 == sha256),
        ).scalar_one_or_none()

    # ── save ─────────────────────────────────────────────────

    def add(self, upload: Upload) -> None:
        self._session.add(upload)

    def flush(self) -> None:
        self._session.flush()

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()
