"""Asset Pydantic schemas."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from oki.assets.enums import AssetStatus, UploadStatus, ValidationStatus


class AssetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    creator_id: UUID
    rights_agreement_id: UUID | None = None
    project_id: UUID | None = None
    localization_job_id: UUID | None = None
    title: str = Field(..., max_length=255)
    description: str | None = Field(default=None, max_length=4000)


class AssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    creator_id: UUID
    rights_agreement_id: UUID | None
    project_id: UUID | None
    localization_job_id: UUID | None
    title: str
    description: str | None
    status: AssetStatus
    storage_key: str | None
    storage_bucket: str | None
    sha256: str | None
    size_bytes: int | None
    duration_seconds: int | None
    container_format: str | None
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime
    version: int


class SimpleUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., max_length=255)
    file_name: str = Field(..., max_length=255)
    content_type: str = Field(..., max_length=255)
    size_bytes: int = Field(..., gt=0)


class SimpleUploadResponse(BaseModel):
    asset_id: UUID
    presigned_url: str
    storage_key: str


class FinalizeUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sha256: str = Field(..., pattern=r"^[0-9a-fA-F]{64}$")


class UploadPartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    part_number: int = Field(..., ge=1)


class UploadUrlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: UUID
    file_name: str = Field(..., max_length=1024)
    content_type: str = Field(default="video/mp4", max_length=255)
    total_size: int = Field(..., gt=0)
    part_size: int = Field(default=50 * 1024 * 1024, gt=0)


class UploadPartUrl(BaseModel):
    part_number: int
    presigned_url: str


class UploadUrlResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    upload_id: UUID
    storage_key: str
    parts: list[UploadPartUrl]


class CompletePart(BaseModel):
    part_number: int
    etag: str


class CompleteUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upload_id: UUID
    parts: list[CompletePart]
    sha256: str = Field(..., pattern=r"^[0-9a-fA-F]{64}$")


class ValidationResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_asset_id: UUID
    status: ValidationStatus
    sha256_computed: str | None
    error_codes: list[str]
    details: dict[str, Any]
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
