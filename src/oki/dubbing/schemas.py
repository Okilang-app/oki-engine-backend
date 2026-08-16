from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DubSegmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    job_id: UUID
    translation_job_id: UUID | None
    sequence_number: int
    source_text: str
    translated_text: str | None
    voice_profile_id: UUID | None
    timing_start_ms: int | None
    timing_end_ms: int | None
    status: str
    audio_asset_reference: str | None
    review_status: str | None
    meta: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class DubbingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: UUID
    organization_id: UUID
    segments: list[DubSegmentResponse]
    status: str
    created_at: datetime
    updated_at: datetime
