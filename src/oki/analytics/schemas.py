from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LanguageBreakdownItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language_code: str
    views: int = 0
    revenue: float = 0.0


class CreatorMetricsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    creator_id: UUID
    total_views: int = 0
    total_revenue: float = 0.0
    language_breakdown: list[LanguageBreakdownItem] = Field(default_factory=list)


class VideoMetricsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    video_id: str
    views: int = 0
    watch_time: float = 0.0
    ctr: float = 0.0
    language: str | None = None


class CampaignMetricsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    campaign_id: str
    impressions: int = 0
    conversions: int = 0
    cost: Decimal = Decimal("0.00")
    roi: float = 0.0


class OkiConversionEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    event_type: str
    attributed_creator_id: UUID | None = None
    attributed_job_id: UUID | None = None
    attributed_language: str | None = None
    attributed_campaign_id: str | None = None
    value: float | None = None
    currency: str | None = None
    event_metadata: dict[str, Any]
    occurred_at: datetime
    created_at: datetime


class MetricIngestionRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    run_type: str
    status: str
    records_processed: int
    started_at: datetime
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class CostLedgerEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    job_id: UUID | None = None
    cost_category: str
    amount: Decimal
    currency: str
    incurred_at: datetime
    description: str | None = None
    created_at: datetime
    updated_at: datetime
