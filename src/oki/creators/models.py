from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from oki.db.base import Base
from oki.db.mixins import TimestampMixin, VersionMixin
from oki.jobs import models as _jobs_models  # register organizations/projects FK targets
from oki.identity import models as _identity_models  # register users/organizations FK targets
from oki.rights.enums import ConsentDecision, CreatorStatus, Platform


def _enum_values(enum_type: type[Any]) -> list[str]:
    return [member.value for member in enum_type]


PLATFORM_TYPE = Enum(
    Platform,
    name="rights_platform",
    native_enum=False,
    create_constraint=False,
    validate_strings=True,
    values_callable=_enum_values,
)
CONSENT_DECISION_TYPE = Enum(
    ConsentDecision,
    name="consent_decision",
    native_enum=False,
    create_constraint=False,
    validate_strings=True,
    values_callable=_enum_values,
)
CREATOR_STATUS_TYPE = Enum(
    CreatorStatus,
    name="creator_status",
    native_enum=False,
    create_constraint=False,
    validate_strings=True,
    values_callable=_enum_values,
)


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Creator(TimestampMixin, VersionMixin, Base):
    __tablename__ = "creators"
    __table_args__ = (
        UniqueConstraint("organization_id", name="uq_creators_organization"),
        Index("ix_creators_organization_status", "organization_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    legal_name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    primary_email: Mapped[str] = mapped_column(String(320), nullable=False)
    manager_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    manager_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    status: Mapped[CreatorStatus] = mapped_column(
        CREATOR_STATUS_TYPE,
        nullable=False,
        default=CreatorStatus.ACTIVE,
        server_default=CreatorStatus.ACTIVE.value,
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )


class CreatorChannel(CreatedAtMixin, Base):
    __tablename__ = "creator_channels"
    __table_args__ = (
        UniqueConstraint(
            "platform", "external_channel_id", name="uq_creator_channels_platform_external"
        ),
        Index("ix_creator_channels_creator", "creator_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    creator_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("creators.id", ondelete="CASCADE"),
        nullable=False,
    )
    platform: Mapped[Platform] = mapped_column(PLATFORM_TYPE, nullable=False)
    external_channel_id: Mapped[str] = mapped_column(String(255), nullable=False)
    handle: Mapped[str | None] = mapped_column(String(255), nullable=True)
    canonical_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    created_by_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )


class ChannelOwnershipEvidence(CreatedAtMixin, Base):
    __tablename__ = "channel_ownership_evidence"
    __table_args__ = (
        Index("ix_channel_ownership_channel_decided", "channel_id", "decided_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    creator_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("creators.id", ondelete="CASCADE"),
        nullable=False,
    )
    channel_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("creator_channels.id", ondelete="CASCADE"),
        nullable=False,
    )
    method: Mapped[str] = mapped_column(String(100), nullable=False)
    decision: Mapped[ConsentDecision] = mapped_column(CONSENT_DECISION_TYPE, nullable=False)
    evidence_reference: Mapped[str] = mapped_column(String(1024), nullable=False)
    evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )


class CreatorBrandGuide(CreatedAtMixin, Base):
    __tablename__ = "creator_brand_guides"
    __table_args__ = (Index("ix_creator_brand_guides_creator", "creator_id", "effective_from"),)

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    creator_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("creators.id", ondelete="CASCADE"),
        nullable=False,
    )
    supersedes_brand_guide_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("creator_brand_guides.id", ondelete="RESTRICT"),
        nullable=True,
    )
    guide_reference: Mapped[str] = mapped_column(String(1024), nullable=False)
    guide_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


class CreatorRestriction(CreatedAtMixin, Base):
    __tablename__ = "creator_restrictions"
    __table_args__ = (Index("ix_creator_restrictions_creator", "creator_id", "effective_from"),)

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    creator_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("creators.id", ondelete="CASCADE"),
        nullable=False,
    )
    supersedes_restriction_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("creator_restrictions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    restriction_type: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
