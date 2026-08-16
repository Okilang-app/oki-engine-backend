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
    text as sa_text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from oki.creators.models import CreatedAtMixin
from oki.db.base import Base
from oki.db.mixins import TimestampMixin, VersionMixin
from oki.analysis.enums import AnalysisStatus, EvidenceType, SegmentType


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


ANALYSIS_STATUS_TYPE = _enum_type(AnalysisStatus, "analysis_status")
SEGMENT_TYPE_TYPE = _enum_type(SegmentType, "segment_type")
EVIDENCE_TYPE_TYPE = _enum_type(EvidenceType, "evidence_type")


class Speakers(CreatedAtMixin, Base):
    __tablename__ = "speakers"
    __table_args__ = (
        Index("ix_speakers_asset", "asset_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=sa_text("uuidv7()")
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
    speaker_label: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    sample_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


class TranscriptSegments(TimestampMixin, VersionMixin, Base):
    __tablename__ = "transcript_segments"
    __table_args__ = (
        Index("ix_transcript_segments_asset_time", "asset_id", "start_time"),
        Index("ix_transcript_segments_job", "job_id", "start_time"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=sa_text("uuidv7()")
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
    speaker_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("speakers.id", ondelete="SET NULL"),
        nullable=True,
    )
    start_time: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    end_time: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    language_code: Mapped[str] = mapped_column(String(16), nullable=False)
    segment_type: Mapped[SegmentType] = mapped_column(SEGMENT_TYPE_TYPE, nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    status: Mapped[AnalysisStatus] = mapped_column(
        ANALYSIS_STATUS_TYPE,
        nullable=False,
        default=AnalysisStatus.COMPLETED,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=sa_text("1"))
    created_by_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


class TranscriptWords(Base):
    __tablename__ = "transcript_words"
    __table_args__ = (
        Index("ix_transcript_words_segment", "segment_id", "start_time"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=sa_text("uuidv7()")
    )
    segment_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("transcript_segments.id", ondelete="CASCADE"),
        nullable=False,
    )
    start_time: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    end_time: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    text: Mapped[str] = mapped_column(String(500), nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)


class Scenes(TimestampMixin, VersionMixin, Base):
    __tablename__ = "scenes"
    __table_args__ = (
        Index("ix_scenes_asset_time", "asset_id", "start_time"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=sa_text("uuidv7()")
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
    scene_label: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)


class OcrSpans(TimestampMixin, VersionMixin, Base):
    __tablename__ = "ocr_spans"
    __table_args__ = (
        Index("ix_ocr_spans_asset_time", "asset_id", "start_time"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=sa_text("uuidv7()")
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
    text: Mapped[str] = mapped_column(Text, nullable=False)
    bounding_box: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sa_text("'{}'::jsonb")
    )
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)


class NamedEntities(TimestampMixin, VersionMixin, Base):
    __tablename__ = "named_entities"
    __table_args__ = (
        Index("ix_named_entities_asset", "asset_id", "entity_type"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=sa_text("uuidv7()")
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
    segment_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("transcript_segments.id", ondelete="SET NULL"),
        nullable=True,
    )
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_text: Mapped[str] = mapped_column(String(500), nullable=False)
    start_time: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    end_time: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)


class SafetyLabels(TimestampMixin, VersionMixin, Base):
    __tablename__ = "safety_labels"
    __table_args__ = (
        Index("ix_safety_labels_asset", "asset_id", "label"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=sa_text("uuidv7()")
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
    start_time: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    end_time: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)


class AudioRegions(TimestampMixin, VersionMixin, Base):
    __tablename__ = "audio_regions"
    __table_args__ = (
        Index("ix_audio_regions_asset_time", "asset_id", "start_time"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=sa_text("uuidv7()")
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
    region_type: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    features: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sa_text("'{}'::jsonb")
    )


class AnalysisRevisions(TimestampMixin, VersionMixin, Base):
    __tablename__ = "analysis_revisions"
    __table_args__ = (
        Index("ix_analysis_revisions_segment", "segment_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=sa_text("uuidv7()")
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
    segment_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("transcript_segments.id", ondelete="SET NULL"),
        nullable=True,
    )
    revision_type: Mapped[str] = mapped_column(String(50), nullable=False)
    previous_value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    new_value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_by_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
