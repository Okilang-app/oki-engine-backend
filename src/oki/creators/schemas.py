from datetime import datetime
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl

from oki.rights.enums import ConsentDecision, CreatorStatus, Platform


class ChannelOwnershipEvidenceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: str = Field(min_length=1, max_length=100)
    decision: ConsentDecision
    evidence_reference: str = Field(min_length=1, max_length=1024)
    evidence_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$")
    observed_at: AwareDatetime
    decided_at: AwareDatetime
    reason: str | None = Field(default=None, max_length=2000)


class CreatorChannelCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: Platform
    external_channel_id: str = Field(min_length=1, max_length=255)
    handle: str | None = Field(default=None, max_length=255)
    canonical_url: HttpUrl
    ownership_evidence: list[ChannelOwnershipEvidenceCreate] = Field(default_factory=list)


class CreatorBrandGuideCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    guide_reference: str = Field(min_length=1, max_length=1024)
    guide_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$")
    notes: str | None = None
    effective_from: AwareDatetime


class CreatorRestrictionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    restriction_type: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1)
    effective_from: AwareDatetime
    expires_at: AwareDatetime | None = None


class CreatorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    legal_name: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    primary_email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")
    manager_name: str | None = Field(default=None, max_length=255)
    manager_email: str | None = Field(default=None, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")
    status: CreatorStatus = CreatorStatus.ACTIVE
    channels: list[CreatorChannelCreate] = Field(default_factory=list)
    brand_guides: list[CreatorBrandGuideCreate] = Field(default_factory=list)
    restrictions: list[CreatorRestrictionCreate] = Field(default_factory=list)


class ChannelOwnershipEvidenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    method: str
    decision: ConsentDecision
    evidence_reference: str
    evidence_sha256: str
    observed_at: datetime
    decided_at: datetime
    reason: str | None
    created_at: datetime


class CreatorChannelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    platform: Platform
    external_channel_id: str
    handle: str | None
    canonical_url: str
    ownership_verified: bool
    ownership_evidence: list[ChannelOwnershipEvidenceResponse]
    created_at: datetime


class CreatorBrandGuideResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    guide_reference: str
    guide_sha256: str
    notes: str | None
    effective_from: datetime
    created_at: datetime


class CreatorRestrictionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    restriction_type: str
    description: str
    effective_from: datetime
    expires_at: datetime | None
    created_at: datetime


class CreatorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    legal_name: str
    display_name: str
    primary_email: str
    manager_name: str | None
    manager_email: str | None
    status: CreatorStatus
    channels: list[CreatorChannelResponse]
    brand_guides: list[CreatorBrandGuideResponse]
    restrictions: list[CreatorRestrictionResponse]
    created_at: datetime
    updated_at: datetime
    version: int
