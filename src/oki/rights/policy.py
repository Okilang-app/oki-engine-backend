from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from oki.rights.enums import (
    AgreementDecisionType,
    AssetScope,
    ConsentDecision,
    ContentFormat,
    CreatorApprovalPolicy,
    EndorsementMode,
    Platform,
    SponsorReplacementMode,
)
from oki.creators.models import CreatorChannel
from oki.rights.models import (
    AgreementDecision,
    EndorsementConsent,
    RightsAgreementVersion,
    RightsGrant,
    VoiceConsent,
)


class RightsDenialCode(StrEnum):
    AGREEMENT_MISSING = "agreement_missing"
    AGREEMENT_NOT_APPROVED = "agreement_not_approved"
    AGREEMENT_EXPIRED = "agreement_expired"
    AGREEMENT_REVOKED = "agreement_revoked"
    LANGUAGE_NOT_PERMITTED = "language_not_permitted"
    PLATFORM_NOT_PERMITTED = "platform_not_permitted"
    SHORTS_NOT_PERMITTED = "shorts_not_permitted"
    SPONSOR_REPLACEMENT_NOT_PERMITTED = "sponsor_replacement_not_permitted"
    VOICE_CLONE_CONSENT_MISSING = "voice_clone_consent_missing"
    ENDORSEMENT_NOT_PERMITTED = "endorsement_not_permitted"
    CREATOR_APPROVAL_MISSING = "creator_approval_missing"
    CHANNEL_NOT_AUTHORIZED = "channel_not_authorized"


@dataclass(frozen=True, slots=True)
class RightsRequest:
    organization_id: UUID
    creator_id: UUID
    language_code: str
    territory_code: str
    platform: Platform
    content_format: ContentFormat
    operation: str
    project_id: UUID | None = None
    asset_reference: str | None = None
    asset_category: str | None = None
    voice_mode: str | None = None
    sponsorship_action: str | None = None
    publication_channel_id: UUID | None = None
    creator_approved: bool = False


@dataclass(frozen=True, slots=True)
class RightsDecision:
    approved: bool
    reason_code: str
    reason_details: dict[str, Any]
    agreement_version_id: UUID | None = None
    evaluation_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class ApprovedRights:
    evaluation_id: UUID
    agreement_version_id: UUID


@dataclass(frozen=True, slots=True)
class AgreementSnapshot:
    version: RightsAgreementVersion | None
    grants: tuple[RightsGrant, ...]
    decisions: tuple[AgreementDecision, ...]
    voice_consents: tuple[VoiceConsent, ...]
    endorsement_consents: tuple[EndorsementConsent, ...]
    channels: tuple[CreatorChannel, ...]


class PolicyEvaluator:
    """Pure, I/O-free policy evaluator for Oki rights decisions."""

    @staticmethod
    def evaluate(
        snapshot: AgreementSnapshot, request: RightsRequest, now: datetime
    ) -> RightsDecision:
        version = snapshot.version
        if version is None:
            return RightsDecision(
                approved=False,
                reason_code=RightsDenialCode.AGREEMENT_MISSING,
                reason_details={},
            )

        approvals = [
            d for d in snapshot.decisions if d.decision == AgreementDecisionType.APPROVED
        ]
        if not approvals:
            return RightsDecision(
                approved=False,
                reason_code=RightsDenialCode.AGREEMENT_NOT_APPROVED,
                reason_details={},
                agreement_version_id=version.id,
            )

        if now > version.expires_at:
            return RightsDecision(
                approved=False,
                reason_code=RightsDenialCode.AGREEMENT_EXPIRED,
                reason_details={"expires_at": version.expires_at.isoformat()},
                agreement_version_id=version.id,
            )

        revocations = [
            d for d in snapshot.decisions if d.decision == AgreementDecisionType.REVOKED
        ]
        if revocations:
            last_approved = max(approvals, key=lambda d: d.decided_at)
            last_revoked = max(revocations, key=lambda d: d.decided_at)
            if last_revoked.decided_at >= last_approved.decided_at:
                return RightsDecision(
                    approved=False,
                    reason_code=RightsDenialCode.AGREEMENT_REVOKED,
                    reason_details={},
                    agreement_version_id=version.id,
                )

        lang_grants = [
            g for g in snapshot.grants if g.language_code == request.language_code
        ]
        if not lang_grants:
            return RightsDecision(
                approved=False,
                reason_code=RightsDenialCode.LANGUAGE_NOT_PERMITTED,
                reason_details={"language_code": request.language_code},
                agreement_version_id=version.id,
            )

        plat_grants = [g for g in lang_grants if g.platform == request.platform]
        if not plat_grants:
            return RightsDecision(
                approved=False,
                reason_code=RightsDenialCode.PLATFORM_NOT_PERMITTED,
                reason_details={"platform": request.platform.value},
                agreement_version_id=version.id,
            )

        fmt_grants = [
            g for g in plat_grants if g.content_format == request.content_format
        ]
        if not fmt_grants:
            return RightsDecision(
                approved=False,
                reason_code=RightsDenialCode.SHORTS_NOT_PERMITTED,
                reason_details={"content_format": request.content_format.value},
                agreement_version_id=version.id,
            )

        asset_grants: list[RightsGrant] = []
        for g in fmt_grants:
            if g.asset_scope == AssetScope.ALL:
                asset_grants.append(g)
            elif (
                g.asset_scope == AssetScope.CATEGORY
                and g.asset_reference == request.asset_category
            ):
                asset_grants.append(g)
            elif (
                g.asset_scope == AssetScope.ASSET
                and g.asset_reference == request.asset_reference
            ):
                asset_grants.append(g)

        if not asset_grants:
            return RightsDecision(
                approved=False,
                reason_code=RightsDenialCode.LANGUAGE_NOT_PERMITTED,
                reason_details={"asset_reference": request.asset_reference},
                agreement_version_id=version.id,
            )

        grant = asset_grants[0]

        if request.sponsorship_action == "replace":
            if grant.sponsor_replacement_mode == SponsorReplacementMode.NONE:
                return RightsDecision(
                    approved=False,
                    reason_code=RightsDenialCode.SPONSOR_REPLACEMENT_NOT_PERMITTED,
                    reason_details={
                        "sponsor_replacement_mode": grant.sponsor_replacement_mode.value
                    },
                    agreement_version_id=version.id,
                )

        if request.voice_mode == "clone" and grant.voice_clone_allowed:
            valid = [
                c
                for c in snapshot.voice_consents
                if c.decision == ConsentDecision.GRANTED
                and c.language_code == request.language_code
                and c.territory_code == request.territory_code
                and c.platform == request.platform
                and c.effective_from <= now <= c.expires_at
            ]
            if not valid:
                return RightsDecision(
                    approved=False,
                    reason_code=RightsDenialCode.VOICE_CLONE_CONSENT_MISSING,
                    reason_details={},
                    agreement_version_id=version.id,
                )
        elif request.voice_mode == "clone" and not grant.voice_clone_allowed:
            return RightsDecision(
                approved=False,
                reason_code=RightsDenialCode.VOICE_CLONE_CONSENT_MISSING,
                reason_details={},
                agreement_version_id=version.id,
            )

        if request.operation == "endorsement":
            if grant.endorsement_mode == EndorsementMode.NONE:
                return RightsDecision(
                    approved=False,
                    reason_code=RightsDenialCode.ENDORSEMENT_NOT_PERMITTED,
                    reason_details={"endorsement_mode": grant.endorsement_mode.value},
                    agreement_version_id=version.id,
                )
            valid = [
                c
                for c in snapshot.endorsement_consents
                if c.decision == ConsentDecision.GRANTED
                and c.language_code == request.language_code
                and c.territory_code == request.territory_code
                and c.platform == request.platform
                and c.effective_from <= now <= c.expires_at
            ]
            if not valid:
                return RightsDecision(
                    approved=False,
                    reason_code=RightsDenialCode.ENDORSEMENT_NOT_PERMITTED,
                    reason_details={},
                    agreement_version_id=version.id,
                )

        if grant.creator_approval_policy == CreatorApprovalPolicy.EVERY_PUBLICATION:
            if not request.creator_approved:
                return RightsDecision(
                    approved=False,
                    reason_code=RightsDenialCode.CREATOR_APPROVAL_MISSING,
                    reason_details={
                        "creator_approval_policy": grant.creator_approval_policy.value
                    },
                    agreement_version_id=version.id,
                )
        elif grant.creator_approval_policy == CreatorApprovalPolicy.FIRST_PER_LANGUAGE:
            if not request.creator_approved:
                return RightsDecision(
                    approved=False,
                    reason_code=RightsDenialCode.CREATOR_APPROVAL_MISSING,
                    reason_details={
                        "creator_approval_policy": grant.creator_approval_policy.value
                    },
                    agreement_version_id=version.id,
                )

        if request.publication_channel_id is not None:
            authorized = any(
                c.id == request.publication_channel_id for c in snapshot.channels
            )
            if not authorized:
                return RightsDecision(
                    approved=False,
                    reason_code=RightsDenialCode.CHANNEL_NOT_AUTHORIZED,
                    reason_details={
                        "publication_channel_id": str(request.publication_channel_id)
                    },
                    agreement_version_id=version.id,
                )

        return RightsDecision(
            approved=True,
            reason_code="rights_granted",
            reason_details={},
            agreement_version_id=version.id,
        )
