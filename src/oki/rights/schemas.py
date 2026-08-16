from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from oki.rights.enums import (
    AgreementDecisionType,
    AssetScope,
    ConsentDecision,
    ContentFormat,
    CreatorApprovalPolicy,
    EndorsementMode,
    MonetizationMode,
    Platform,
    SponsorReplacementMode,
)


class RightsGrantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_scope: AssetScope
    asset_reference: str | None = Field(default=None, max_length=255)
    language_code: str = Field(min_length=2, max_length=16, pattern=r"^[A-Za-z0-9-]+$")
    territory_code: str = Field(min_length=2, max_length=3, pattern=r"^[A-Za-z]{2,3}$")
    platform: Platform
    content_format: ContentFormat
    translation_allowed: bool
    dubbing_allowed: bool
    editing_allowed: bool
    metadata_allowed: bool
    likeness_allowed: bool
    brand_use_allowed: bool
    sponsor_removal_allowed: bool
    sponsor_replacement_mode: SponsorReplacementMode
    endorsement_mode: EndorsementMode
    voice_clone_allowed: bool
    creator_approval_policy: CreatorApprovalPolicy
    starts_at: AwareDatetime
    ends_at: AwareDatetime

    @model_validator(mode="after")
    def validate_scope_and_dates(self) -> "RightsGrantCreate":
        if self.asset_scope is AssetScope.ALL and self.asset_reference is not None:
            raise ValueError("asset_reference must be omitted for an all-assets grant")
        if self.asset_scope is not AssetScope.ALL and not self.asset_reference:
            raise ValueError("asset_reference is required for category and asset grants")
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be later than starts_at")
        if (
            self.sponsor_replacement_mode is not SponsorReplacementMode.NONE
            and not self.sponsor_removal_allowed
        ):
            raise ValueError("sponsor replacement requires sponsor removal permission")
        return self


class AgreementVersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_reference: str = Field(min_length=1, max_length=1024)
    contract_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$")
    effective_from: AwareDatetime
    expires_at: AwareDatetime
    termination_notice_days: int | None = Field(default=None, ge=0)
    termination_terms: str
    monetization_mode: MonetizationMode
    fixed_fee_amount: Decimal | None = Field(default=None, ge=0, decimal_places=6)
    revenue_share_bps: Decimal | None = Field(default=None, ge=0, le=10000, decimal_places=4)
    payout_currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$")
    payout_frequency: str = Field(min_length=1, max_length=100)
    payout_terms: str
    grants: list[RightsGrantCreate] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_version_terms(self) -> "AgreementVersionCreate":
        if self.expires_at <= self.effective_from:
            raise ValueError("expires_at must be later than effective_from")
        if self.monetization_mode in {MonetizationMode.FIXED_FEE, MonetizationMode.HYBRID}:
            if self.fixed_fee_amount is None:
                raise ValueError("fixed_fee_amount is required by the monetization mode")
        if self.monetization_mode in {MonetizationMode.REVENUE_SHARE, MonetizationMode.HYBRID}:
            if self.revenue_share_bps is None:
                raise ValueError("revenue_share_bps is required by the monetization mode")
        return self


class AgreementCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agreement_id: UUID | None = None
    title: str = Field(min_length=1, max_length=255)
    external_reference: str | None = Field(default=None, max_length=255)
    version: AgreementVersionCreate


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agreement_version_id: UUID | None = None
    reason: str | None = Field(default=None, max_length=4000)


class VoiceConsentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agreement_version_id: UUID
    decision: ConsentDecision
    supersedes_consent_id: UUID | None = None
    language_code: str = Field(min_length=2, max_length=16, pattern=r"^[A-Za-z0-9-]+$")
    territory_code: str = Field(min_length=2, max_length=3, pattern=r"^[A-Za-z]{2,3}$")
    platform: Platform
    provider: str = Field(min_length=1, max_length=100)
    purpose: str = Field(min_length=1)
    evidence_reference: str = Field(min_length=1, max_length=1024)
    evidence_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$")
    effective_from: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def validate_dates(self) -> "VoiceConsentCreate":
        if self.expires_at <= self.effective_from:
            raise ValueError("expires_at must be later than effective_from")
        return self


class EndorsementConsentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agreement_version_id: UUID
    decision: ConsentDecision
    supersedes_consent_id: UUID | None = None
    language_code: str = Field(min_length=2, max_length=16, pattern=r"^[A-Za-z0-9-]+$")
    territory_code: str = Field(min_length=2, max_length=3, pattern=r"^[A-Za-z]{2,3}$")
    platform: Platform
    approved_language: str = Field(min_length=1)
    evidence_reference: str = Field(min_length=1, max_length=1024)
    evidence_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$")
    effective_from: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def validate_dates(self) -> "EndorsementConsentCreate":
        if self.expires_at <= self.effective_from:
            raise ValueError("expires_at must be later than effective_from")
        return self


class RightsGrantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agreement_version_id: UUID
    asset_scope: AssetScope
    asset_reference: str | None
    language_code: str
    territory_code: str
    platform: Platform
    content_format: ContentFormat
    translation_allowed: bool
    dubbing_allowed: bool
    editing_allowed: bool
    metadata_allowed: bool
    likeness_allowed: bool
    brand_use_allowed: bool
    sponsor_removal_allowed: bool
    sponsor_replacement_mode: SponsorReplacementMode
    endorsement_mode: EndorsementMode
    voice_clone_allowed: bool
    creator_approval_policy: CreatorApprovalPolicy
    starts_at: datetime
    ends_at: datetime
    created_at: datetime


class AgreementVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agreement_id: UUID
    agreement_version_number: int
    contract_reference: str
    contract_sha256: str
    effective_from: datetime
    expires_at: datetime
    termination_notice_days: int | None
    termination_terms: str
    monetization_mode: MonetizationMode
    fixed_fee_amount: Decimal | None
    revenue_share_bps: Decimal | None
    payout_currency: str
    payout_frequency: str
    payout_terms: str
    submitted_at: datetime
    grants: list[RightsGrantResponse]
    created_at: datetime
    updated_at: datetime
    version: int


class AgreementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    creator_id: UUID
    title: str
    external_reference: str | None
    latest_version: AgreementVersionResponse
    created_at: datetime
    updated_at: datetime
    version: int


class AgreementDecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agreement_id: UUID
    agreement_version_id: UUID
    decision: AgreementDecisionType
    reason: str | None
    decided_by_user_id: UUID
    decided_at: datetime
    created_at: datetime


class VoiceConsentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agreement_id: UUID
    agreement_version_id: UUID
    decision: ConsentDecision
    supersedes_consent_id: UUID | None
    language_code: str
    territory_code: str
    platform: Platform
    provider: str
    purpose: str
    evidence_reference: str
    evidence_sha256: str
    effective_from: datetime
    expires_at: datetime
    created_at: datetime


class EndorsementConsentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agreement_id: UUID
    agreement_version_id: UUID
    decision: ConsentDecision
    supersedes_consent_id: UUID | None
    language_code: str
    territory_code: str
    platform: Platform
    approved_language: str
    evidence_reference: str
    evidence_sha256: str
    effective_from: datetime
    expires_at: datetime
    created_at: datetime
