"""Create short candidates, versions, scores, approvals, and publications.

Revision ID: 0018_shorts
Revises: 0017_publications
Create Date: 2026-08-15
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0018_shorts"
down_revision: str | None = "0017_publications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPLICATION_ROLE = "oki_app"
MUTABLE_NO_DELETE_TABLES = ("short_candidates",)
APPEND_ONLY_TABLES = (
    "short_versions",
    "short_scores",
    "short_approvals",
    "short_publications",
)


def _id_column() -> sa.Column[object]:
    return sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuidv7()"))


def _created_at_column() -> sa.Column[object]:
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"))


def _organization_column() -> sa.Column[object]:
    return sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)


def _actor_column(name: str = "created_by_user_id") -> sa.Column[object]:
    return sa.Column(name, postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "short_candidates",
        _id_column(),
        _organization_column(),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("localization_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="candidate"),
        sa.Column("source_timestamps", sa.dialects.postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("detected_hooks", sa.dialects.postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("raw_score", sa.Float(), nullable=True),
        _actor_column(),
        _created_at_column(),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("status IN ('candidate', 'scoring', 'revising', 'approved', 'rejected', 'published')", name="ck_short_candidates_status"),
        sa.Index("ix_short_candidates_organization_job", "organization_id", "job_id"),
    )

    op.create_table(
        "short_versions",
        _id_column(),
        _organization_column(),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("short_candidates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("crop_params", sa.dialects.postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("refinement_prompt", sa.Text(), nullable=True),
        sa.Column("revised_media_url", sa.String(2048), nullable=True),
        _created_at_column(),
        sa.Index("ix_short_versions_candidate", "candidate_id"),
    )

    op.create_table(
        "short_scores",
        _id_column(),
        _organization_column(),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("short_candidates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("short_versions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("factor_scores", sa.dialects.postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("total_score", sa.Float(), nullable=False),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Index("ix_short_scores_candidate", "candidate_id"),
    )

    op.create_table(
        "short_approvals",
        _id_column(),
        _organization_column(),
        sa.Column("short_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("short_candidates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("approved_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        _created_at_column(),
        sa.Index("ix_short_approvals_short", "short_id"),
    )

    op.create_table(
        "short_publications",
        _id_column(),
        _organization_column(),
        sa.Column("short_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("short_candidates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform", sa.String(100), nullable=False),
        sa.Column("platform_video_id", sa.String(255), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        _created_at_column(),
        sa.Index("ix_short_publications_short", "short_id"),
    )

    for table in MUTABLE_NO_DELETE_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO {APPLICATION_ROLE}")
    for table in APPEND_ONLY_TABLES:
        op.execute(f"GRANT SELECT, INSERT ON {table} TO {APPLICATION_ROLE}")


def downgrade() -> None:
    op.drop_table("short_publications")
    op.drop_table("short_approvals")
    op.drop_table("short_scores")
    op.drop_table("short_versions")
    op.drop_table("short_candidates")
