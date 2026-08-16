from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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

from oki.creators.models import CreatedAtMixin
from oki.db.base import Base
from oki.db.mixins import TimestampMixin, VersionMixin
from oki.rights.enums import (
    AgreementDecisionType,
    AssetScope,
    ConsentDecision,
    ContentFormat,
    CreatorApprovalPolicy,
    EndorsementMode,
    MonetizationMode,
    Platform,
    SponsorReplacementMode,
)


def _enum_values(enum_type: type[Any]) -> list[str]:
    return [member.value for member in enum_type]


def _enum_type(enum_type: type[Any], name: str) -> Enum:
    return Enum(
        enum_type,
        name=name,
        native_enum=False,
        create_constraint=False,
        validate_strings=True,
        values_callable=_enum_values,
    )


ASSET_SCOPE_TYPE = _enum_type(AssetScope, "rights_asset_scope")
PLATFORM_TYPE = _enum_type(Platform, "rights_platform")
CONTENT_FORMAT_TYPE = _enum_type(ContentFormat, "rights_content_format")
SPONSOR_REPLACEMENT_TYPE = _enum_type(
    SponsorReplacementMode, "rights_sponsor_replacement_mode"
)
ENDORSEMENT_MODE_TYPE = _enum_type(EndorsementMode, "rights_endorsement_mode")
APPROVAL_POLICY_TYPE = _enum_type(CreatorApprovalPolicy, "rights_creator_approval_policy")
MONETIZATION_MODE_TYPE = _enum_type(MonetizationMode, "rights_monetization_mode")
AGREEMENT_DECISION_TYPE = _enum_type(AgreementDecisionType, "agreement_decision_type")
CONSENT_DECISION_TYPE = _enum_type(ConsentDecision, "consent_decision")


class RightsAgreement(TimestampMixin, VersionMixin, Base):
    __tablename__ = "rights_agreements"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "external_reference", name="uq_rights_agreements_external_reference"
        ),
        Index("ix_rights_agreements_creator", "creator_id", "created_at"),
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
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    external_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


class RightsAgreementVersion(TimestampMixin, VersionMixin, Base):
    __tablename__ = "rights_agreement_versions"
    __table_args__ = (
        UniqueConstraint(
            "agreement_id", "agreement_version_number", name="uq_rights_agreement_versions_number"
        ),
        UniqueConstraint("agreement_id", "contract_sha256", name="uq_rights_agreement_versions_hash"),
        CheckConstraint(
            "expires_at > effective_from", name="ck_rights_agreement_versions_effective_range"
        ),
        CheckConstraint(
            "termination_notice_days IS NULL OR termination_notice_days >= 0",
            name="ck_rights_agreement_versions_notice_nonnegative",
        ),
        CheckConstraint(
            "fixed_fee_amount IS NULL OR fixed_fee_amount >= 0",
            name="ck_rights_agreement_versions_fee_nonnegative",
        ),
        CheckConstraint(
            "revenue_share_bps IS NULL OR (revenue_share_bps >= 0 AND revenue_share_bps <= 10000)",
            name="ck_rights_agreement_versions_revenue_share_range",
        ),
        Index("ix_rights_agreement_versions_agreement", "agreement_id", "agreement_version_number"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    agreement_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("rights_agreements.id", ondelete="CASCADE"),
        nullable=False,
    )
    agreement_version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    contract_reference: Mapped[str] = mapped_column(String(1024), nullable=False)
    contract_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    termination_notice_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    termination_terms: Mapped[str] = mapped_column(Text, nullable=False)
    monetization_mode: Mapped[MonetizationMode] = mapped_column(
        MONETIZATION_MODE_TYPE, nullable=False
    )
    fixed_fee_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    revenue_share_bps: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    payout_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    payout_frequency: Mapped[str] = mapped_column(String(100), nullable=False)
    payout_terms: Mapped[str] = mapped_column(Text, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


class RightsGrant(CreatedAtMixin, Base):
    __tablename__ = "rights_grants"
    __table_args__ = (
        CheckConstraint(
            "(asset_scope = 'all' AND asset_reference IS NULL) OR "
            "(asset_scope <> 'all' AND asset_reference IS NOT NULL)",
            name="ck_rights_grants_asset_scope_reference",
        ),
        CheckConstraint("ends_at > starts_at", name="ck_rights_grants_effective_range"),
        CheckConstraint(
            "sponsor_replacement_mode = 'none' OR sponsor_removal_allowed",
            name="ck_rights_grants_replacement_requires_removal",
        ),
        Index(
            "ix_rights_grants_evaluation",
            "agreement_version_id",
            "language_code",
            "territory_code",
            "platform",
            "content_format",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    agreement_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("rights_agreement_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    asset_scope: Mapped[AssetScope] = mapped_column(ASSET_SCOPE_TYPE, nullable=False)
    asset_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    language_code: Mapped[str] = mapped_column(String(16), nullable=False)
    territory_code: Mapped[str] = mapped_column(String(3), nullable=False)
    platform: Mapped[Platform] = mapped_column(PLATFORM_TYPE, nullable=False)
    content_format: Mapped[ContentFormat] = mapped_column(CONTENT_FORMAT_TYPE, nullable=False)
    translation_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    dubbing_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    editing_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    metadata_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    likeness_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    brand_use_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    sponsor_removal_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    sponsor_replacement_mode: Mapped[SponsorReplacementMode] = mapped_column(
        SPONSOR_REPLACEMENT_TYPE, nullable=False
    )
    endorsement_mode: Mapped[EndorsementMode] = mapped_column(ENDORSEMENT_MODE_TYPE, nullable=False)
    voice_clone_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    creator_approval_policy: Mapped[CreatorApprovalPolicy] = mapped_column(
        APPROVAL_POLICY_TYPE, nullable=False
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


class VoiceConsent(CreatedAtMixin, Base):
    __tablename__ = "voice_consents"
    __table_args__ = (
        CheckConstraint("expires_at > effective_from", name="ck_voice_consents_effective_range"),
        Index("ix_voice_consents_agreement_version", "agreement_version_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    agreement_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("rights_agreements.id", ondelete="CASCADE"), nullable=False
    )
    agreement_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("rights_agreement_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    decision: Mapped[ConsentDecision] = mapped_column(CONSENT_DECISION_TYPE, nullable=False)
    supersedes_consent_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("voice_consents.id", ondelete="RESTRICT"), nullable=True
    )
    language_code: Mapped[str] = mapped_column(String(16), nullable=False)
    territory_code: Mapped[str] = mapped_column(String(3), nullable=False)
    platform: Mapped[Platform] = mapped_column(PLATFORM_TYPE, nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_reference: Mapped[str] = mapped_column(String(1024), nullable=False)
    evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_by_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


class EndorsementConsent(CreatedAtMixin, Base):
    __tablename__ = "endorsement_consents"
    __table_args__ = (
        CheckConstraint(
            "expires_at > effective_from", name="ck_endorsement_consents_effective_range"
        ),
        Index("ix_endorsement_consents_agreement_version", "agreement_version_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    agreement_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("rights_agreements.id", ondelete="CASCADE"), nullable=False
    )
    agreement_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("rights_agreement_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    decision: Mapped[ConsentDecision] = mapped_column(CONSENT_DECISION_TYPE, nullable=False)
    supersedes_consent_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("endorsement_consents.id", ondelete="RESTRICT"),
        nullable=True,
    )
    language_code: Mapped[str] = mapped_column(String(16), nullable=False)
    territory_code: Mapped[str] = mapped_column(String(3), nullable=False)
    platform: Mapped[Platform] = mapped_column(PLATFORM_TYPE, nullable=False)
    approved_language: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_reference: Mapped[str] = mapped_column(String(1024), nullable=False)
    evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_by_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


class AgreementDecision(CreatedAtMixin, Base):
    __tablename__ = "agreement_decisions"
    __table_args__ = (
        UniqueConstraint(
            "agreement_version_id", "decision", name="uq_agreement_decisions_version_decision"
        ),
        Index("ix_agreement_decisions_agreement_decided", "agreement_id", "decided_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    agreement_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("rights_agreements.id", ondelete="CASCADE"), nullable=False
    )
    agreement_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("rights_agreement_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    decision: Mapped[AgreementDecisionType] = mapped_column(
        AGREEMENT_DECISION_TYPE, nullable=False
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    correlation_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)


class RightsEvaluation(CreatedAtMixin, Base):
    __tablename__ = "rights_evaluations"
    __table_args__ = (
        Index("ix_rights_evaluations_creator_evaluated", "creator_id", "evaluated_at"),
        Index("ix_rights_evaluations_correlation", "correlation_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    creator_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("creators.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    asset_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    asset_category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    language_code: Mapped[str] = mapped_column(String(16), nullable=False)
    territory_code: Mapped[str] = mapped_column(String(3), nullable=False)
    platform: Mapped[Platform] = mapped_column(PLATFORM_TYPE, nullable=False)
    content_format: Mapped[ContentFormat] = mapped_column(CONTENT_FORMAT_TYPE, nullable=False)
    operation: Mapped[str] = mapped_column(String(100), nullable=False)
    voice_mode: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sponsorship_action: Mapped[str | None] = mapped_column(String(100), nullable=True)
    publication_channel_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("creator_channels.id", ondelete="SET NULL"),
        nullable=True,
    )
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason_code: Mapped[str] = mapped_column(String(150), nullable=False)
    reason_details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    agreement_version_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("rights_agreement_versions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    correlation_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = {"extend_existing": True}

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=True
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String(150), nullable=False)
    previous_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    new_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    request_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
