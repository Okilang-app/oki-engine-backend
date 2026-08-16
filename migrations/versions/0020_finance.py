"""Create payout runs, inputs, creator payouts, approvals, and finance exports.

Revision ID: 0020_finance
Revises: 0019_analytics_events
Create Date: 2026-08-15
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0020_finance"
down_revision: str | None = "0019_analytics_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPLICATION_ROLE = "oki_app"
MUTABLE_NO_DELETE_TABLES = ("payout_runs",)
APPEND_ONLY_TABLES = (
    "payout_inputs",
    "creator_payouts",
    "payout_approvals",
    "finance_exports",
)


def _id_column() -> sa.Column[object]:
    return sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuidv7()"))


def _created_at_column() -> sa.Column[object]:
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"))


def _organization_column() -> sa.Column[object]:
    return sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)


def _actor_column(name: str = "created_by_user_id") -> sa.Column[object]:
    return sa.Column(name, postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "payout_runs",
        _id_column(),
        _organization_column(),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="draft"),
        sa.Column("total_gross", sa.Numeric(20, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("total_fees", sa.Numeric(20, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("total_payouts", sa.Numeric(20, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("currency", sa.String(3), nullable=False),
        _actor_column(),
        _created_at_column(),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Index("ix_payout_runs_organization_status", "organization_id", "status"),
    )

    op.create_table(
        "payout_inputs",
        _id_column(),
        _organization_column(),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payout_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("creator_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("creators.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("revenue_share_basis", sa.Numeric(20, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("deductions", sa.Numeric(20, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("bonus", sa.Numeric(20, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("exchange_rate", sa.Numeric(20, 8), nullable=False, server_default=sa.text("1")),
        _created_at_column(),
        sa.Index("ix_payout_inputs_run", "run_id", "created_at"),
        sa.Index("ix_payout_inputs_creator", "creator_id"),
    )

    op.create_table(
        "creator_payouts",
        _id_column(),
        _organization_column(),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payout_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("input_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payout_inputs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("creator_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("creators.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("calculated_amount", sa.Numeric(20, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("transfer_method", sa.String(50), nullable=True),
        sa.Column("transfer_reference", sa.String(255), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        _created_at_column(),
        sa.Index("ix_creator_payouts_run", "run_id", "status"),
        sa.Index("ix_creator_payouts_creator", "creator_id"),
    )

    op.create_table(
        "payout_approvals",
        _id_column(),
        _organization_column(),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payout_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("approved_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        _created_at_column(),
        sa.Index("ix_payout_approvals_run", "run_id", "approved_at"),
    )

    op.create_table(
        "finance_exports",
        _id_column(),
        _organization_column(),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payout_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("export_type", sa.String(50), nullable=False),
        sa.Column("file_url", sa.String(2048), nullable=True),
        sa.Column("file_sha256", sa.String(64), nullable=True),
        _actor_column(),
        _created_at_column(),
        sa.Index("ix_finance_exports_run", "run_id", "export_type"),
    )

    for table in MUTABLE_NO_DELETE_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO {APPLICATION_ROLE}")
    for table in APPEND_ONLY_TABLES:
        op.execute(f"GRANT SELECT, INSERT ON {table} TO {APPLICATION_ROLE}")


def downgrade() -> None:
    op.drop_table("finance_exports")
    op.drop_table("payout_approvals")
    op.drop_table("creator_payouts")
    op.drop_table("payout_inputs")
    op.drop_table("payout_runs")
