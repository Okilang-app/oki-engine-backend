"""Add back_translation and risk_flag to translation_segments.

Revision ID: 0023_translation_segment_qa
Revises: 0022_notifications
Create Date: 2026-09-06
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0023_translation_segment_qa"
down_revision: str | None = "0022_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPLICATION_ROLE = "oki_app"
MUTABLE_NO_DELETE_TABLES = ("translation_segments",)
APPEND_ONLY_TABLES: tuple[str, ...] = ()


def upgrade() -> None:
    op.add_column(
        "translation_segments",
        sa.Column("back_translation", sa.Text(), nullable=True),
    )
    op.add_column(
        "translation_segments",
        sa.Column("risk_flag", sa.String(100), nullable=True),
    )

    for table in MUTABLE_NO_DELETE_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO {APPLICATION_ROLE}")
    for table in APPEND_ONLY_TABLES:
        op.execute(f"GRANT SELECT, INSERT ON {table} TO {APPLICATION_ROLE}")


def downgrade() -> None:
    op.drop_column("translation_segments", "risk_flag")
    op.drop_column("translation_segments", "back_translation")
