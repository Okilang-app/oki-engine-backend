"""Create source_assets, asset_versions, asset_uploads, and upload_parts.

Revision ID: 0005_assets_uploads
Revises: 0004_creators_rights
Create Date: 2026-08-15
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0005_assets_uploads"
down_revision: str | None = "0004_creators_rights"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPLICATION_ROLE = "oki_app"
MUTABLE_NO_DELETE_TABLES = (
    "source_assets",
    "asset_uploads",
)
APPEND_ONLY_TABLES = (
    "asset_versions",
    "upload_parts",
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
        "source_assets",
        _id_column(),
        _organization_column(),
        sa.Column("creator_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("creators.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rights_agreement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rights_agreements.id", ondelete="SET NULL"), nullable=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("localization_job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("localization_jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("storage_key", sa.String(1024), nullable=True),
        sa.Column("storage_bucket", sa.String(255), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("container_format", sa.String(50), nullable=True),
        _actor_column(),
        *_mutable_columns(),
        sa.CheckConstraint("status IN ('draft', 'active', 'archived', 'deleted')", name="ck_source_assets_status"),
        sa.CheckConstraint("sha256 IS NULL OR sha256 ~ '^[0-9a-fA-F]{64}$'", name="ck_source_assets_sha256"),
    )
    op.create_index("ix_source_assets_organization", "source_assets", ["organization_id", "status"])
    op.create_index("ix_source_assets_creator", "source_assets", ["creator_id", "created_at"])
    op.create_index("ix_source_assets_job", "source_assets", ["localization_job_id", "created_at"])

    op.create_table(
        "asset_versions",
        _id_column(),
        sa.Column("source_asset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(1024), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        _actor_column(),
        _created_at_column(),
        sa.CheckConstraint("sha256 IS NULL OR sha256 ~ '^[0-9a-fA-F]{64}$'", name="ck_asset_versions_sha256"),
        sa.UniqueConstraint("source_asset_id", "version_number", name="uq_asset_versions_number"),
    )
    op.create_index("ix_asset_versions_asset", "asset_versions", ["source_asset_id", "version_number"])

    op.create_table(
        "asset_uploads",
        _id_column(),
        sa.Column("source_asset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_assets.id", ondelete="CASCADE"), nullable=False),
        _organization_column(),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("upload_id", sa.String(255), nullable=True),
        sa.Column("storage_key", sa.String(1024), nullable=True),
        sa.Column("part_size", sa.Integer(), nullable=True),
        sa.Column("total_parts", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=True),
        _actor_column(),
        *_mutable_columns(),
        sa.CheckConstraint("status IN ('pending', 'in_progress', 'completed', 'failed', 'aborted')", name="ck_asset_uploads_status"),
        sa.CheckConstraint("sha256 IS NULL OR sha256 ~ '^[0-9a-fA-F]{64}$'", name="ck_asset_uploads_sha256"),
    )
    op.create_index("ix_asset_uploads_asset", "asset_uploads", ["source_asset_id", "status"])
    op.create_index("ix_asset_uploads_organization", "asset_uploads", ["organization_id", "created_at"])

    op.create_table(
        "upload_parts",
        _id_column(),
        sa.Column("asset_upload_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("asset_uploads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("part_number", sa.Integer(), nullable=False),
        sa.Column("etag", sa.String(255), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        _created_at_column(),
        sa.UniqueConstraint("asset_upload_id", "part_number", name="uq_upload_parts_number"),
    )
    op.create_index("ix_upload_parts_upload", "upload_parts", ["asset_upload_id", "part_number"])

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
    for table_name in ("upload_parts", "asset_uploads", "asset_versions", "source_assets"):
        op.drop_table(table_name)
