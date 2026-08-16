"""Create asset_stems, media_streams, asset_validation_results, and media_artifacts.

Revision ID: 0006_asset_validation
Revises: 0005_assets_uploads
Create Date: 2026-08-15
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0006_asset_validation"
down_revision: str | None = "0005_assets_uploads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPLICATION_ROLE = "oki_app"
MUTABLE_NO_DELETE_TABLES = (
    "asset_validation_results",
)
APPEND_ONLY_TABLES = (
    "asset_stems",
    "media_streams",
    "media_artifacts",
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
        "asset_stems",
        _id_column(),
        sa.Column("source_asset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_assets.id", ondelete="CASCADE"), nullable=False),
        _organization_column(),
        sa.Column("stem_type", sa.String(100), nullable=False),
        sa.Column("storage_key", sa.String(1024), nullable=False),
        sa.Column("storage_bucket", sa.String(255), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("sample_rate", sa.Integer(), nullable=True),
        sa.Column("channel_count", sa.Integer(), nullable=True),
        _created_at_column(),
        sa.CheckConstraint("sha256 IS NULL OR sha256 ~ '^[0-9a-fA-F]{64}$'", name="ck_asset_stems_sha256"),
    )
    op.create_index("ix_asset_stems_asset", "asset_stems", ["source_asset_id", "stem_type"])

    op.create_table(
        "media_streams",
        _id_column(),
        sa.Column("source_asset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stream_index", sa.Integer(), nullable=False),
        sa.Column("stream_type", sa.String(20), nullable=False),
        sa.Column("codec_name", sa.String(100), nullable=True),
        sa.Column("codec_long_name", sa.String(255), nullable=True),
        sa.Column("bitrate", sa.Integer(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("sample_rate", sa.Integer(), nullable=True),
        sa.Column("channel_count", sa.Integer(), nullable=True),
        sa.Column("language", sa.String(16), nullable=True),
        _created_at_column(),
        sa.CheckConstraint("stream_type IN ('video', 'audio', 'subtitle', 'data')", name="ck_media_streams_type"),
        sa.UniqueConstraint("source_asset_id", "stream_index", name="uq_media_streams_index"),
    )
    op.create_index("ix_media_streams_asset", "media_streams", ["source_asset_id", "stream_type"])

    op.create_table(
        "asset_validation_results",
        _id_column(),
        sa.Column("source_asset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_assets.id", ondelete="CASCADE"), nullable=False),
        _organization_column(),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("sha256_computed", sa.String(64), nullable=True),
        sa.Column("error_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        _actor_column(),
        _created_at_column(),
        sa.CheckConstraint("status IN ('pending', 'running', 'passed', 'failed')", name="ck_asset_validation_results_status"),
        sa.CheckConstraint("sha256_computed IS NULL OR sha256_computed ~ '^[0-9a-fA-F]{64}$'", name="ck_asset_validation_results_sha256"),
    )
    op.create_index("ix_asset_validation_results_asset", "asset_validation_results", ["source_asset_id", "status"])

    op.create_table(
        "media_artifacts",
        _id_column(),
        sa.Column("source_asset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_assets.id", ondelete="CASCADE"), nullable=False),
        _organization_column(),
        sa.Column("artifact_type", sa.String(20), nullable=False),
        sa.Column("storage_key", sa.String(1024), nullable=False),
        sa.Column("storage_bucket", sa.String(255), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("artifact_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        _actor_column(),
        _created_at_column(),
        sa.CheckConstraint("sha256 IS NULL OR sha256 ~ '^[0-9a-fA-F]{64}$'", name="ck_media_artifacts_sha256"),
        sa.CheckConstraint("artifact_type IN ('proxy', 'audio_extract', 'thumbnail', 'transcript', 'stem')", name="ck_media_artifacts_type"),
    )
    op.create_index("ix_media_artifacts_asset", "media_artifacts", ["source_asset_id", "artifact_type"])

    op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APPLICATION_ROLE}') THEN
                EXECUTE 'GRANT SELECT, INSERT, UPDATE ON TABLE {", ".join(MUTABLE_NO_DELETE_TABLES)} TO {APPLICATION_ROLE}';
                EXECUTE 'GRANT SELECT, INSERT ON TABLE {", ".join(APPEND_ONLY_TABLES)} TO {APPLICATION_ROLE}';
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    for table_name in ("media_artifacts", "asset_validation_results", "media_streams", "asset_stems"):
        op.drop_table(table_name)
