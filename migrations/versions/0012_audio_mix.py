"""Create audio_mix_versions and audio_qa_results.

Revision ID: 0012_audio_mix
Revises: 0011_dubbing
Create Date: 2026-08-15
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0012_audio_mix"
down_revision: str | None = "0011_dubbing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPLICATION_ROLE = "oki_app"
MUTABLE_NO_DELETE_TABLES = ("audio_mix_versions",)
APPEND_ONLY_TABLES = ("audio_qa_results",)


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
        "audio_mix_versions",
        _id_column(),
        _organization_column(),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("localization_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("localization_jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("mix_plan", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("stems", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("output_asset_reference", sa.String(2048), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        *_mutable_columns(),
    )
    op.create_index("ix_audio_mix_versions_job", "audio_mix_versions", ["job_id"])
    op.create_index("ix_audio_mix_versions_asset", "audio_mix_versions", ["asset_id"])

    op.create_table(
        "audio_qa_results",
        _id_column(),
        _organization_column(),
        sa.Column("audio_mix_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("audio_mix_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("clipping_detected", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("silence_detected", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("cut_words_detected", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("loudness_lufs", sa.Integer(), nullable=True),
        sa.Column("issues", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("passed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        *_mutable_columns(),
    )
    op.create_index("ix_audio_qa_results_mix_version", "audio_qa_results", ["audio_mix_version_id"])

    op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APPLICATION_ROLE}') THEN
                EXECUTE 'GRANT SELECT, INSERT, UPDATE ON TABLE audio_mix_versions TO {APPLICATION_ROLE}';
                EXECUTE 'GRANT SELECT, INSERT ON TABLE audio_qa_results TO {APPLICATION_ROLE}';
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.drop_table("audio_qa_results")
    op.drop_table("audio_mix_versions")
