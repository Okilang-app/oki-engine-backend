from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from oki.creators.models import CreatedAtMixin
from oki.db.base import Base
from oki.db.mixins import TimestampMixin, VersionMixin
from oki.sponsors.enums import DetectionReason, ReplacementType, SponsorStatus


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


SPONSOR_STATUS_TYPE = _enum_type(SponsorStatus, "sponsor_status")
DETECTION_REASON_TYPE = _enum_type(DetectionReason, "detection_reason")
REPLACEMENT_TYPE_TYPE = _enum_type(ReplacementType, "replacement_type")


class AdSegments(TimestampMixin, VersionMixin, Base):
    __tablename__ = "ad_segments"
    __table_args__ = (
        Index("ix_ad_segments_asset_time", "asset_id", "start_time"),
        Index("ix_ad_segments_job_status", "job_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    asset_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("source_assets.id", ondelete="CASCADE"),
        nullable=False,
    )
    job_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("localization_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    start_time: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    end_time: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    sponsor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[SponsorStatus] = mapped_column(SPONSOR_STATUS_TYPE, nullable=False)
    replacement_type: Mapped[ReplacementType | None] = mapped_column(
        REPLACEMENT_TYPE_TYPE, nullable=True
    )
    reason_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by_user_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    proposed_replacement_ad_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=True
    )
    proposed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AdSegmentEvidence(CreatedAtMixin, Base):
    __tablename__ = "ad_segment_evidence"
    __table_args__ = (
        Index("ix_ad_segment_evidence_segment", "ad_segment_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    ad_segment_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("ad_segments.id", ondelete="CASCADE"),
        nullable=False,
    )
    evidence_type: Mapped[DetectionReason] = mapped_column(
        DETECTION_REASON_TYPE, nullable=False
    )
    source_segment_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("transcript_segments.id", ondelete="SET NULL"),
        nullable=True,
    )
    evidence_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)


class AdSegmentReviews(CreatedAtMixin, Base):
    __tablename__ = "ad_segment_reviews"
    __table_args__ = (
        Index("ix_ad_segment_reviews_segment", "ad_segment_id", "reviewed_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    ad_segment_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("ad_segments.id", ondelete="CASCADE"),
        nullable=False,
    )
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    boundaries_start: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    boundaries_end: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReplacementPlans(TimestampMixin, VersionMixin, Base):
    __tablename__ = "replacement_plans"
    __table_args__ = (
        Index("ix_replacement_plans_ad_segment", "ad_segment_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    ad_segment_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("ad_segments.id", ondelete="CASCADE"),
        nullable=False,
    )
    job_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("localization_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    replacement_type: Mapped[ReplacementType] = mapped_column(
        REPLACEMENT_TYPE_TYPE, nullable=False
    )
    replacement_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    created_by_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
