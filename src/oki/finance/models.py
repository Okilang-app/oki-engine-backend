from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from oki.creators.models import CreatedAtMixin
from oki.db.base import Base
from oki.db.mixins import TimestampMixin
from oki.identity import models as _identity_models  # noqa: F401  # register users/organizations FK targets
from oki.jobs import models as _jobs_models  # noqa: F401  # register organizations/projects FK targets


class PayoutRuns(TimestampMixin, Base):
    __tablename__ = "payout_runs"
    __table_args__ = (
        Index("ix_payout_runs_organization_period", "organization_id", "period_start", "period_end"),
        Index("ix_payout_runs_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="draft", server_default="draft"
    )
    total_gross: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=Decimal("0"), server_default=text("0")
    )
    total_fees: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=Decimal("0"), server_default=text("0")
    )
    total_payouts: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=Decimal("0"), server_default=text("0")
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    created_by_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )


class PayoutInputs(CreatedAtMixin, Base):
    __tablename__ = "payout_inputs"
    __table_args__ = (
        Index("ix_payout_inputs_run", "run_id", "created_at"),
        Index("ix_payout_inputs_creator", "creator_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("payout_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    creator_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("creators.id", ondelete="RESTRICT"),
        nullable=False,
    )
    revenue_share_basis: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=Decimal("0"), server_default=text("0")
    )
    deductions: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=Decimal("0"), server_default=text("0")
    )
    bonus: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=Decimal("0"), server_default=text("0")
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    exchange_rate: Mapped[Decimal] = mapped_column(
        Numeric(20, 8), nullable=False, default=Decimal("1"), server_default=text("1")
    )


class CreatorPayouts(CreatedAtMixin, Base):
    __tablename__ = "creator_payouts"
    __table_args__ = (
        Index("ix_creator_payouts_run", "run_id", "status"),
        Index("ix_creator_payouts_creator", "creator_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("payout_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    input_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("payout_inputs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    creator_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("creators.id", ondelete="RESTRICT"),
        nullable=False,
    )
    calculated_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=Decimal("0"), server_default=text("0")
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    transfer_method: Mapped[str | None] = mapped_column(String(50), nullable=True)
    transfer_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending", server_default="pending"
    )
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PayoutApprovals(CreatedAtMixin, Base):
    __tablename__ = "payout_approvals"
    __table_args__ = (
        Index("ix_payout_approvals_run", "run_id", "approved_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("payout_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    approved_by_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    approved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class FinanceExports(CreatedAtMixin, Base):
    __tablename__ = "finance_exports"
    __table_args__ = (
        Index("ix_finance_exports_run", "run_id", "export_type"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("payout_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    export_type: Mapped[str] = mapped_column(String(50), nullable=False)
    file_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    file_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
