"""Create translation workspace tables.

Revision ID: 0009_translation_workspace
Revises: 0008_sponsor_review
Create Date: 2026-08-15
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0009_translation_workspace"
down_revision: str | None = "0008_sponsor_review"
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
        "glossaries", _id_column(), _organization_column(),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("source_language", sa.String(16), nullable=False),
        sa.Column("target_language", sa.String(16), nullable=False),
        _actor_column(), *_mutable_columns(),
    )
    op.create_index("ix_glossaries_project", "glossaries", ["project_id", "created_at"])

    op.create_table(
        "glossary_terms", _id_column(), _organization_column(),
        sa.Column("glossary_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("glossaries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_term", sa.String(500), nullable=False),
        sa.Column("target_term", sa.String(500), nullable=False),
        sa.Column("part_of_speech", sa.String(50), nullable=True),
        sa.Column("context", sa.Text(), nullable=True),
        _actor_column(), *_mutable_columns(),
    )
    op.create_index("ix_glossary_terms_glossary", "glossary_terms", ["glossary_id", "source_term"])

    op.create_table(
        "translation_memories", _id_column(), _organization_column(),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("target_text", sa.Text(), nullable=False),
        sa.Column("source_language", sa.String(16), nullable=False),
        sa.Column("target_language", sa.String(16), nullable=False),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        _actor_column(), *_mutable_columns(),
    )
    op.create_index("ix_translation_memories_project", "translation_memories", ["project_id", "source_language", "target_language"])

    op.create_table(
        "translations", _id_column(), _organization_column(),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("localization_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_language", sa.String(16), nullable=False),
        sa.Column("target_language", sa.String(16), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        _actor_column(), *_mutable_columns(),
        sa.CheckConstraint("status IN ('pending', 'in_progress', 'review_pending', 'approved', 'rejected')", name="ck_translations_status"),
    )
    op.create_index("ix_translations_job", "translations", ["job_id", "target_language"])
    op.create_index("ix_translations_project", "translations", ["project_id", "created_at"])

    op.create_table(
        "translation_segments", _id_column(), _organization_column(),
        sa.Column("translation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("translations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_segment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("transcript_segments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("translated_text", sa.Text(), nullable=True),
        sa.Column("start_time", sa.Numeric(12, 3), nullable=True),
        sa.Column("end_time", sa.Numeric(12, 3), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        *_mutable_columns(),
        sa.CheckConstraint("status IN ('pending', 'in_progress', 'review_pending', 'approved', 'rejected')", name="ck_translation_segments_status"),
    )
    op.create_index("ix_translation_segments_translation", "translation_segments", ["translation_id", "sequence_number"])

    op.create_table(
        "translation_revisions", _id_column(), _organization_column(),
        sa.Column("translation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("translations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("segment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("translation_segments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("previous_text", sa.Text(), nullable=False),
        sa.Column("new_text", sa.Text(), nullable=False),
        _actor_column(), *_mutable_columns(),
    )
    op.create_index("ix_translation_revisions_translation", "translation_revisions", ["translation_id", "created_at"])

    op.create_table(
        "translation_comments", _id_column(), _organization_column(),
        sa.Column("translation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("translations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("segment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("translation_segments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("comment_text", sa.Text(), nullable=False),
        _actor_column(), *_mutable_columns(),
    )
    op.create_index("ix_translation_comments_translation", "translation_comments", ["translation_id", "created_at"])

    op.create_table(
        "translation_qa_reviews", _id_column(), _organization_column(),
        sa.Column("translation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("translations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dimension", sa.String(20), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        _actor_column("reviewer_id"),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        *_mutable_columns(),
        sa.CheckConstraint("dimension IN ('accuracy', 'fluency', 'terminology', 'style', 'locale', 'format', 'safety')", name="ck_translation_qa_reviews_dimension"),
        sa.CheckConstraint("score >= 0 AND score <= 10", name="ck_translation_qa_reviews_score_range"),
    )
    op.create_index("ix_translation_qa_reviews_translation", "translation_qa_reviews", ["translation_id", "dimension"])


def downgrade() -> None:
    op.drop_index("ix_translation_qa_reviews_translation", table_name="translation_qa_reviews")
    op.drop_table("translation_qa_reviews")
    op.drop_index("ix_translation_comments_translation", table_name="translation_comments")
    op.drop_table("translation_comments")
    op.drop_index("ix_translation_revisions_translation", table_name="translation_revisions")
    op.drop_table("translation_revisions")
    op.drop_index("ix_translation_segments_translation", table_name="translation_segments")
    op.drop_table("translation_segments")
    op.drop_index("ix_translations_project", table_name="translations")
    op.drop_index("ix_translations_job", table_name="translations")
    op.drop_table("translations")
    op.drop_index("ix_translation_memories_project", table_name="translation_memories")
    op.drop_table("translation_memories")
    op.drop_index("ix_glossary_terms_glossary", table_name="glossary_terms")
    op.drop_table("glossary_terms")
    op.drop_index("ix_glossaries_project", table_name="glossaries")
    op.drop_table("glossaries")
