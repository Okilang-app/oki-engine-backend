from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class OAuthCallbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    state: str


class ChannelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    connection_id: UUID
    platform_channel_id: str
    channel_title: str
    upload_defaults: dict[str, Any]
    is_active: bool
    linked_at: datetime
