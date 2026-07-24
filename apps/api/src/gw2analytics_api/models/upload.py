from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gw2analytics_api.models.fight import OrmFight

from sqlalchemy import BigInteger, CheckConstraint, DateTime, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from gw2analytics_api.database import Base, utcnow

UPLOAD_STATUS_PENDING = "pending"
UPLOAD_STATUS_COMPLETED = "completed"
UPLOAD_STATUS_FAILED = "failed"


class Upload(Base):
    __tablename__ = "uploads"

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'completed', 'failed')",
            name="ck_uploads_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(50), default=UPLOAD_STATUS_PENDING, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    parser_version: Mapped[str] = mapped_column(String(64), default="0", nullable=False)

    fight: Mapped[OrmFight | None] = relationship(
        back_populates="upload",
        uselist=False,
        cascade="all, delete-orphan",
    )
