"""Create render_jobs table.

Revision ID: 0021_render_jobs
Revises: 0020_finance
Create Date: 2026-08-15
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0021_render_jobs"
down_revision: str | None = "0020_finance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPLICATION_ROLE = "oki_app"
MUTABLE_NO_DELETE_TABLES = ("render_jobs",)
APPEND_ONLY_TABLES: tuple[str, ...] = ()


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
        "render_jobs",
        _id_column(),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("localization_jobs.id", ondelete="CASCADE"), nullable=True),
        _organization_column(),
        sa.Column("status", sa.String(50), nullable=False, server_default="QUEUED"),
        sa.Column("output_storage_key", sa.String(1024), nullable=True),
        sa.Column("progress_percent", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error_message", sa.Text(), nullable=True),
        _actor_column(),
        _created_at_column(),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Index("ix_render_jobs_organization_status", "organization_id", "status"),
    )

    for table in MUTABLE_NO_DELETE_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO {APPLICATION_ROLE}")
    for table in APPEND_ONLY_TABLES:
        op.execute(f"GRANT SELECT, INSERT ON {table} TO {APPLICATION_ROLE}")


def downgrade() -> None:
    op.drop_table("render_jobs")
