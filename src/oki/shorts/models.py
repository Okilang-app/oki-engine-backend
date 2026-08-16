from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from oki.creators.models import CreatedAtMixin
from oki.db.base import Base
from oki.db.mixins import TimestampMixin
from oki.jobs import models as _jobs_models  # register FK targets
from oki.identity import models as _identity_models  # register FK targets
from oki.shorts.enums import ShortStatus


def _enum_values(enum_type: type[Any]) -> list[str]:
    return [member.value for member in enum_type]


def _enum_type(enum_type: type[Any], name: str) -> Enum:
    return Enum(
        enum_type,
        name=name,
        native_enum=False,
        create_constraint=False,
        validate_strings=True,
        values_callable=_enum_values,
    )


SHORT_STATUS_TYPE = _enum_type(ShortStatus, "short_status")


class ShortCandidates(TimestampMixin, Base):
    __tablename__ = "short_candidates"
    __table_args__ = (
        Index("ix_short_candidates_organization_job", "organization_id", "job_id"),
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
    status: Mapped[ShortStatus] = mapped_column(
        SHORT_STATUS_TYPE,
        nullable=False,
        default=ShortStatus.CANDIDATE,
        server_default=ShortStatus.CANDIDATE.value,
    )
    source_timestamps: Mapped[list[tuple[float, float]]] = mapped_column(
        JSONB, nullable=False
    )
    detected_hooks: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    raw_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_by_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )


class ShortVersions(CreatedAtMixin, Base):
    __tablename__ = "short_versions"
    __table_args__ = (
        Index("ix_short_versions_candidate", "candidate_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    candidate_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("short_candidates.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    crop_params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    refinement_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    revised_media_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)


class ShortScores(Base):
    __tablename__ = "short_scores"
    __table_args__ = (
        Index("ix_short_scores_candidate", "candidate_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    candidate_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("short_candidates.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("short_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    factor_scores: Mapped[dict[str, float]] = mapped_column(JSONB, nullable=False)
    total_score: Mapped[float] = mapped_column(Float, nullable=False)
    scored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ShortApprovals(Base):
    __tablename__ = "short_approvals"
    __table_args__ = (
        Index("ix_short_approvals_short", "short_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    short_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("short_candidates.id", ondelete="CASCADE"),
        nullable=False,
    )
    approved_by_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    approved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ShortPublications(Base):
    __tablename__ = "short_publications"
    __table_args__ = (
        Index("ix_short_publications_short", "short_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    short_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("short_candidates.id", ondelete="CASCADE"),
        nullable=False,
    )
    platform: Mapped[str] = mapped_column(String(100), nullable=False)
    platform_video_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
