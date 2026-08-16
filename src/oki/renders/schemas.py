from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from oki.renders.enums import RenderStatus


class ManifestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    job_id: UUID
    canonical_hash: str
    inputs: dict[str, Any]
    output_spec: dict[str, Any]
    status: str
    meta: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    version: int


class RenderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    render_manifest_id: UUID
    provider_key: str
    provider_request_id: str | None
    status: str
    ffmpeg_plan: dict[str, Any]
    error_message: str | None
    meta: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class RenderJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID | None
    job_id: UUID | None
    status: RenderStatus
    output_storage_key: str | None
    progress_percent: int
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class CreateRenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID | None = None
    job_id: UUID | None = None


class UpdateRenderStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: RenderStatus
    progress_percent: int | None = None
    output_storage_key: str | None = None
