from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select

from oki.api.errors import ProblemException
from oki.creators.models import CreatorChannel
from oki.db.uow import UnitOfWork
from oki.rights.enums import ContentFormat, Platform
from oki.rights.models import (
    AgreementDecision,
    EndorsementConsent,
    RightsAgreement,
    RightsAgreementVersion,
    RightsEvaluation,
    RightsGrant,
    VoiceConsent,
)
from oki.rights.policy import (
    AgreementSnapshot,
    ApprovedRights,
    PolicyEvaluator,
    RightsDecision,
    RightsRequest,
)


class RightsGate:
    """Fail-closed rights gate: loads current legal versions, evaluates every SOW
    dimension via the pure policy evaluator, persists the decision, and returns
    an approved token or an exact denial reason.
    """

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def evaluate(self, request: RightsRequest, now: datetime | None = None) -> RightsDecision:
        if now is None:
            now = datetime.now(UTC)

        async with self._uow_factory() as uow:
            return await self._evaluate_in_uow(uow, request, now)

    async def require(self, request: RightsRequest, now: datetime | None = None) -> ApprovedRights:
        decision = await self.evaluate(request, now)
        if not decision.approved or decision.agreement_version_id is None:
            raise ProblemException(
                status_code=403,
                code=decision.reason_code,
                title="Rights denied",
                detail=f"Rights evaluation denied: {decision.reason_code}.",
            )
        return ApprovedRights(
            evaluation_id=decision.evaluation_id,
            agreement_version_id=decision.agreement_version_id,
        )

    async def _evaluate_in_uow(
        self, uow: UnitOfWork, request: RightsRequest, now: datetime
    ) -> RightsDecision:
        snapshot = await self._load_snapshot(uow, request)
        decision = PolicyEvaluator.evaluate(snapshot, request, now)
        evaluation_id = uuid4()
        uow.session.add(
            RightsEvaluation(
                id=evaluation_id,
                organization_id=request.organization_id,
                creator_id=request.creator_id,
                project_id=request.project_id,
                asset_reference=request.asset_reference,
                asset_category=request.asset_category,
                language_code=request.language_code,
                territory_code=request.territory_code,
                platform=request.platform,
                content_format=request.content_format,
                operation=request.operation,
                voice_mode=request.voice_mode,
                sponsorship_action=request.sponsorship_action,
                publication_channel_id=(request.publication_channel_id if decision.approved else None),
                approved=decision.approved,
                reason_code=decision.reason_code,
                reason_details=decision.reason_details,
                agreement_version_id=decision.agreement_version_id,
                correlation_id=uuid4(),
            )
        )
        await uow.session.flush()
        return RightsDecision(
            approved=decision.approved,
            reason_code=decision.reason_code,
            reason_details=decision.reason_details,
            agreement_version_id=decision.agreement_version_id,
            evaluation_id=evaluation_id,
        )

    async def _load_snapshot(
        self, uow: UnitOfWork, request: RightsRequest
    ) -> AgreementSnapshot:
        agreement = await uow.session.scalar(
            select(RightsAgreement)
            .where(
                RightsAgreement.creator_id == request.creator_id,
                RightsAgreement.organization_id == request.organization_id,
            )
            .order_by(RightsAgreement.created_at.desc())
            .limit(1)
        )

        if agreement is None:
            return AgreementSnapshot(
                version=None,
                grants=(),
                decisions=(),
                voice_consents=(),
                endorsement_consents=(),
                channels=(),
            )

        version = await uow.session.scalar(
            select(RightsAgreementVersion)
            .where(RightsAgreementVersion.agreement_id == agreement.id)
            .order_by(RightsAgreementVersion.agreement_version_number.desc())
            .limit(1)
        )

        if version is None:
            return AgreementSnapshot(
                version=None,
                grants=(),
                decisions=(),
                voice_consents=(),
                endorsement_consents=(),
                channels=(),
            )

        grants = tuple(
            await uow.session.scalars(
                select(RightsGrant)
                .where(RightsGrant.agreement_version_id == version.id)
                .order_by(RightsGrant.created_at)
            )
        )
        decisions = tuple(
            await uow.session.scalars(
                select(AgreementDecision)
                .where(AgreementDecision.agreement_version_id == version.id)
                .order_by(AgreementDecision.decided_at)
            )
        )
        voice_consents = tuple(
            await uow.session.scalars(
                select(VoiceConsent)
                .where(VoiceConsent.agreement_version_id == version.id)
                .order_by(VoiceConsent.created_at)
            )
        )
        endorsement_consents = tuple(
            await uow.session.scalars(
                select(EndorsementConsent)
                .where(EndorsementConsent.agreement_version_id == version.id)
                .order_by(EndorsementConsent.created_at)
            )
        )
        channels = tuple(
            await uow.session.scalars(
                select(CreatorChannel)
                .where(CreatorChannel.creator_id == request.creator_id)
                .order_by(CreatorChannel.created_at)
            )
        )

        return AgreementSnapshot(
            version=version,
            grants=grants,
            decisions=decisions,
            voice_consents=voice_consents,
            endorsement_consents=endorsement_consents,
            channels=channels,
        )


class RightsGuardEvaluator:
    """Stage 0 GuardEvaluator adapter backed by RightsGate.

    Hatchet tasks use this to recheck rights inside the locked runner
    transaction so that every transition is evaluated against the current
    legal snapshot and the decision is persisted.
    """

    def __init__(self, rights_gate: RightsGate) -> None:
        self._rights_gate = rights_gate

    async def evaluate(
        self,
        uow: UnitOfWork,
        job: "LocalizationJob",
        event: "WorkflowEvent",
        context: dict[str, Any],
    ) -> "GuardEvaluation":
        from datetime import UTC, datetime

        from oki.jobs.enums import WorkflowEvent
        from oki.jobs.tasks import GuardEvaluation

        now = datetime.now(UTC)
        request = RightsRequest(
            organization_id=job.organization_id,
            creator_id=context.get("creator_id", UUID(int=0)),
            project_id=job.project_id,
            language_code=context.get("language_code", "en"),
            territory_code=context.get("territory_code", "US"),
            platform=context.get("platform", Platform.YOUTUBE),
            content_format=context.get("content_format", ContentFormat.FULL),
            operation=context.get("operation", "unknown"),
            asset_reference=context.get("asset_reference"),
            asset_category=context.get("asset_category"),
            voice_mode=context.get("voice_mode"),
            sponsorship_action=context.get("sponsorship_action"),
            publication_channel_id=(
                UUID(context["publication_channel_id"])
                if context.get("publication_channel_id")
                else None
            ),
            creator_approved=context.get("creator_approved", False),
        )
        decision = await self._rights_gate._evaluate_in_uow(uow, request, now)
        return GuardEvaluation(
            allowed=decision.approved,
            actor_type="system",
            actor_id="oki.rights.gate",
            details={
                "reason_code": decision.reason_code,
                "evaluation_id": str(decision.evaluation_id),
                "agreement_version_id": (
                    str(decision.agreement_version_id)
                    if decision.agreement_version_id
                    else None
                ),
            },
        )
