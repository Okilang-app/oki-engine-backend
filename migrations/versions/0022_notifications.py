"""Create notifications table.

Revision ID: 0022_notifications
Revises: 0021_render_jobs
Create Date: 2026-09-05
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0022_notifications"
down_revision: str | None = "0021_render_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPLICATION_ROLE = "oki_app"
MUTABLE_NO_DELETE_TABLES = ("notifications",)
APPEND_ONLY_TABLES: tuple[str, ...] = ()


def _id_column() -> sa.Column[object]:
    return sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()"))


def _created_at_column() -> sa.Column[object]:
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"))


def _organization_column() -> sa.Column[object]:
    return sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "notifications",
        _id_column(),
        _organization_column(),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column(
            "channel",
            sa.Enum("email", "in_app", "telegram", name="notificationchannel"),
            nullable=False,
            server_default="in_app",
        ),
        sa.Column(
            "status",
            sa.Enum("pending", "sent", "failed", name="notificationstatus"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("send_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        _created_at_column(),
        sa.Index("ix_notifications_user_id_created_at", "user_id", "created_at"),
    )

    for table in MUTABLE_NO_DELETE_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO {APPLICATION_ROLE}")
    for table in APPEND_ONLY_TABLES:
        op.execute(f"GRANT SELECT, INSERT ON {table} TO {APPLICATION_ROLE}")


def downgrade() -> None:
    op.drop_table("notifications")
    op.execute("DROP TYPE IF EXISTS notificationchannel")
    op.execute("DROP TYPE IF EXISTS notificationstatus")
