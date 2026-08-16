from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from oki.analysis.enums import AnalysisStatus, SegmentType


class TimelineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_time: float
    end_time: float
    type: str = Field(description="Type of timeline item: segment, scene, ocr, audio_region, safety_label")
    label: str
    data: dict = Field(default_factory=dict)


class WordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    segment_id: UUID
    start_time: float
    end_time: float
    text: str
    confidence: float | None


class TranscriptSegmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    asset_id: UUID
    job_id: UUID
    speaker_id: UUID | None
    start_time: float
    end_time: float
    text: str
    language_code: str
    segment_type: SegmentType
    confidence: float | None
    status: AnalysisStatus
    version: int
    created_at: datetime
    updated_at: datetime


class SceneResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    asset_id: UUID
    job_id: UUID
    start_time: float
    end_time: float
    scene_label: str
    description: str | None
    confidence: float | None
    created_at: datetime
    updated_at: datetime


class OcrResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    asset_id: UUID
    job_id: UUID
    start_time: float
    end_time: float
    text: str
    bounding_box: dict
    confidence: float | None
    created_at: datetime
    updated_at: datetime


class TimelineResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: UUID
    items: list[TimelineItem]


class SegmentReviseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_text: str = Field(min_length=1)
    reason: str | None = Field(default=None, max_length=4000)


class SegmentReviseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    segment_id: UUID
    previous_text: str
    new_text: str
    created_by_user_id: UUID
    created_at: datetime
