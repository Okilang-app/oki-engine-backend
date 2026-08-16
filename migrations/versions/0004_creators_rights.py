"""Create creator, channel ownership, agreement, grant, consent, and decision history.

Revision ID: 0004_creators_rights
Revises: 0003_identity_permissions
Create Date: 2026-08-15
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0004_creators_rights"
down_revision: str | None = "0003_identity_permissions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPLICATION_ROLE = "oki_app"
MUTABLE_NO_DELETE_TABLES = (
    "creators",
    "rights_agreements",
    "rights_agreement_versions",
)
APPEND_ONLY_TABLES = (
    "creator_channels",
    "channel_ownership_evidence",
    "creator_brand_guides",
    "creator_restrictions",
    "rights_grants",
    "voice_consents",
    "endorsement_consents",
    "agreement_decisions",
    "rights_evaluations",
)


def _id_column() -> sa.Column[object]:
    return sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuidv7()"))


def _created_at_column() -> sa.Column[object]:
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"))


def _mutable_columns() -> tuple[sa.Column[object], ...]:
    return (
        _created_at_column(),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )


def _organization_column() -> sa.Column[object]:
    return sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)


def _actor_column(name: str = "created_by_user_id") -> sa.Column[object]:
    return sa.Column(name, postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "creators", _id_column(), _organization_column(),
        sa.Column("legal_name", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("primary_email", sa.String(320), nullable=False),
        sa.Column("manager_name", sa.String(255), nullable=True),
        sa.Column("manager_email", sa.String(320), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        _actor_column(), *_mutable_columns(),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_creators_status"),
        sa.UniqueConstraint("organization_id", name="uq_creators_organization"),
    )
    op.create_index("ix_creators_organization_status", "creators", ["organization_id", "status"])

    op.create_table(
        "creator_channels", _id_column(), _organization_column(),
        sa.Column("creator_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("creators.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform", sa.String(30), nullable=False),
        sa.Column("external_channel_id", sa.String(255), nullable=False),
        sa.Column("handle", sa.String(255), nullable=True),
        sa.Column("canonical_url", sa.String(2048), nullable=False),
        _actor_column(), _created_at_column(),
        sa.CheckConstraint("platform IN ('youtube', 'youtube_music', 'instagram', 'tiktok', 'facebook', 'owned_web')", name="ck_creator_channels_platform"),
        sa.UniqueConstraint("platform", "external_channel_id", name="uq_creator_channels_platform_external"),
    )
    op.create_index("ix_creator_channels_creator", "creator_channels", ["creator_id", "created_at"])

    op.create_table(
        "channel_ownership_evidence", _id_column(), _organization_column(),
        sa.Column("creator_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("creators.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("creator_channels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("method", sa.String(100), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("evidence_reference", sa.String(1024), nullable=False),
        sa.Column("evidence_sha256", sa.String(64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        _actor_column("decided_by_user_id"), _created_at_column(),
        sa.CheckConstraint("decision IN ('granted', 'denied', 'revoked')", name="ck_channel_ownership_evidence_decision"),
        sa.CheckConstraint("evidence_sha256 ~ '^[0-9a-fA-F]{64}$'", name="ck_channel_ownership_evidence_sha256"),
    )
    op.create_index("ix_channel_ownership_channel_decided", "channel_ownership_evidence", ["channel_id", "decided_at"])

    op.create_table(
        "creator_brand_guides", _id_column(), _organization_column(),
        sa.Column("creator_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("creators.id", ondelete="CASCADE"), nullable=False),
        sa.Column("supersedes_brand_guide_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("creator_brand_guides.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("guide_reference", sa.String(1024), nullable=False),
        sa.Column("guide_sha256", sa.String(64), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        _actor_column(), _created_at_column(),
        sa.CheckConstraint("guide_sha256 ~ '^[0-9a-fA-F]{64}$'", name="ck_creator_brand_guides_sha256"),
    )
    op.create_index("ix_creator_brand_guides_creator", "creator_brand_guides", ["creator_id", "effective_from"])

    op.create_table(
        "creator_restrictions", _id_column(), _organization_column(),
        sa.Column("creator_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("creators.id", ondelete="CASCADE"), nullable=False),
        sa.Column("supersedes_restriction_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("creator_restrictions.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("restriction_type", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        _actor_column(), _created_at_column(),
        sa.CheckConstraint("expires_at IS NULL OR expires_at > effective_from", name="ck_creator_restrictions_effective_range"),
    )
    op.create_index("ix_creator_restrictions_creator", "creator_restrictions", ["creator_id", "effective_from"])

    op.create_table(
        "rights_agreements", _id_column(), _organization_column(),
        sa.Column("creator_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("creators.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("external_reference", sa.String(255), nullable=True),
        _actor_column(), *_mutable_columns(),
        sa.UniqueConstraint("organization_id", "external_reference", name="uq_rights_agreements_external_reference"),
    )
    op.create_index("ix_rights_agreements_creator", "rights_agreements", ["creator_id", "created_at"])

    op.create_table(
        "rights_agreement_versions", _id_column(), _organization_column(),
        sa.Column("agreement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rights_agreements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agreement_version_number", sa.Integer(), nullable=False),
        sa.Column("contract_reference", sa.String(1024), nullable=False),
        sa.Column("contract_sha256", sa.String(64), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("termination_notice_days", sa.Integer(), nullable=True),
        sa.Column("termination_terms", sa.Text(), nullable=False),
        sa.Column("monetization_mode", sa.String(30), nullable=False),
        sa.Column("fixed_fee_amount", sa.Numeric(20, 6), nullable=True),
        sa.Column("revenue_share_bps", sa.Numeric(10, 4), nullable=True),
        sa.Column("payout_currency", sa.String(3), nullable=False),
        sa.Column("payout_frequency", sa.String(100), nullable=False),
        sa.Column("payout_terms", sa.Text(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        _actor_column(), *_mutable_columns(),
        sa.CheckConstraint("contract_sha256 ~ '^[0-9a-fA-F]{64}$'", name="ck_rights_agreement_versions_sha256"),
        sa.CheckConstraint("expires_at > effective_from", name="ck_rights_agreement_versions_effective_range"),
        sa.CheckConstraint("termination_notice_days IS NULL OR termination_notice_days >= 0", name="ck_rights_agreement_versions_notice_nonnegative"),
        sa.CheckConstraint("monetization_mode IN ('none', 'fixed_fee', 'revenue_share', 'hybrid')", name="ck_rights_agreement_versions_monetization_mode"),
        sa.CheckConstraint("fixed_fee_amount IS NULL OR fixed_fee_amount >= 0", name="ck_rights_agreement_versions_fee_nonnegative"),
        sa.CheckConstraint("revenue_share_bps IS NULL OR (revenue_share_bps >= 0 AND revenue_share_bps <= 10000)", name="ck_rights_agreement_versions_revenue_share_range"),
        sa.UniqueConstraint("agreement_id", "agreement_version_number", name="uq_rights_agreement_versions_number"),
        sa.UniqueConstraint("agreement_id", "contract_sha256", name="uq_rights_agreement_versions_hash"),
    )
    op.create_index("ix_rights_agreement_versions_agreement", "rights_agreement_versions", ["agreement_id", "agreement_version_number"])

    op.create_table(
        "rights_grants", _id_column(), _organization_column(),
        sa.Column("agreement_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rights_agreement_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_scope", sa.String(20), nullable=False),
        sa.Column("asset_reference", sa.String(255), nullable=True),
        sa.Column("language_code", sa.String(16), nullable=False),
        sa.Column("territory_code", sa.String(3), nullable=False),
        sa.Column("platform", sa.String(30), nullable=False),
        sa.Column("content_format", sa.String(20), nullable=False),
        sa.Column("translation_allowed", sa.Boolean(), nullable=False),
        sa.Column("dubbing_allowed", sa.Boolean(), nullable=False),
        sa.Column("editing_allowed", sa.Boolean(), nullable=False),
        sa.Column("metadata_allowed", sa.Boolean(), nullable=False),
        sa.Column("likeness_allowed", sa.Boolean(), nullable=False),
        sa.Column("brand_use_allowed", sa.Boolean(), nullable=False),
        sa.Column("sponsor_removal_allowed", sa.Boolean(), nullable=False),
        sa.Column("sponsor_replacement_mode", sa.String(30), nullable=False),
        sa.Column("endorsement_mode", sa.String(30), nullable=False),
        sa.Column("voice_clone_allowed", sa.Boolean(), nullable=False),
        sa.Column("creator_approval_policy", sa.String(30), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        _actor_column(), _created_at_column(),
        sa.CheckConstraint("asset_scope IN ('all', 'category', 'asset')", name="ck_rights_grants_asset_scope"),
        sa.CheckConstraint("(asset_scope = 'all' AND asset_reference IS NULL) OR (asset_scope <> 'all' AND asset_reference IS NOT NULL)", name="ck_rights_grants_asset_scope_reference"),
        sa.CheckConstraint("platform IN ('youtube', 'youtube_music', 'instagram', 'tiktok', 'facebook', 'owned_web')", name="ck_rights_grants_platform"),
        sa.CheckConstraint("content_format IN ('full', 'shorts')", name="ck_rights_grants_content_format"),
        sa.CheckConstraint("sponsor_replacement_mode IN ('none', 'visual_only', 'voice_only', 'full')", name="ck_rights_grants_sponsor_replacement_mode"),
        sa.CheckConstraint("endorsement_mode IN ('none', 'neutral_disclosure', 'personal')", name="ck_rights_grants_endorsement_mode"),
        sa.CheckConstraint("creator_approval_policy IN ('not_required', 'first_per_language', 'every_publication')", name="ck_rights_grants_creator_approval_policy"),
        sa.CheckConstraint("ends_at > starts_at", name="ck_rights_grants_effective_range"),
        sa.CheckConstraint("sponsor_replacement_mode = 'none' OR sponsor_removal_allowed", name="ck_rights_grants_replacement_requires_removal"),
    )
    op.create_index("ix_rights_grants_evaluation", "rights_grants", ["agreement_version_id", "language_code", "territory_code", "platform", "content_format"])

    op.create_table(
        "voice_consents", _id_column(), _organization_column(),
        sa.Column("agreement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rights_agreements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agreement_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rights_agreement_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("supersedes_consent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("voice_consents.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("language_code", sa.String(16), nullable=False),
        sa.Column("territory_code", sa.String(3), nullable=False),
        sa.Column("platform", sa.String(30), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("evidence_reference", sa.String(1024), nullable=False),
        sa.Column("evidence_sha256", sa.String(64), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        _actor_column("decided_by_user_id"), _created_at_column(),
        sa.CheckConstraint("decision IN ('granted', 'denied', 'revoked')", name="ck_voice_consents_decision"),
        sa.CheckConstraint("platform IN ('youtube', 'youtube_music', 'instagram', 'tiktok', 'facebook', 'owned_web')", name="ck_voice_consents_platform"),
        sa.CheckConstraint("evidence_sha256 ~ '^[0-9a-fA-F]{64}$'", name="ck_voice_consents_sha256"),
        sa.CheckConstraint("expires_at > effective_from", name="ck_voice_consents_effective_range"),
    )
    op.create_index("ix_voice_consents_agreement_version", "voice_consents", ["agreement_version_id", "created_at"])

    op.create_table(
        "endorsement_consents", _id_column(), _organization_column(),
        sa.Column("agreement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rights_agreements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agreement_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rights_agreement_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("supersedes_consent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("endorsement_consents.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("language_code", sa.String(16), nullable=False),
        sa.Column("territory_code", sa.String(3), nullable=False),
        sa.Column("platform", sa.String(30), nullable=False),
        sa.Column("approved_language", sa.Text(), nullable=False),
        sa.Column("evidence_reference", sa.String(1024), nullable=False),
        sa.Column("evidence_sha256", sa.String(64), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        _actor_column("decided_by_user_id"), _created_at_column(),
        sa.CheckConstraint("decision IN ('granted', 'denied', 'revoked')", name="ck_endorsement_consents_decision"),
        sa.CheckConstraint("platform IN ('youtube', 'youtube_music', 'instagram', 'tiktok', 'facebook', 'owned_web')", name="ck_endorsement_consents_platform"),
        sa.CheckConstraint("evidence_sha256 ~ '^[0-9a-fA-F]{64}$'", name="ck_endorsement_consents_sha256"),
        sa.CheckConstraint("expires_at > effective_from", name="ck_endorsement_consents_effective_range"),
    )
    op.create_index("ix_endorsement_consents_agreement_version", "endorsement_consents", ["agreement_version_id", "created_at"])

    op.create_table(
        "agreement_decisions", _id_column(), _organization_column(),
        sa.Column("agreement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rights_agreements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agreement_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rights_agreement_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        _actor_column("decided_by_user_id"),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        _created_at_column(),
        sa.CheckConstraint("decision IN ('approved', 'revoked', 'expired', 'superseded')", name="ck_agreement_decisions_decision"),
        sa.UniqueConstraint("agreement_version_id", "decision", name="uq_agreement_decisions_version_decision"),
    )
    op.create_index("ix_agreement_decisions_agreement_decided", "agreement_decisions", ["agreement_id", "decided_at"])

    op.create_table(
        "rights_evaluations", _id_column(), _organization_column(),
        sa.Column("creator_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("creators.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("asset_reference", sa.String(255), nullable=True),
        sa.Column("asset_category", sa.String(255), nullable=True),
        sa.Column("language_code", sa.String(16), nullable=False),
        sa.Column("territory_code", sa.String(3), nullable=False),
        sa.Column("platform", sa.String(30), nullable=False),
        sa.Column("content_format", sa.String(20), nullable=False),
        sa.Column("operation", sa.String(100), nullable=False),
        sa.Column("voice_mode", sa.String(100), nullable=True),
        sa.Column("sponsorship_action", sa.String(100), nullable=True),
        sa.Column("publication_channel_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("creator_channels.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved", sa.Boolean(), nullable=False),
        sa.Column("reason_code", sa.String(150), nullable=False),
        sa.Column("reason_details", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("agreement_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rights_agreement_versions.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        _created_at_column(),
        sa.CheckConstraint("platform IN ('youtube', 'youtube_music', 'instagram', 'tiktok', 'facebook', 'owned_web')", name="ck_rights_evaluations_platform"),
        sa.CheckConstraint("content_format IN ('full', 'shorts')", name="ck_rights_evaluations_content_format"),
        sa.CheckConstraint("approved = false OR agreement_version_id IS NOT NULL", name="ck_rights_evaluations_approved_version"),
    )
    op.create_index("ix_rights_evaluations_creator_evaluated", "rights_evaluations", ["creator_id", "evaluated_at"])
    op.create_index("ix_rights_evaluations_correlation", "rights_evaluations", ["correlation_id"])

    op.execute("""
        CREATE FUNCTION reject_submitted_agreement_version_update()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.submitted_at IS NOT NULL THEN
                RAISE EXCEPTION 'submitted agreement versions are immutable' USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER rights_agreement_versions_immutable_after_submission
        BEFORE UPDATE ON rights_agreement_versions
        FOR EACH ROW EXECUTE FUNCTION reject_submitted_agreement_version_update()
    """)
    op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APPLICATION_ROLE}') THEN
                EXECUTE 'GRANT SELECT, INSERT, UPDATE ON TABLE {", ".join(MUTABLE_NO_DELETE_TABLES)} TO {APPLICATION_ROLE}';
                EXECUTE 'GRANT SELECT, INSERT ON TABLE {", ".join(APPEND_ONLY_TABLES)} TO {APPLICATION_ROLE}';
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    op.execute("DROP FUNCTION reject_submitted_agreement_version_update() CASCADE")
    for table_name in (
        "rights_evaluations", "agreement_decisions", "endorsement_consents", "voice_consents",
        "rights_grants", "rights_agreement_versions", "rights_agreements", "creator_restrictions",
        "creator_brand_guides", "channel_ownership_evidence", "creator_channels", "creators",
    ):
        op.drop_table(table_name)
