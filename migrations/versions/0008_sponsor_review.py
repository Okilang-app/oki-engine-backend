"""Create sponsor review tables.

Revision ID: 0008_sponsor_review
Revises: 0007_analysis_timeline
Create Date: 2026-08-15
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0008_sponsor_review"
down_revision: str | None = "0007_analysis_timeline"
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
        "ad_segments", _id_column(), _organization_column(),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("localization_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("start_time", sa.Numeric(12, 3), nullable=False),
        sa.Column("end_time", sa.Numeric(12, 3), nullable=False),
        sa.Column("sponsor_name", sa.String(255), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("replacement_type", sa.String(30), nullable=True),
        sa.Column("reason_note", sa.Text(), nullable=True),
        sa.Column("reviewed_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        *_mutable_columns(),
        sa.CheckConstraint("status IN ('detected', 'confirmed', 'replaced', 'rejected')", name="ck_ad_segments_status"),
        sa.CheckConstraint("replacement_type IS NULL OR replacement_type IN ('skip', 'mute', 'replace_voice', 'replace_visual')", name="ck_ad_segments_replacement_type"),
    )
    op.create_index("ix_ad_segments_asset_time", "ad_segments", ["asset_id", "start_time"])
    op.create_index("ix_ad_segments_job_status", "ad_segments", ["job_id", "status"])

    op.create_table(
        "ad_segment_evidence", _id_column(), _organization_column(),
        sa.Column("ad_segment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ad_segments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("evidence_type", sa.String(30), nullable=False),
        sa.Column("source_segment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("transcript_segments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("evidence_data", sa.JSON(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        _created_at_column(),
        sa.CheckConstraint("evidence_type IN ('keyword', 'audio_fingerprint', 'brand_logo', 'manual')", name="ck_ad_segment_evidence_type"),
    )
    op.create_index("ix_ad_segment_evidence_segment", "ad_segment_evidence", ["ad_segment_id", "created_at"])

    op.create_table(
        "ad_segment_reviews", _id_column(), _organization_column(),
        sa.Column("ad_segment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ad_segments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("boundaries_start", sa.Numeric(12, 3), nullable=True),
        sa.Column("boundaries_end", sa.Numeric(12, 3), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        _actor_column("reviewed_by_user_id"),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        _created_at_column(),
        sa.CheckConstraint("decision IN ('approve', 'reject', 'adjust')", name="ck_ad_segment_reviews_decision"),
    )
    op.create_index("ix_ad_segment_reviews_segment", "ad_segment_reviews", ["ad_segment_id", "reviewed_at"])

    op.create_table(
        "replacement_plans", _id_column(), _organization_column(),
        sa.Column("ad_segment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ad_segments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("localization_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("replacement_type", sa.String(30), nullable=False),
        sa.Column("replacement_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        _actor_column(), *_mutable_columns(),
        sa.CheckConstraint("replacement_type IN ('skip', 'mute', 'replace_voice', 'replace_visual')", name="ck_replacement_plans_replacement_type"),
    )
    op.create_index("ix_replacement_plans_ad_segment", "replacement_plans", ["ad_segment_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_replacement_plans_ad_segment", table_name="replacement_plans")
    op.drop_table("replacement_plans")
    op.drop_index("ix_ad_segment_reviews_segment", table_name="ad_segment_reviews")
    op.drop_table("ad_segment_reviews")
    op.drop_index("ix_ad_segment_evidence_segment", table_name="ad_segment_evidence")
    op.drop_table("ad_segment_evidence")
    op.drop_index("ix_ad_segments_job_status", table_name="ad_segments")
    op.drop_index("ix_ad_segments_asset_time", table_name="ad_segments")
    op.drop_table("ad_segments")
