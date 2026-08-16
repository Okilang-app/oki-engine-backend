"""Create OAuth connections and authorized channels for YouTube integration.

Revision ID: 0016_youtube_connections
Revises: 0015_reviews
Create Date: 2026-08-15
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0016_youtube_connections"
down_revision: str | None = "0015_reviews"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPLICATION_ROLE = "oki_app"
MUTABLE_NO_DELETE_TABLES = ("oauth_connections",)
APPEND_ONLY_TABLES = ("authorized_channels",)


def _id_column() -> sa.Column[object]:
    return sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuidv7()"))


def _created_at_column() -> sa.Column[object]:
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"))


def _organization_column() -> sa.Column[object]:
    return sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "oauth_connections",
        _id_column(),
        _organization_column(),
        sa.Column("creator_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("creators.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("access_token_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("refresh_token_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scope", sa.String(512), nullable=False),
        sa.Column("state", sa.String(256), nullable=True),
        sa.Column("code_verifier", sa.String(256), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        _created_at_column(),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )

    op.create_table(
        "authorized_channels",
        _id_column(),
        _organization_column(),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("oauth_connections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform_channel_id", sa.String(128), nullable=False),
        sa.Column("channel_title", sa.String(256), nullable=False),
        sa.Column("upload_defaults", sa.dialects.postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        _created_at_column(),
        sa.Index("ix_authorized_channels_connection", "connection_id"),
        sa.Index("ix_authorized_channels_platform", "organization_id", "platform_channel_id"),
    )

    for table in MUTABLE_NO_DELETE_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO {APPLICATION_ROLE}")
    for table in APPEND_ONLY_TABLES:
        op.execute(f"GRANT SELECT, INSERT ON {table} TO {APPLICATION_ROLE}")


def downgrade() -> None:
    op.drop_table("authorized_channels")
    op.drop_table("oauth_connections")
