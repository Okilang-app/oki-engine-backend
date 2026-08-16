from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class PayoutInputCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    creator_id: UUID
    revenue_share_basis: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    deductions: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    bonus: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    exchange_rate: Decimal = Field(default=Decimal("1"), gt=Decimal("0"))


class PayoutRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    period_start: AwareDatetime
    period_end: AwareDatetime
    currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    inputs: list[PayoutInputCreate]


class PayoutRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    period_start: datetime
    period_end: datetime
    status: str
    total_gross: Decimal
    total_fees: Decimal
    total_payouts: Decimal
    currency: str
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime


class PayoutInputResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    run_id: UUID
    creator_id: UUID
    revenue_share_basis: Decimal
    deductions: Decimal
    bonus: Decimal
    currency: str
    exchange_rate: Decimal
    created_at: datetime


class CreatorPayoutResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    run_id: UUID
    input_id: UUID
    creator_id: UUID
    calculated_amount: Decimal
    currency: str
    transfer_method: str | None
    transfer_reference: str | None
    status: str
    paid_at: datetime | None
    created_at: datetime


class PayoutApprovalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    run_id: UUID
    approved_by_user_id: UUID
    approved_at: datetime
    created_at: datetime


class FinanceExportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    run_id: UUID
    export_type: str
    file_url: str | None
    file_sha256: str | None
    created_by_user_id: UUID
    created_at: datetime


class ContributionMarginResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revenue: Decimal
    cost: Decimal
    margin_bps: Decimal
    margin_pct: Decimal
    gross_profit: Decimal


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    export_type: str = Field(min_length=1, max_length=50)
