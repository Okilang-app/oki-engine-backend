from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from oki.reviews.enums import ReviewDecisionType


# ---------------------------------------------------------------------------
# Create / Request schemas
# ---------------------------------------------------------------------------

class CommentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., min_length=1, max_length=50000)
    line_reference: str | None = Field(default=None, max_length=255)


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=4000)
    package_version_id: UUID | None = Field(default=None)


class PackageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    status: str = Field(default="open", max_length=64)


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class ReviewPackageVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    package_id: UUID
    version_number: int
    canonical_hash: str
    material_changed: bool
    invalidated_at: datetime | None
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime
    version: int


class CommentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    package_version_id: UUID
    author_user_id: UUID
    text: str
    line_reference: str | None
    created_at: datetime


class ReviewDecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    package_version_id: UUID
    decision: ReviewDecisionType
    reason: str | None
    decided_by_user_id: UUID
    decided_at: datetime
    correlation_id: UUID


class ReviewPackageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    job_id: UUID
    created_by_user_id: UUID
    status: str
    correlation_id: UUID
    created_at: datetime
    updated_at: datetime
    version: int
