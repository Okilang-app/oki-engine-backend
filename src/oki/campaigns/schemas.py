from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from oki.campaigns.enums import CreativeStatus, CreativeType


class CreativeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    campaign_id: UUID
    name: str
    creative_type: CreativeType
    status: CreativeStatus
    language_code: str
    territory_code: str
    sponsor_name: str | None
    sponsor_product: str | None
    script_text: str | None
    visual_reference_url: str | None
    expires_at: datetime | None
    meta: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    version: int


class CampaignResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    name: str
    description: str | None
    starts_at: datetime
    ends_at: datetime
    budget_currency: str
    budget_amount: int
    meta: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    version: int


class CampaignCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    starts_at: datetime
    ends_at: datetime
    budget_currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$")
    budget_amount: int = Field(default=0, ge=0)
    meta: dict[str, Any] = Field(default_factory=dict)


class CampaignUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    budget_currency: str | None = Field(default=None, min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$")
    budget_amount: int | None = Field(default=None, ge=0)
    meta: dict[str, Any] | None = None


class CreativeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    creative_type: CreativeType
    language_code: str = Field(min_length=2, max_length=16, pattern=r"^[A-Za-z0-9-]+$")
    territory_code: str = Field(min_length=2, max_length=3, pattern=r"^[A-Za-z]{2,3}$")
    sponsor_name: str | None = Field(default=None, max_length=255)
    sponsor_product: str | None = Field(default=None, max_length=255)
    script_text: str | None = Field(default=None, max_length=10000)
    visual_reference_url: str | None = Field(default=None, max_length=2048)
    expires_at: datetime | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class CreativeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    creative_type: CreativeType | None = None
    language_code: str | None = Field(default=None, min_length=2, max_length=16, pattern=r"^[A-Za-z0-9-]+$")
    territory_code: str | None = Field(default=None, min_length=2, max_length=3, pattern=r"^[A-Za-z]{2,3}$")
    sponsor_name: str | None = Field(default=None, max_length=255)
    sponsor_product: str | None = Field(default=None, max_length=255)
    script_text: str | None = Field(default=None, max_length=10000)
    visual_reference_url: str | None = Field(default=None, max_length=2048)
    expires_at: datetime | None = None
    meta: dict[str, Any] | None = None
