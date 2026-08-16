"""add_ml_transformer_to_detection_reason

Revision ID: 940e8afcebe0
Revises: 1689e2dc9a5a
Create Date: 2026-08-16 00:28:56.820824
"""
from collections.abc import Sequence

from alembic import op


revision: str = '940e8afcebe0'
down_revision: str | None = '1689e2dc9a5a'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint('ck_ad_segment_evidence_type', 'ad_segment_evidence', type_='check')
    op.create_check_constraint(
        'ck_ad_segment_evidence_type',
        'ad_segment_evidence',
        "evidence_type IN ('keyword', 'audio_fingerprint', 'brand_logo', 'ml_transformer', 'manual')"
    )


def downgrade() -> None:
    op.drop_constraint('ck_ad_segment_evidence_type', 'ad_segment_evidence', type_='check')
    op.create_check_constraint(
        'ck_ad_segment_evidence_type',
        'ad_segment_evidence',
        "evidence_type IN ('keyword', 'audio_fingerprint', 'brand_logo', 'manual')"
    )
