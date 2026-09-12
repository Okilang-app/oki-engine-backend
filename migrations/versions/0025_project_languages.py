"""Add source_language and target_language to projects.

Revision ID: 0025_project_languages
Revises: 0024_merge_ads_and_qa
Create Date: 2026-09-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0025_project_languages"
down_revision: str | None = "0024_merge_ads_and_qa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("source_language", sa.String(10), nullable=True))
    op.add_column("projects", sa.Column("target_language", sa.String(10), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "target_language")
    op.drop_column("projects", "source_language")
