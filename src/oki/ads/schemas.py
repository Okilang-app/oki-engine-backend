"""Ad Pydantic schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AdCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=255)
    # An ad with a blank key registers fine but blows up at render time, when
    # the renderer tries to fetch it from S3. Reject it at the door instead.
    storage_key: str = Field(..., min_length=1, max_length=1024)
    duration_seconds: int | None = Field(default=None, ge=0)


class AdResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    name: str
    storage_key: str
    duration_seconds: int | None
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime
