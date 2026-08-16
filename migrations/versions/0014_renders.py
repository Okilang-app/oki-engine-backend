"""Create edit_decision_lists, render_manifests, render_attempts, render_outputs, render_validation_results, publication_packages.

Revision ID: 0014_renders
Revises: 0013_campaigns_creatives
Create Date: 2026-08-15
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0014_renders"
down_revision: str | None = "0013_campaigns_creatives"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPLICATION_ROLE = "oki_app"
MUTABLE_NO_DELETE_TABLES = (
    "edit_decision_lists",
    "render_manifests",
    "render_attempts",
    "render_outputs",
    "render_validation_results",
    "publication_packages",
)
APPEND_ONLY_TABLES: tuple[str, ...] = ()


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


def upgrade() -> None:
    op.create_table(
        "render_manifests",
        _id_column(),
        _organization_column(),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("localization_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("canonical_hash", sa.String(64), nullable=False),
        sa.Column("inputs", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("output_spec", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        *_mutable_columns(),
        sa.UniqueConstraint("canonical_hash", name="uq_render_manifests_hash"),
    )
    op.create_index("ix_render_manifests_job", "render_manifests", ["job_id"])

    op.create_table(
        "edit_decision_lists",
        _id_column(),
        _organization_column(),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("localization_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("render_manifest_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("render_manifests.id", ondelete="SET NULL"), nullable=True),
        sa.Column("edl_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        *_mutable_columns(),
    )
    op.create_index("ix_edit_decision_lists_job", "edit_decision_lists", ["job_id"])
    op.create_index("ix_edit_decision_lists_manifest", "edit_decision_lists", ["render_manifest_id"])

    op.create_table(
        "render_attempts",
        _id_column(),
        _organization_column(),
        sa.Column("render_manifest_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("render_manifests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_key", sa.String(100), nullable=False),
        sa.Column("provider_request_id", sa.String(255), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("ffmpeg_plan", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        _created_at_column(),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_render_attempts_manifest", "render_attempts", ["render_manifest_id"])
    op.create_index("ix_render_attempts_status", "render_attempts", ["status"])

    op.create_table(
        "render_outputs",
        _id_column(),
        _organization_column(),
        sa.Column("render_attempt_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("render_attempts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_reference", sa.String(2048), nullable=False),
        sa.Column("format", sa.String(50), nullable=False),
        sa.Column("resolution", sa.String(50), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        _created_at_column(),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_render_outputs_attempt", "render_outputs", ["render_attempt_id"])
    op.create_index("ix_render_outputs_asset", "render_outputs", ["asset_reference"])

    op.create_table(
        "render_validation_results",
        _id_column(),
        _organization_column(),
        sa.Column("render_attempt_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("render_attempts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("streams_ok", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("black_frames_detected", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("subtitles_present", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("issues", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("passed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        *_mutable_columns(),
    )
    op.create_index("ix_render_validation_results_attempt", "render_validation_results", ["render_attempt_id"])

    op.create_table(
        "publication_packages",
        _id_column(),
        _organization_column(),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("localization_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("render_manifest_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("render_manifests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform", sa.String(50), nullable=False),
        sa.Column("package_assets", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        *_mutable_columns(),
    )
    op.create_index("ix_publication_packages_job", "publication_packages", ["job_id"])
    op.create_index("ix_publication_packages_manifest", "publication_packages", ["render_manifest_id"])

    op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APPLICATION_ROLE}') THEN
                EXECUTE 'GRANT SELECT, INSERT, UPDATE ON TABLE edit_decision_lists, render_manifests, render_attempts, render_outputs, render_validation_results, publication_packages TO {APPLICATION_ROLE}';
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.drop_table("publication_packages")
    op.drop_table("render_validation_results")
    op.drop_table("render_outputs")
    op.drop_table("render_attempts")
    op.drop_table("edit_decision_lists")
    op.drop_table("render_manifests")
