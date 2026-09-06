"""Ad Pydantic schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from oki.ads.enums import AdFormat, EndorsementMode


class AdCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=255)
    storage_key: str = Field(..., min_length=1, max_length=1024)
    duration_seconds: int | None = Field(default=None, ge=0)

    # SOW 8.9 creative metadata (all optional at creation)
    format: AdFormat | None = Field(default=None)
    language_code: str | None = Field(default=None, max_length=16)
    audience: str | None = Field(default=None, max_length=255)
    cta: str | None = Field(default=None, max_length=1024)
    landing_page: str | None = Field(default=None, max_length=2048)
    promo_code: str | None = Field(default=None, max_length=255)
    territory_codes: list[str] | None = Field(default=None)
    campaign_start: datetime | None = Field(default=None)
    campaign_end: datetime | None = Field(default=None)
    approved_claims: list[str] | None = Field(default=None)
    prohibited_claims: list[str] | None = Field(default=None)
    disclosure_text: str | None = Field(default=None)
    endorsement_mode: EndorsementMode = Field(default=EndorsementMode.NEUTRAL_DISCLOSURE)


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

    format: str | None
    language_code: str | None
    audience: str | None
    cta: str | None
    landing_page: str | None
    promo_code: str | None
    territory_codes: list[str] | None
    campaign_start: datetime | None
    campaign_end: datetime | None
    approved_claims: list[str] | None
    prohibited_claims: list[str] | None
    disclosure_text: str | None
    endorsement_mode: str | None
    endorsement_approved: bool
