from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from oki.sponsors.enums import DetectionReason, ReplacementType, SponsorStatus


class SponsorCandidateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_id: UUID
    asset_id: UUID
    start_time: float
    end_time: float
    sponsor_name: str | None
    status: SponsorStatus
    detection_reason: DetectionReason | None
    confidence: float | None
    replacement_type: ReplacementType | None = None
    proposed_replacement_ad_id: UUID | None = None
    proposed_replacement_ad_name: str | None = None
    created_at: datetime
    updated_at: datetime


class SponsorReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    boundaries_start: float | None = None
    boundaries_end: float | None = None
    replacement_type: ReplacementType | None = None
    ad_id: UUID | None = None
    reason: str | None = Field(default=None, max_length=4000)


class SponsorDecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    ad_segment_id: UUID
    decision: str
    boundaries_start: float | None
    boundaries_end: float | None
    reason: str | None
    reviewed_by_user_id: UUID
    reviewed_at: datetime
    created_at: datetime


class ManualSponsorCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_time: float = Field(..., ge=0)
    end_time: float = Field(..., ge=0)
    sponsor_name: str | None = Field(default=None, max_length=255)
    replacement_type: ReplacementType | None = None


class ManualSponsorUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_time: float | None = Field(default=None, ge=0)
    end_time: float | None = Field(default=None, ge=0)
    sponsor_name: str | None = Field(default=None, max_length=255)
    replacement_type: ReplacementType | None = None


class SponsorListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    candidates: list[SponsorCandidateResponse]
