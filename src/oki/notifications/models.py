from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String, Text, DateTime, Boolean, Index
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.orm import Mapped, mapped_column

from oki.db.base import Base


class NotificationChannel(str, Enum):
    EMAIL = "email"
    IN_APP = "in_app"
    TELEGRAM = "telegram"


class NotificationStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(index=True)
    channel: Mapped[str] = mapped_column(
        PGEnum(NotificationChannel, name="notificationchannel"),
        default=NotificationChannel.IN_APP,
    )
    status: Mapped[str] = mapped_column(
        PGEnum(NotificationStatus, name="notificationstatus"),
        default=NotificationStatus.PENDING,
    )
    subject: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    send_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("ix_notifications_user_id_created_at", "user_id", "created_at"),
    )
