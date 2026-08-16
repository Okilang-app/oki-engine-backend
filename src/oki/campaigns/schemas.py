from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

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
