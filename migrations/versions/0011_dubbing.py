"""Create dub_segments and dub_attempts.

Revision ID: 0011_dubbing
Revises: 0010_voice_profiles
Create Date: 2026-08-15
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0011_dubbing"
down_revision: str | None = "0010_voice_profiles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPLICATION_ROLE = "oki_app"
MUTABLE_NO_DELETE_TABLES = ("dub_segments",)
APPEND_ONLY_TABLES = ("dub_attempts",)


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
        "dub_segments",
        _id_column(),
        _organization_column(),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("localization_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("translation_job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("localization_jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("translated_text", sa.Text(), nullable=True),
        sa.Column("voice_profile_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("voice_profiles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("timing_start_ms", sa.Integer(), nullable=True),
        sa.Column("timing_end_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("audio_asset_reference", sa.String(2048), nullable=True),
        sa.Column("review_status", sa.String(50), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        *_mutable_columns(),
        sa.UniqueConstraint("job_id", "sequence_number", name="uq_dub_segments_job_sequence"),
    )
    op.create_index("ix_dub_segments_job_id", "dub_segments", ["job_id"])
    op.create_index("ix_dub_segments_voice_profile", "dub_segments", ["voice_profile_id"])

    op.create_table(
        "dub_attempts",
        _id_column(),
        _organization_column(),
        sa.Column("dub_segment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("dub_segments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_key", sa.String(100), nullable=False),
        sa.Column("provider_request_id", sa.String(255), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("audio_asset_reference", sa.String(2048), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        *_mutable_columns(),
    )
    op.create_index("ix_dub_attempts_segment", "dub_attempts", ["dub_segment_id"])
    op.create_index("ix_dub_attempts_provider", "dub_attempts", ["provider_key", "provider_request_id"])

    op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APPLICATION_ROLE}') THEN
                EXECUTE 'GRANT SELECT, INSERT, UPDATE ON TABLE dub_segments TO {APPLICATION_ROLE}';
                EXECUTE 'GRANT SELECT, INSERT ON TABLE dub_attempts TO {APPLICATION_ROLE}';
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.drop_table("dub_attempts")
    op.drop_table("dub_segments")
