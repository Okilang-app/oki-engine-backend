"""Merge expand_internal_ads and translation_segment_qa branches

Revision ID: 0024_merge_ads_and_qa
Revises: 0023_expand_internal_ads, 0023_translation_segment_qa
Create Date: 2026-09-06 00:00:00.000000
"""
from collections.abc import Sequence

revision: str = "0024_merge_ads_and_qa"
down_revision: tuple[str, str] = ("0023_expand_internal_ads", "0023_translation_segment_qa")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
