from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from oki.db.base import Base
from oki.db.mixins import TimestampMixin, VersionMixin
from oki.renders.enums import RenderStatus


def _enum_values(enum_type: type[Any]) -> list[str]:
    return [member.value for member in enum_type]


RENDER_STATUS_TYPE = Enum(
    RenderStatus,
    name="render_status",
    native_enum=False,
    create_constraint=False,
    validate_strings=True,
    values_callable=_enum_values,
)


class RenderJob(TimestampMixin, Base):
    __tablename__ = "render_jobs"
    __table_args__ = (
        Index("ix_render_jobs_organization_status", "organization_id", "status"),
    )
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    project_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
    )
    job_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("localization_jobs.id", ondelete="CASCADE"),
        nullable=True,
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[RenderStatus] = mapped_column(
        RENDER_STATUS_TYPE,
        nullable=False,
        default=RenderStatus.QUEUED,
        server_default=RenderStatus.QUEUED.value,
    )
    output_storage_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    progress_percent: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )


class EditDecisionList(TimestampMixin, VersionMixin, Base):
    __tablename__ = "edit_decision_lists"
    __table_args__ = (
        Index("ix_edit_decision_lists_job", "job_id"),
        Index("ix_edit_decision_lists_manifest", "render_manifest_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    job_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("localization_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    render_manifest_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("render_manifests.id", ondelete="SET NULL"),
        nullable=True,
    )
    edl_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="pending"
    )
    meta: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


class RenderManifest(TimestampMixin, VersionMixin, Base):
    __tablename__ = "render_manifests"
    __table_args__ = (
        UniqueConstraint("canonical_hash", name="uq_render_manifests_hash"),
        Index("ix_render_manifests_job", "job_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    job_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("localization_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    canonical_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    inputs: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    output_spec: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="pending"
    )
    meta: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


class RenderAttempt(TimestampMixin, Base):
    __tablename__ = "render_attempts"
    __table_args__ = (
        Index("ix_render_attempts_manifest", "render_manifest_id"),
        Index("ix_render_attempts_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    render_manifest_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("render_manifests.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider_key: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="pending"
    )
    ffmpeg_plan: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


class RenderOutput(TimestampMixin, Base):
    __tablename__ = "render_outputs"
    __table_args__ = (
        Index("ix_render_outputs_attempt", "render_attempt_id"),
        Index("ix_render_outputs_asset", "asset_reference"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    render_attempt_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("render_attempts.id", ondelete="CASCADE"),
        nullable=False,
    )
    asset_reference: Mapped[str] = mapped_column(String(2048), nullable=False)
    format: Mapped[str] = mapped_column(String(50), nullable=False)
    resolution: Mapped[str | None] = mapped_column(String(50), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


class RenderValidationResult(TimestampMixin, Base):
    __tablename__ = "render_validation_results"
    __table_args__ = (
        Index("ix_render_validation_results_attempt", "render_attempt_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    render_attempt_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("render_attempts.id", ondelete="CASCADE"),
        nullable=False,
    )
    streams_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    black_frames_detected: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    subtitles_present: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    issues: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    meta: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


class PublicationPackage(TimestampMixin, Base):
    __tablename__ = "publication_packages"
    __table_args__ = (
        Index("ix_publication_packages_job", "job_id"),
        Index("ix_publication_packages_manifest", "render_manifest_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    job_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("localization_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    render_manifest_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("render_manifests.id", ondelete="CASCADE"),
        nullable=False,
    )
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    package_assets: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="pending"
    )
    meta: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
