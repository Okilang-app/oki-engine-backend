"""Create voice_profiles and pronunciation_entries.

Revision ID: 0010_voice_profiles
Revises: 0009_translation_workspace
Create Date: 2026-08-15
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0010_voice_profiles"
down_revision: str | None = "0009_translation_workspace"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPLICATION_ROLE = "oki_app"
MUTABLE_NO_DELETE_TABLES = ("voice_profiles",)
APPEND_ONLY_TABLES = ("pronunciation_entries",)


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
        "voice_profiles",
        _id_column(),
        _organization_column(),
        sa.Column("creator_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("creators.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("mode", sa.String(100), nullable=False),
        sa.Column("language_code", sa.String(16), nullable=False),
        sa.Column("provider_key", sa.String(100), nullable=False, server_default="internal"),
        sa.Column("provider_voice_id", sa.String(255), nullable=True),
        sa.Column("ssml_config", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("consent_reference", sa.String(255), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        *_mutable_columns(),
        sa.CheckConstraint("mode IN ('licensed_neutral_voice', 'creator_approved_clone', 'human_voice_actor')", name="ck_voice_profiles_mode"),
    )
    op.create_index("ix_voice_profiles_organization", "voice_profiles", ["organization_id"])
    op.create_index("ix_voice_profiles_creator", "voice_profiles", ["creator_id"])

    op.create_table(
        "pronunciation_entries",
        _id_column(),
        _organization_column(),
        sa.Column("voice_profile_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("voice_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("original_text", sa.Text(), nullable=False),
        sa.Column("pronunciation", sa.Text(), nullable=False),
        sa.Column("part_of_speech", sa.String(50), nullable=True),
        sa.Column("language_code", sa.String(16), nullable=False),
        *_mutable_columns(),
        sa.UniqueConstraint("voice_profile_id", "original_text", "language_code", name="uq_pronunciation_entries_text_lang"),
    )
    op.create_index("ix_pronunciation_entries_voice_profile", "pronunciation_entries", ["voice_profile_id"])

    op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APPLICATION_ROLE}') THEN
                EXECUTE 'GRANT SELECT, INSERT, UPDATE ON TABLE voice_profiles TO {APPLICATION_ROLE}';
                EXECUTE 'GRANT SELECT, INSERT ON TABLE pronunciation_entries TO {APPLICATION_ROLE}';
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.drop_table("pronunciation_entries")
    op.drop_table("voice_profiles")
