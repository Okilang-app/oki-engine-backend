from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from oki.shorts.enums import ShortStatus


class GenerateShortsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: UUID


class ShortCandidateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    job_id: UUID
    status: ShortStatus
    source_timestamps: list[tuple[float, float]]
    detected_hooks: dict
    raw_score: float | None
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime


class ShortVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    candidate_id: UUID
    version_number: int
    crop_params: dict
    refinement_prompt: str | None
    revised_media_url: str | None
    created_at: datetime
