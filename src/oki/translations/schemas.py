from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from oki.translations.enums import ApprovalStatus, QaDimension, TranslationStatus


class TranslationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_id: UUID
    project_id: UUID
    asset_id: UUID
    source_language: str
    target_language: str
    status: TranslationStatus
    created_at: datetime
    updated_at: datetime
    version: int


class TranslationSegmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    translation_id: UUID
    source_segment_id: UUID | None
    sequence_number: int
    source_text: str
    translated_text: str | None
    start_time: float | None
    end_time: float | None
    status: TranslationStatus
    created_at: datetime
    updated_at: datetime


class QaResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    translation_id: UUID
    dimension: QaDimension
    score: int
    comment: str | None
    reviewer_id: UUID
    reviewed_at: datetime
    created_at: datetime


class TranslationStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    target_language: str = Field(min_length=2, max_length=16)
    source_language: str = Field(default="en", min_length=2, max_length=16)


class TranslationSegmentReviseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_text: str = Field(min_length=1)
    reason: str | None = Field(default=None, max_length=4000)
