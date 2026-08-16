"""Create campaigns, campaign_versions, creatives, creative_versions, attribution_keys.

Revision ID: 0013_campaigns_creatives
Revises: 0012_audio_mix
Create Date: 2026-08-15
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0013_campaigns_creatives"
down_revision: str | None = "0012_audio_mix"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPLICATION_ROLE = "oki_app"
MUTABLE_NO_DELETE_TABLES = (
    "campaigns",
    "campaign_versions",
    "creatives",
    "creative_versions",
)
APPEND_ONLY_TABLES = ("attribution_keys",)


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
        "campaigns",
        _id_column(),
        _organization_column(),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("budget_currency", sa.String(3), nullable=False),
        sa.Column("budget_amount", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        *_mutable_columns(),
    )
    op.create_index("ix_campaigns_organization", "campaigns", ["organization_id"])
    op.create_index("ix_campaigns_dates", "campaigns", ["starts_at", "ends_at"])

    op.create_table(
        "campaign_versions",
        _id_column(),
        _organization_column(),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("changes_summary", sa.Text(), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        *_mutable_columns(),
        sa.UniqueConstraint("campaign_id", "version_number", name="uq_campaign_versions_number"),
    )

    op.create_table(
        "creatives",
        _id_column(),
        _organization_column(),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("creative_type", sa.String(100), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="draft"),
        sa.Column("language_code", sa.String(16), nullable=False),
        sa.Column("territory_code", sa.String(3), nullable=False),
        sa.Column("sponsor_name", sa.String(255), nullable=True),
        sa.Column("sponsor_product", sa.String(255), nullable=True),
        sa.Column("script_text", sa.Text(), nullable=True),
        sa.Column("visual_reference_url", sa.String(2048), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        *_mutable_columns(),
        sa.CheckConstraint("status IN ('draft', 'pending_review', 'approved', 'rejected', 'expired', 'archived')", name="ck_creatives_status"),
        sa.CheckConstraint("creative_type IN ('sponsor_integration', 'product_placement', 'brand_mention', 'endorsement', 'custom')", name="ck_creatives_type"),
    )
    op.create_index("ix_creatives_campaign", "creatives", ["campaign_id"])
    op.create_index("ix_creatives_status", "creatives", ["status"])

    op.create_table(
        "creative_versions",
        _id_column(),
        _organization_column(),
        sa.Column("creative_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("creatives.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("changes_summary", sa.Text(), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        *_mutable_columns(),
        sa.UniqueConstraint("creative_id", "version_number", name="uq_creative_versions_number"),
    )

    op.create_table(
        "attribution_keys",
        _id_column(),
        _organization_column(),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("creative_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("creatives.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key_type", sa.String(50), nullable=False),
        sa.Column("key_value", sa.String(255), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        *_mutable_columns(),
        sa.UniqueConstraint("creative_id", "key_type", "key_value", name="uq_attribution_keys_type_value"),
    )
    op.create_index("ix_attribution_keys_campaign", "attribution_keys", ["campaign_id"])

    op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APPLICATION_ROLE}') THEN
                EXECUTE 'GRANT SELECT, INSERT, UPDATE ON TABLE campaigns, campaign_versions, creatives, creative_versions TO {APPLICATION_ROLE}';
                EXECUTE 'GRANT SELECT, INSERT ON TABLE attribution_keys TO {APPLICATION_ROLE}';
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.drop_table("attribution_keys")
    op.drop_table("creative_versions")
    op.drop_table("creatives")
    op.drop_table("campaign_versions")
    op.drop_table("campaigns")
