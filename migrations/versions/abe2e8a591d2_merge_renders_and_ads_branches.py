"""Merge renders and ads branches

Revision ID: abe2e8a591d2
Revises: 0021_render_jobs, d52f6623ebc2
Create Date: 2026-08-15 16:07:30.765321
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'abe2e8a591d2'
down_revision: str | None = ('0021_render_jobs', 'd52f6623ebc2')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
