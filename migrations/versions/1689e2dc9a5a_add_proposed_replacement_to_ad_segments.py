"""add_proposed_replacement_to_ad_segments

Revision ID: 1689e2dc9a5a
Revises: abe2e8a591d2
Create Date: 2026-08-15 23:13:41.877519
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '1689e2dc9a5a'
down_revision: str | None = 'abe2e8a591d2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'ad_segments',
        sa.Column('proposed_replacement_ad_id', sa.Uuid(), nullable=True)
    )
    op.add_column(
        'ad_segments',
        sa.Column('proposed_at', sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('ad_segments', 'proposed_replacement_ad_id')
    op.drop_column('ad_segments', 'proposed_at')
