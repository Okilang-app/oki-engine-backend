from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from oki.publications.enums import PublicationMode, PublicationStatus


class PublicationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    mode: PublicationMode = PublicationMode.CREATOR_CHANNEL_LOCALIZATION


class UploadPrivateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PublicationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    job_id: UUID
    channel_id: UUID | None
    status: PublicationStatus
    mode: PublicationMode
    video_id: str | None
    private_video_id: str | None
    scheduled_at: datetime | None
    published_at: datetime | None
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime
