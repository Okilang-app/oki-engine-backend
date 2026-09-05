from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from oki.notifications.models import NotificationChannel, NotificationStatus


class NotificationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    user_id: UUID | None = None
    channel: NotificationChannel = NotificationChannel.IN_APP
    subject: str
    body: str
    send_at: datetime | None = None


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    user_id: UUID | None
    channel: NotificationChannel
    status: NotificationStatus
    subject: str
    body: str
    send_at: datetime | None
    sent_at: datetime | None
    read_at: datetime | None
    error_message: str | None
    created_at: datetime


class NotificationListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[NotificationResponse]
    total: int
