"""Expand internal_ads with SOW 8.9 creative metadata columns

Revision ID: 0023_expand_internal_ads
Revises: 7827a6e11a33
Create Date: 2026-09-06 00:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023_expand_internal_ads"
down_revision: str | None = "7827a6e11a33"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("internal_ads", sa.Column("format", sa.String(64), nullable=True))
    op.add_column("internal_ads", sa.Column("language_code", sa.String(16), nullable=True))
    op.add_column("internal_ads", sa.Column("audience", sa.String(255), nullable=True))
    op.add_column("internal_ads", sa.Column("cta", sa.String(1024), nullable=True))
    op.add_column("internal_ads", sa.Column("landing_page", sa.String(2048), nullable=True))
    op.add_column("internal_ads", sa.Column("promo_code", sa.String(255), nullable=True))
    op.add_column("internal_ads", sa.Column("territory_codes", postgresql.JSONB(), nullable=True))
    op.add_column("internal_ads", sa.Column("campaign_start", sa.DateTime(timezone=True), nullable=True))
    op.add_column("internal_ads", sa.Column("campaign_end", sa.DateTime(timezone=True), nullable=True))
    op.add_column("internal_ads", sa.Column("approved_claims", postgresql.JSONB(), nullable=True))
    op.add_column("internal_ads", sa.Column("prohibited_claims", postgresql.JSONB(), nullable=True))
    op.add_column("internal_ads", sa.Column("disclosure_text", sa.Text(), nullable=True))
    op.add_column("internal_ads", sa.Column(
        "endorsement_mode", sa.String(64), nullable=True,
        server_default="neutral_disclosure",
    ))
    op.add_column("internal_ads", sa.Column(
        "endorsement_approved", sa.Boolean(), nullable=False,
        server_default=sa.text("false"),
    ))


def downgrade() -> None:
    for col in (
        "endorsement_approved", "endorsement_mode", "disclosure_text",
        "prohibited_claims", "approved_claims", "campaign_end", "campaign_start",
        "territory_codes", "promo_code", "landing_page", "cta", "audience",
        "language_code", "format",
    ):
        op.drop_column("internal_ads", col)
