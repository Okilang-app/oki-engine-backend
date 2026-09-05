"""merge notification branch

Revision ID: 7827a6e11a33
Revises: 0022_notifications, 940e8afcebe0
Create Date: 2026-09-05 20:48:38.147804
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '7827a6e11a33'
down_revision: str | None = ('0022_notifications', '940e8afcebe0')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
