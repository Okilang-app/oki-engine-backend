from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from oki.db.base import Base
from oki.db.mixins import TimestampMixin, VersionMixin
from oki.campaigns.enums import CreativeStatus, CreativeType


def _enum_values(enum_type: type[Any]) -> list[str]:
    return [member.value for member in enum_type]


CREATIVE_TYPE_TYPE = Enum(
    CreativeType,
    name="creative_type",
    native_enum=False,
    create_constraint=False,
    validate_strings=True,
    values_callable=_enum_values,
)
CREATIVE_STATUS_TYPE = Enum(
    CreativeStatus,
    name="creative_status",
    native_enum=False,
    create_constraint=False,
    validate_strings=True,
    values_callable=_enum_values,
)


class Campaign(TimestampMixin, VersionMixin, Base):
    __tablename__ = "campaigns"
    __table_args__ = (
        Index("ix_campaigns_organization", "organization_id"),
        Index("ix_campaigns_dates", "starts_at", "ends_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    starts_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    ends_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    budget_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    budget_amount: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    meta: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


class CampaignVersion(TimestampMixin, VersionMixin, Base):
    __tablename__ = "campaign_versions"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id", "version_number", name="uq_campaign_versions_number"
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    campaign_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    changes_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


class Creative(TimestampMixin, VersionMixin, Base):
    __tablename__ = "creatives"
    __table_args__ = (
        Index("ix_creatives_campaign", "campaign_id"),
        Index("ix_creatives_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    campaign_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    creative_type: Mapped[CreativeType] = mapped_column(
        CREATIVE_TYPE_TYPE, nullable=False
    )
    status: Mapped[CreativeStatus] = mapped_column(
        CREATIVE_STATUS_TYPE, nullable=False, default=CreativeStatus.DRAFT
    )
    language_code: Mapped[str] = mapped_column(String(16), nullable=False)
    territory_code: Mapped[str] = mapped_column(String(3), nullable=False)
    sponsor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sponsor_product: Mapped[str | None] = mapped_column(String(255), nullable=True)
    script_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    visual_reference_url: Mapped[str | None] = mapped_column(
        String(2048), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    meta: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


class CreativeVersion(TimestampMixin, VersionMixin, Base):
    __tablename__ = "creative_versions"
    __table_args__ = (
        UniqueConstraint(
            "creative_id", "version_number", name="uq_creative_versions_number"
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    creative_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("creatives.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    changes_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


class AttributionKey(TimestampMixin, Base):
    __tablename__ = "attribution_keys"
    __table_args__ = (
        UniqueConstraint(
            "creative_id", "key_type", "key_value", name="uq_attribution_keys_type_value"
        ),
        Index("ix_attribution_keys_campaign", "campaign_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    campaign_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    creative_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("creatives.id", ondelete="CASCADE"),
        nullable=False,
    )
    key_type: Mapped[str] = mapped_column(String(50), nullable=False)
    key_value: Mapped[str] = mapped_column(String(255), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    meta: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
