"""Internal ad creative models."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from oki.db.base import Base
from oki.db.mixins import TimestampMixin


class InternalAd(TimestampMixin, Base):
    __tablename__ = "internal_ads"
    __table_args__ = (
        Index("ix_internal_ads_org_created", "organization_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    duration_seconds: Mapped[int | None] = mapped_column(nullable=True)
    created_by_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # SOW Section 8.9 creative metadata
    format: Mapped[str | None] = mapped_column(String(64), nullable=True)
    language_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    audience: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cta: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    landing_page: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    promo_code: Mapped[str | None] = mapped_column(String(255), nullable=True)
    territory_codes: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    campaign_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    campaign_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_claims: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    prohibited_claims: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    disclosure_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    endorsement_mode: Mapped[str | None] = mapped_column(
        String(64), nullable=True, server_default="neutral_disclosure"
    )
    endorsement_approved: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default=text("false")
    )
