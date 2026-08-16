"""Create publications, attempts, platform checks, and publish approvals.

Revision ID: 0017_publications
Revises: 0016_youtube_connections
Create Date: 2026-08-15
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0017_publications"
down_revision: str | None = "0016_youtube_connections"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPLICATION_ROLE = "oki_app"
MUTABLE_NO_DELETE_TABLES = ("publications",)
APPEND_ONLY_TABLES = (
    "publication_attempts",
    "platform_checks",
    "publish_approvals",
)


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
        "publications",
        _id_column(),
        _organization_column(),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("localization_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("authorized_channels.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("mode", sa.String(30), nullable=False, server_default="creator_channel_localization"),
        sa.Column("video_id", sa.String(255), nullable=True),
        sa.Column("private_video_id", sa.String(255), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        _actor_column(),
        *_mutable_columns(),
        sa.CheckConstraint("status IN ('draft', 'private_uploaded', 'platform_check_pending', 'approved', 'published', 'unpublished', 'failed')", name="ck_publications_status"),
        sa.CheckConstraint("mode IN ('creator_channel_localization', 'licensed_regional_channel', 'original_local_adaptation')", name="ck_publications_mode"),
        sa.Index("ix_publications_organization_status", "organization_id", "status"),
        sa.Index("ix_publications_job_id", "job_id"),
    )

    op.create_table(
        "publication_attempts",
        _id_column(),
        _organization_column(),
        sa.Column("publication_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("publications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("platform_response", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        _created_at_column(),
        sa.Index("ix_publication_attempts_publication_id", "publication_id"),
    )

    op.create_table(
        "platform_checks",
        _id_column(),
        _organization_column(),
        sa.Column("publication_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("publications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("check_type", sa.String(100), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("details", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        _created_at_column(),
        sa.Index("ix_platform_checks_publication_id", "publication_id"),
    )

    op.create_table(
        "publish_approvals",
        _id_column(),
        _organization_column(),
        sa.Column("publication_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("publications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("approved_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        _created_at_column(),
        sa.Index("ix_publish_approvals_publication_id", "publication_id"),
    )

    for table in MUTABLE_NO_DELETE_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO {APPLICATION_ROLE}")
    for table in APPEND_ONLY_TABLES:
        op.execute(f"GRANT SELECT, INSERT ON {table} TO {APPLICATION_ROLE}")


def downgrade() -> None:
    op.drop_table("publish_approvals")
    op.drop_table("platform_checks")
    op.drop_table("publication_attempts")
    op.drop_table("publications")
