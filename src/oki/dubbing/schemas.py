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


class DubSegmentListResponse(BaseModel):
    job_id: UUID
    segments: list[DubSegmentResponse]


class DubbingStartRequest(BaseModel):
    voice_profile_id: UUID | None = None
    target_language: str | None = None


class DubbingStartResponse(BaseModel):
    job_id: UUID
    organization_id: UUID
    total_segments: int
    pending_segments: int
    completed_segments: int
    failed_segments: int
    status: str
    voice_profile_id: UUID | None = None
    target_language: str | None = None
    segments: list[DubSegmentResponse] = []


class DubRegenerateRequest(BaseModel):
    voice_profile_id: UUID | None = None


class DubReviewRequest(BaseModel):
    approved: bool
    reason: str | None = None


class DubPlaybackResponse(BaseModel):
    segment_id: UUID
    playback_url: str


class DubCancelResponse(BaseModel):
    job_id: UUID
    cancelled_segments: int
    cancelled_attempts: int
    status: str
