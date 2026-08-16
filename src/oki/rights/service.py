from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, NoReturn
from uuid import UUID

from sqlalchemy import func, select

from oki.api.errors import ProblemException
from oki.creators.models import Creator
from oki.creators.service import add_mutation_evidence
from oki.db.uow import UnitOfWork
from oki.identity.authorization import Authorizer
from oki.identity.enums import Action
from oki.identity.schemas import Principal, ResourceScope
from oki.rights.enums import AgreementDecisionType
from oki.rights.models import (
    AgreementDecision,
    EndorsementConsent,
    RightsAgreement,
    RightsAgreementVersion,
    RightsGrant,
    VoiceConsent,
)
from oki.rights.schemas import AgreementCreate, EndorsementConsentCreate, VoiceConsentCreate


@dataclass(frozen=True, slots=True)
class AgreementDetails:
    agreement: RightsAgreement
    version: RightsAgreementVersion
    grants: tuple[RightsGrant, ...]


class AgreementService:
    def __init__(self, uow_factory: Callable[[], UnitOfWork], authorizer: Authorizer) -> None:
        self._uow_factory = uow_factory
        self._authorizer = authorizer

    async def create_version(
        self,
        principal: Principal,
        creator_id: UUID,
        payload: AgreementCreate,
        *,
        correlation_id: UUID,
    ) -> tuple[RightsAgreement, RightsAgreementVersion]:
        async with self._uow_factory() as uow:
            creator = await uow.session.get(Creator, creator_id)
            if creator is None:
                self._not_found("creator_not_found", "Creator not found")
            self._authorizer.require(
                principal,
                Action.AGREEMENT_CREATE,
                self._scope(creator.organization_id),
            )

            if payload.agreement_id is None:
                agreement = RightsAgreement(
                    organization_id=creator.organization_id,
                    creator_id=creator.id,
                    title=payload.title,
                    external_reference=payload.external_reference,
                    created_by_user_id=principal.user_id,
                )
                uow.session.add(agreement)
                await uow.session.flush()
                version_number = 1
            else:
                agreement = await uow.session.scalar(
                    select(RightsAgreement)
                    .where(RightsAgreement.id == payload.agreement_id)
                    .with_for_update()
                )
                if agreement is None:
                    self._not_found("agreement_not_found", "Agreement not found")
                if agreement.creator_id != creator.id:
                    raise ProblemException(
                        status_code=403,
                        code="resource_scope_denied",
                        title="Forbidden",
                        detail="The agreement does not belong to the requested creator.",
                    )
                latest_number = await uow.session.scalar(
                    select(func.max(RightsAgreementVersion.agreement_version_number)).where(
                        RightsAgreementVersion.agreement_id == agreement.id
                    )
                )
                version_number = int(latest_number or 0) + 1

            data = payload.version
            version = RightsAgreementVersion(
                organization_id=creator.organization_id,
                agreement_id=agreement.id,
                agreement_version_number=version_number,
                contract_reference=data.contract_reference,
                contract_sha256=data.contract_sha256.lower(),
                effective_from=data.effective_from,
                expires_at=data.expires_at,
                termination_notice_days=data.termination_notice_days,
                termination_terms=data.termination_terms,
                monetization_mode=data.monetization_mode,
                fixed_fee_amount=data.fixed_fee_amount,
                revenue_share_bps=data.revenue_share_bps,
                payout_currency=data.payout_currency.upper(),
                payout_frequency=data.payout_frequency,
                payout_terms=data.payout_terms,
                created_by_user_id=principal.user_id,
            )
            uow.session.add(version)
            await uow.session.flush()
            for grant in data.grants:
                uow.session.add(
                    RightsGrant(
                        organization_id=creator.organization_id,
                        agreement_version_id=version.id,
                        asset_scope=grant.asset_scope,
                        asset_reference=grant.asset_reference,
                        language_code=grant.language_code.lower(),
                        territory_code=grant.territory_code.upper(),
                        platform=grant.platform,
                        content_format=grant.content_format,
                        translation_allowed=grant.translation_allowed,
                        dubbing_allowed=grant.dubbing_allowed,
                        editing_allowed=grant.editing_allowed,
                        metadata_allowed=grant.metadata_allowed,
                        likeness_allowed=grant.likeness_allowed,
                        brand_use_allowed=grant.brand_use_allowed,
                        sponsor_removal_allowed=grant.sponsor_removal_allowed,
                        sponsor_replacement_mode=grant.sponsor_replacement_mode,
                        endorsement_mode=grant.endorsement_mode,
                        voice_clone_allowed=grant.voice_clone_allowed,
                        creator_approval_policy=grant.creator_approval_policy,
                        starts_at=grant.starts_at,
                        ends_at=grant.ends_at,
                        created_by_user_id=principal.user_id,
                    )
                )
            add_mutation_evidence(
                uow,
                principal=principal,
                organization_id=creator.organization_id,
                entity_type="rights_agreement_version",
                entity_id=version.id,
                action="agreement.version_created",
                correlation_id=correlation_id,
                new_values={
                    "agreement_id": str(agreement.id),
                    "agreement_version_id": str(version.id),
                    "agreement_version_number": version_number,
                    "contract_sha256": version.contract_sha256,
                    "grant_count": len(data.grants),
                },
            )
            await uow.session.flush()
            return agreement, version

    async def update_version(
        self,
        principal: Principal,
        version_id: UUID,
        changes: dict[str, Any],
        *,
        correlation_id: UUID,
    ) -> RightsAgreementVersion:
        async with self._uow_factory() as uow:
            version = await uow.session.scalar(
                select(RightsAgreementVersion)
                .where(RightsAgreementVersion.id == version_id)
                .with_for_update()
            )
            if version is None:
                self._not_found("agreement_version_not_found", "Agreement version not found")
            _, creator = await self._agreement_and_creator(uow, version.agreement_id)
            self._authorizer.require(
                principal, Action.AGREEMENT_CREATE, self._scope(creator.organization_id)
            )
            decided = await uow.session.scalar(
                select(AgreementDecision.id).where(
                    AgreementDecision.agreement_version_id == version.id
                )
            )
            if version.submitted_at is not None or decided is not None:
                raise ProblemException(
                    status_code=409,
                    code="agreement_version_immutable",
                    title="Agreement version is immutable",
                    detail="Submitted or decided agreement versions cannot be edited.",
                )
            allowed_fields = {
                "contract_reference",
                "contract_sha256",
                "effective_from",
                "expires_at",
                "termination_notice_days",
                "termination_terms",
                "monetization_mode",
                "fixed_fee_amount",
                "revenue_share_bps",
                "payout_currency",
                "payout_frequency",
                "payout_terms",
            }
            if changes.keys() - allowed_fields:
                raise ProblemException(
                    status_code=422,
                    code="agreement_version_field_invalid",
                    title="Agreement version field is invalid",
                    detail="Only explicit agreement-version terms may be edited.",
                )
            previous = {name: str(getattr(version, name)) for name in changes}
            for name, value in changes.items():
                setattr(version, name, value)
            add_mutation_evidence(
                uow,
                principal=principal,
                organization_id=creator.organization_id,
                entity_type="rights_agreement_version",
                entity_id=version.id,
                action="agreement.version_updated",
                correlation_id=correlation_id,
                previous_values=previous,
                new_values={name: str(value) for name, value in changes.items()},
            )
            await uow.session.flush()
            return version

    async def approve(
        self,
        principal: Principal,
        agreement_id: UUID,
        *,
        reason: str | None = None,
        agreement_version_id: UUID | None = None,
        correlation_id: UUID,
    ) -> AgreementDecision:
        return await self._record_decision(
            principal,
            agreement_id,
            action=Action.AGREEMENT_APPROVE,
            decision=AgreementDecisionType.APPROVED,
            reason=reason,
            agreement_version_id=agreement_version_id,
            correlation_id=correlation_id,
        )

    async def revoke(
        self,
        principal: Principal,
        agreement_id: UUID,
        *,
        reason: str | None = None,
        agreement_version_id: UUID | None = None,
        correlation_id: UUID,
    ) -> AgreementDecision:
        return await self._record_decision(
            principal,
            agreement_id,
            action=Action.AGREEMENT_REVOKE,
            decision=AgreementDecisionType.REVOKED,
            reason=reason,
            agreement_version_id=agreement_version_id,
            correlation_id=correlation_id,
        )

    async def record_voice_consent(
        self,
        principal: Principal,
        agreement_id: UUID,
        payload: VoiceConsentCreate,
        *,
        correlation_id: UUID,
    ) -> VoiceConsent:
        async with self._uow_factory() as uow:
            agreement, creator = await self._agreement_and_creator(uow, agreement_id)
            self._authorizer.require(
                principal, Action.VOICE_CONSENT_RECORD, self._scope(creator.organization_id)
            )
            await self._require_version(uow, agreement.id, payload.agreement_version_id)
            if payload.supersedes_consent_id is not None:
                superseded = await uow.session.get(VoiceConsent, payload.supersedes_consent_id)
                if superseded is None or superseded.agreement_id != agreement.id:
                    self._not_found("voice_consent_not_found", "Voice consent not found")
            consent = VoiceConsent(
                organization_id=creator.organization_id,
                agreement_id=agreement.id,
                agreement_version_id=payload.agreement_version_id,
                decision=payload.decision,
                supersedes_consent_id=payload.supersedes_consent_id,
                language_code=payload.language_code.lower(),
                territory_code=payload.territory_code.upper(),
                platform=payload.platform,
                provider=payload.provider,
                purpose=payload.purpose,
                evidence_reference=payload.evidence_reference,
                evidence_sha256=payload.evidence_sha256.lower(),
                effective_from=payload.effective_from,
                expires_at=payload.expires_at,
                decided_by_user_id=principal.user_id,
            )
            uow.session.add(consent)
            await uow.session.flush()
            add_mutation_evidence(
                uow,
                principal=principal,
                organization_id=creator.organization_id,
                entity_type="voice_consent",
                entity_id=consent.id,
                action="voice_consent.recorded",
                correlation_id=correlation_id,
                new_values={
                    "agreement_id": str(agreement.id),
                    "agreement_version_id": str(payload.agreement_version_id),
                    "decision": payload.decision.value,
                    "provider": payload.provider,
                    "purpose": payload.purpose,
                },
            )
            await uow.session.flush()
            return consent

    async def record_endorsement_consent(
        self,
        principal: Principal,
        agreement_id: UUID,
        payload: EndorsementConsentCreate,
        *,
        correlation_id: UUID,
    ) -> EndorsementConsent:
        async with self._uow_factory() as uow:
            agreement, creator = await self._agreement_and_creator(uow, agreement_id)
            self._authorizer.require(
                principal, Action.AGREEMENT_APPROVE, self._scope(creator.organization_id)
            )
            await self._require_version(uow, agreement.id, payload.agreement_version_id)
            if payload.supersedes_consent_id is not None:
                superseded = await uow.session.get(
                    EndorsementConsent, payload.supersedes_consent_id
                )
                if superseded is None or superseded.agreement_id != agreement.id:
                    self._not_found(
                        "endorsement_consent_not_found", "Endorsement consent not found"
                    )
            consent = EndorsementConsent(
                organization_id=creator.organization_id,
                agreement_id=agreement.id,
                agreement_version_id=payload.agreement_version_id,
                decision=payload.decision,
                supersedes_consent_id=payload.supersedes_consent_id,
                language_code=payload.language_code.lower(),
                territory_code=payload.territory_code.upper(),
                platform=payload.platform,
                approved_language=payload.approved_language,
                evidence_reference=payload.evidence_reference,
                evidence_sha256=payload.evidence_sha256.lower(),
                effective_from=payload.effective_from,
                expires_at=payload.expires_at,
                decided_by_user_id=principal.user_id,
            )
            uow.session.add(consent)
            await uow.session.flush()
            add_mutation_evidence(
                uow,
                principal=principal,
                organization_id=creator.organization_id,
                entity_type="endorsement_consent",
                entity_id=consent.id,
                action="endorsement_consent.recorded",
                correlation_id=correlation_id,
                new_values={
                    "agreement_id": str(agreement.id),
                    "agreement_version_id": str(payload.agreement_version_id),
                    "decision": payload.decision.value,
                    "approved_language": payload.approved_language,
                },
            )
            await uow.session.flush()
            return consent

    async def get_details(self, principal: Principal, agreement_id: UUID) -> AgreementDetails:
        async with self._uow_factory() as uow:
            agreement, creator = await self._agreement_and_creator(uow, agreement_id)
            self._authorizer.require(
                principal, Action.CREATOR_READ, self._scope(creator.organization_id)
            )
            version = await self._latest_version(uow, agreement.id)
            grants = tuple(
                await uow.session.scalars(
                    select(RightsGrant)
                    .where(RightsGrant.agreement_version_id == version.id)
                    .order_by(RightsGrant.created_at)
                )
            )
            return AgreementDetails(agreement=agreement, version=version, grants=grants)

    async def _record_decision(
        self,
        principal: Principal,
        agreement_id: UUID,
        *,
        action: Action,
        decision: AgreementDecisionType,
        reason: str | None,
        agreement_version_id: UUID | None,
        correlation_id: UUID,
    ) -> AgreementDecision:
        async with self._uow_factory() as uow:
            agreement, creator = await self._agreement_and_creator(uow, agreement_id, lock=True)
            self._authorizer.require(principal, action, self._scope(creator.organization_id))
            version = (
                await self._require_version(uow, agreement.id, agreement_version_id)
                if agreement_version_id is not None
                else await self._latest_version(uow, agreement.id)
            )
            prior = set(
                await uow.session.scalars(
                    select(AgreementDecision.decision).where(
                        AgreementDecision.agreement_version_id == version.id
                    )
                )
            )
            if decision is AgreementDecisionType.APPROVED:
                if AgreementDecisionType.APPROVED in prior:
                    self._conflict("agreement_already_approved", "Agreement is already approved")
                if AgreementDecisionType.REVOKED in prior:
                    self._conflict(
                        "agreement_version_revoked",
                        "A revoked agreement version cannot be approved again.",
                    )
            else:
                if AgreementDecisionType.APPROVED not in prior:
                    self._conflict(
                        "agreement_not_approved",
                        "Only an approved agreement version can be revoked.",
                    )
                if AgreementDecisionType.REVOKED in prior:
                    self._conflict("agreement_already_revoked", "Agreement is already revoked")
            record = AgreementDecision(
                organization_id=creator.organization_id,
                agreement_id=agreement.id,
                agreement_version_id=version.id,
                decision=decision,
                reason=reason,
                decided_by_user_id=principal.user_id,
                correlation_id=correlation_id,
            )
            uow.session.add(record)
            await uow.session.flush()
            event_name = f"agreement.{decision.value}"
            add_mutation_evidence(
                uow,
                principal=principal,
                organization_id=creator.organization_id,
                entity_type="agreement_decision",
                entity_id=record.id,
                action=event_name,
                correlation_id=correlation_id,
                reason=reason,
                new_values={
                    "agreement_id": str(agreement.id),
                    "agreement_version_id": str(version.id),
                    "decision": decision.value,
                },
            )
            await uow.session.flush()
            return record

    async def _agreement_and_creator(
        self, uow: UnitOfWork, agreement_id: UUID, *, lock: bool = False
    ) -> tuple[RightsAgreement, Creator]:
        query = select(RightsAgreement).where(RightsAgreement.id == agreement_id)
        if lock:
            query = query.with_for_update()
        agreement = await uow.session.scalar(query)
        if agreement is None:
            self._not_found("agreement_not_found", "Agreement not found")
        creator = await uow.session.get(Creator, agreement.creator_id)
        if creator is None:
            self._not_found("creator_not_found", "Creator not found")
        return agreement, creator

    async def _latest_version(
        self, uow: UnitOfWork, agreement_id: UUID
    ) -> RightsAgreementVersion:
        version = await uow.session.scalar(
            select(RightsAgreementVersion)
            .where(RightsAgreementVersion.agreement_id == agreement_id)
            .order_by(RightsAgreementVersion.agreement_version_number.desc())
            .limit(1)
        )
        if version is None:
            self._not_found("agreement_version_not_found", "Agreement version not found")
        return version

    async def _require_version(
        self, uow: UnitOfWork, agreement_id: UUID, version_id: UUID
    ) -> RightsAgreementVersion:
        version = await uow.session.get(RightsAgreementVersion, version_id)
        if version is None or version.agreement_id != agreement_id:
            self._not_found("agreement_version_not_found", "Agreement version not found")
        return version

    @staticmethod
    def _scope(organization_id: UUID) -> ResourceScope:
        return ResourceScope(
            organization_id=organization_id,
            creator_organization_id=organization_id,
        )

    @staticmethod
    def _not_found(code: str, title: str) -> NoReturn:
        raise ProblemException(
            status_code=404,
            code=code,
            title=title,
            detail=f"The requested {title.lower()} does not exist.",
        )

    @staticmethod
    def _conflict(code: str, detail: str) -> NoReturn:
        raise ProblemException(
            status_code=409,
            code=code,
            title="Agreement conflict",
            detail=detail,
        )
