"""Create analysis timeline tables.

Revision ID: 0007_analysis_timeline
Revises: 0006_asset_validation
Create Date: 2026-08-15
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0007_analysis_timeline"
down_revision: str | None = "0006_asset_validation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id_column() -> sa.Column[object]:
    return sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuidv7()"))


def _created_at_column() -> sa.Column[object]:
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"))


def _mutable_columns() -> tuple[sa.Column[object], ...]:
    return (
        _created_at_column(),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )


def _organization_column() -> sa.Column[object]:
    return sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)


def _actor_column(name: str = "created_by_user_id") -> sa.Column[object]:
    return sa.Column(name, postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "speakers", _id_column(), _organization_column(),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("localization_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("speaker_label", sa.String(50), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("sample_count", sa.Integer(), nullable=True),
        _actor_column(), _created_at_column(),
    )
    op.create_index("ix_speakers_asset", "speakers", ["asset_id", "created_at"])

    op.create_table(
        "transcript_segments", _id_column(), _organization_column(),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("localization_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("speaker_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("speakers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("start_time", sa.Numeric(12, 3), nullable=False),
        sa.Column("end_time", sa.Numeric(12, 3), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("language_code", sa.String(16), nullable=False),
        sa.Column("segment_type", sa.String(20), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="completed"),
        _actor_column(), *_mutable_columns(),
        sa.CheckConstraint("segment_type IN ('speech', 'music', 'noise', 'silence')", name="ck_transcript_segments_segment_type"),
        sa.CheckConstraint("status IN ('pending', 'running', 'completed', 'failed')", name="ck_transcript_segments_status"),
    )
    op.create_index("ix_transcript_segments_asset_time", "transcript_segments", ["asset_id", "start_time"])
    op.create_index("ix_transcript_segments_job", "transcript_segments", ["job_id", "start_time"])

    op.create_table(
        "transcript_words", _id_column(),
        sa.Column("segment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("transcript_segments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("start_time", sa.Numeric(12, 3), nullable=False),
        sa.Column("end_time", sa.Numeric(12, 3), nullable=False),
        sa.Column("text", sa.String(500), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
    )
    op.create_index("ix_transcript_words_segment", "transcript_words", ["segment_id", "start_time"])

    op.create_table(
        "scenes", _id_column(), _organization_column(),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("localization_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("start_time", sa.Numeric(12, 3), nullable=False),
        sa.Column("end_time", sa.Numeric(12, 3), nullable=False),
        sa.Column("scene_label", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        *_mutable_columns(),
    )
    op.create_index("ix_scenes_asset_time", "scenes", ["asset_id", "start_time"])

    op.create_table(
        "ocr_spans", _id_column(), _organization_column(),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("localization_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("start_time", sa.Numeric(12, 3), nullable=False),
        sa.Column("end_time", sa.Numeric(12, 3), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("bounding_box", sa.JSON(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        *_mutable_columns(),
    )
    op.create_index("ix_ocr_spans_asset_time", "ocr_spans", ["asset_id", "start_time"])

    op.create_table(
        "named_entities", _id_column(), _organization_column(),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("localization_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("segment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("transcript_segments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("entity_text", sa.String(500), nullable=False),
        sa.Column("start_time", sa.Numeric(12, 3), nullable=True),
        sa.Column("end_time", sa.Numeric(12, 3), nullable=True),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        *_mutable_columns(),
    )
    op.create_index("ix_named_entities_asset", "named_entities", ["asset_id", "entity_type"])

    op.create_table(
        "safety_labels", _id_column(), _organization_column(),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("localization_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("start_time", sa.Numeric(12, 3), nullable=True),
        sa.Column("end_time", sa.Numeric(12, 3), nullable=True),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        *_mutable_columns(),
    )
    op.create_index("ix_safety_labels_asset", "safety_labels", ["asset_id", "label"])

    op.create_table(
        "audio_regions", _id_column(), _organization_column(),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("localization_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("start_time", sa.Numeric(12, 3), nullable=False),
        sa.Column("end_time", sa.Numeric(12, 3), nullable=False),
        sa.Column("region_type", sa.String(50), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("features", sa.JSON(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        *_mutable_columns(),
    )
    op.create_index("ix_audio_regions_asset_time", "audio_regions", ["asset_id", "start_time"])

    op.create_table(
        "analysis_revisions", _id_column(), _organization_column(),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("localization_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("segment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("transcript_segments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("revision_type", sa.String(50), nullable=False),
        sa.Column("previous_value", sa.JSON(), nullable=False),
        sa.Column("new_value", sa.JSON(), nullable=False),
        _actor_column(), *_mutable_columns(),
    )
    op.create_index("ix_analysis_revisions_segment", "analysis_revisions", ["segment_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_analysis_revisions_segment", table_name="analysis_revisions")
    op.drop_table("analysis_revisions")
    op.drop_index("ix_audio_regions_asset_time", table_name="audio_regions")
    op.drop_table("audio_regions")
    op.drop_index("ix_safety_labels_asset", table_name="safety_labels")
    op.drop_table("safety_labels")
    op.drop_index("ix_named_entities_asset", table_name="named_entities")
    op.drop_table("named_entities")
    op.drop_index("ix_ocr_spans_asset_time", table_name="ocr_spans")
    op.drop_table("ocr_spans")
    op.drop_index("ix_scenes_asset_time", table_name="scenes")
    op.drop_table("scenes")
    op.drop_index("ix_transcript_words_segment", table_name="transcript_words")
    op.drop_table("transcript_words")
    op.drop_index("ix_transcript_segments_job", table_name="transcript_segments")
    op.drop_index("ix_transcript_segments_asset_time", table_name="transcript_segments")
    op.drop_table("transcript_segments")
    op.drop_index("ix_speakers_asset", table_name="speakers")
    op.drop_table("speakers")
