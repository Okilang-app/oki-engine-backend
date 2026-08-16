"""Asset, upload, validation, and artifact models."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from oki.assets.enums import (
    AssetStatus,
    MediaArtifactType,
    MediaStreamType,
    UploadStatus,
    ValidationStatus,
)
from oki.db.base import Base
from oki.db.mixins import TimestampMixin, VersionMixin


def _enum_values(enum_type: type[Any]) -> list[str]:
    return [member.value for member in enum_type]


ASSET_STATUS_TYPE = Enum(
    AssetStatus,
    name="asset_status",
    native_enum=False,
    create_constraint=False,
    validate_strings=True,
    values_callable=_enum_values,
)
UPLOAD_STATUS_TYPE = Enum(
    UploadStatus,
    name="upload_status",
    native_enum=False,
    create_constraint=False,
    validate_strings=True,
    values_callable=_enum_values,
)
VALIDATION_STATUS_TYPE = Enum(
    ValidationStatus,
    name="validation_status",
    native_enum=False,
    create_constraint=False,
    validate_strings=True,
    values_callable=_enum_values,
)
MEDIA_STREAM_TYPE = Enum(
    MediaStreamType,
    name="media_stream_type",
    native_enum=False,
    create_constraint=False,
    validate_strings=True,
    values_callable=_enum_values,
)
MEDIA_ARTIFACT_TYPE = Enum(
    MediaArtifactType,
    name="media_artifact_type",
    native_enum=False,
    create_constraint=False,
    validate_strings=True,
    values_callable=_enum_values,
)


class SourceAsset(TimestampMixin, VersionMixin, Base):
    __tablename__ = "source_assets"
    __table_args__ = (
        Index("ix_source_assets_organization", "organization_id", "status"),
        Index("ix_source_assets_creator", "creator_id", "created_at"),
        Index("ix_source_assets_job", "localization_job_id", "created_at"),
        CheckConstraint(
            "status IN ('draft', 'active', 'archived', 'deleted')",
            name="ck_source_assets_status",
        ),
        CheckConstraint(
            "sha256 IS NULL OR sha256 ~ '^[0-9a-fA-F]{64}$'",
            name="ck_source_assets_sha256",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    creator_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("creators.id", ondelete="CASCADE"),
        nullable=False,
    )
    rights_agreement_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("rights_agreements.id", ondelete="SET NULL"),
        nullable=True,
    )
    project_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    localization_job_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("localization_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[AssetStatus] = mapped_column(ASSET_STATUS_TYPE, nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    storage_bucket: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    container_format: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_by_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


class AssetVersion(Base):
    __tablename__ = "asset_versions"
    __table_args__ = (
        UniqueConstraint("source_asset_id", "version_number", name="uq_asset_versions_number"),
        Index("ix_asset_versions_asset", "source_asset_id", "version_number"),
        CheckConstraint(
            "sha256 IS NULL OR sha256 ~ '^[0-9a-fA-F]{64}$'",
            name="ck_asset_versions_sha256",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    source_asset_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("source_assets.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AssetUpload(TimestampMixin, Base):
    __tablename__ = "asset_uploads"
    __table_args__ = (
        Index("ix_asset_uploads_asset", "source_asset_id", "status"),
        Index("ix_asset_uploads_organization", "organization_id", "created_at"),
        CheckConstraint(
            "status IN ('pending', 'in_progress', 'completed', 'failed', 'aborted')",
            name="ck_asset_uploads_status",
        ),
        CheckConstraint(
            "sha256 IS NULL OR sha256 ~ '^[0-9a-fA-F]{64}$'",
            name="ck_asset_uploads_sha256",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    source_asset_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("source_assets.id", ondelete="CASCADE"),
        nullable=False,
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[UploadStatus] = mapped_column(UPLOAD_STATUS_TYPE, nullable=False)
    upload_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    part_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_parts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


class UploadPart(Base):
    __tablename__ = "upload_parts"
    __table_args__ = (
        UniqueConstraint("asset_upload_id", "part_number", name="uq_upload_parts_number"),
        Index("ix_upload_parts_upload", "asset_upload_id", "part_number"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    asset_upload_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("asset_uploads.id", ondelete="CASCADE"),
        nullable=False,
    )
    part_number: Mapped[int] = mapped_column(Integer, nullable=False)
    etag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AssetStem(Base):
    __tablename__ = "asset_stems"
    __table_args__ = (
        Index("ix_asset_stems_asset", "source_asset_id", "stem_type"),
        CheckConstraint(
            "sha256 IS NULL OR sha256 ~ '^[0-9a-fA-F]{64}$'",
            name="ck_asset_stems_sha256",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    source_asset_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("source_assets.id", ondelete="CASCADE"),
        nullable=False,
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    stem_type: Mapped[str] = mapped_column(String(100), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    storage_bucket: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sample_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    channel_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MediaStream(Base):
    __tablename__ = "media_streams"
    __table_args__ = (
        UniqueConstraint("source_asset_id", "stream_index", name="uq_media_streams_index"),
        Index("ix_media_streams_asset", "source_asset_id", "stream_type"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    source_asset_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("source_assets.id", ondelete="CASCADE"),
        nullable=False,
    )
    stream_index: Mapped[int] = mapped_column(Integer, nullable=False)
    stream_type: Mapped[MediaStreamType] = mapped_column(MEDIA_STREAM_TYPE, nullable=False)
    codec_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    codec_long_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bitrate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sample_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    channel_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AssetValidationResult(Base):
    __tablename__ = "asset_validation_results"
    __table_args__ = (
        Index("ix_asset_validation_results_asset", "source_asset_id", "status"),
        CheckConstraint(
            "status IN ('pending', 'running', 'passed', 'failed')",
            name="ck_asset_validation_results_status",
        ),
        CheckConstraint(
            "sha256_computed IS NULL OR sha256_computed ~ '^[0-9a-fA-F]{64}$'",
            name="ck_asset_validation_results_sha256",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    source_asset_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("source_assets.id", ondelete="CASCADE"),
        nullable=False,
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[ValidationStatus] = mapped_column(VALIDATION_STATUS_TYPE, nullable=False)
    sha256_computed: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MediaArtifact(Base):
    __tablename__ = "media_artifacts"
    __table_args__ = (
        Index("ix_media_artifacts_asset", "source_asset_id", "artifact_type"),
        CheckConstraint(
            "sha256 IS NULL OR sha256 ~ '^[0-9a-fA-F]{64}$'",
            name="ck_media_artifacts_sha256",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    source_asset_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("source_assets.id", ondelete="CASCADE"),
        nullable=False,
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    artifact_type: Mapped[MediaArtifactType] = mapped_column(MEDIA_ARTIFACT_TYPE, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    storage_bucket: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    artifact_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_by_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
