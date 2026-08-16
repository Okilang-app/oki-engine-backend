from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    creator_id: str | None
    agreement_id: str | None
    title: str
    target_language: str | None
    workflow_state: str
    created_at: datetime
