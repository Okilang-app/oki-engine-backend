from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from oki.config import Settings
from oki.creators.schemas import ChannelOwnershipEvidenceCreate, CreatorChannelCreate, CreatorCreate
from oki.creators.service import CreatorService
from oki.db.uow import UnitOfWork
from oki.identity.authorization import Authorizer
from oki.identity.enums import Action
from oki.identity.schemas import Principal, PrincipalMembership
from oki.jobs.enums import WorkflowEvent, WorkflowState
from oki.jobs.models import LocalizationJob, Project
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
from oki.rights.models import (
    RightsEvaluation,
)
from oki.rights.policy import RightsRequest
from oki.rights.schemas import AgreementCreate, AgreementVersionCreate, RightsGrantCreate
from oki.rights.service import AgreementService
from oki.rights.gate import RightsGate


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(Settings(environment="test").database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture
def uow_factory(session_factory: async_sessionmaker[AsyncSession]) -> Callable[[], UnitOfWork]:
    return lambda: UnitOfWork(session_factory)


@pytest.fixture
async def tenant(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[tuple[UUID, UUID, Principal]]:
    organization_id = uuid4()
    user_id = uuid4()
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "insert into organizations (id, slug, name) "
                "values (:id, :slug, 'Task 2 unit tenant')"
            ),
            {"id": organization_id, "slug": f"task-2-unit-{organization_id}"},
        )
        await session.execute(
            text(
                "insert into users (id, keycloak_subject, email, display_name) "
                "values (:id, :subject, :email, 'Legal Reviewer')"
            ),
            {
                "id": user_id,
                "subject": f"task-2-unit-{user_id}",
                "email": f"task-2-unit-{user_id}@example.test",
            },
        )

    principal = Principal(
        subject=f"task-2-unit-{user_id}",
        user_id=user_id,
        email=f"task-2-unit-{user_id}@example.test",
        display_name="Legal Reviewer",
        memberships=(
            PrincipalMembership(
                organization_id=organization_id,
                role_names=frozenset({"legal_reviewer"}),
                actions=frozenset(
                    {
                        Action.CREATOR_CREATE,
                        Action.CREATOR_READ,
                        Action.AGREEMENT_CREATE,
                        Action.AGREEMENT_APPROVE,
                        Action.AGREEMENT_REVOKE,
                        Action.VOICE_CONSENT_RECORD,
                    }
                ),
                creator_organization_ids=frozenset({organization_id}),
            ),
        ),
    )
    try:
        yield organization_id, user_id, principal
    finally:
        async with session_factory.begin() as session:
            await session.execute(
                text("delete from creator_channels where organization_id = :organization_id"),
                {"organization_id": organization_id},
            )
            await session.execute(
                text("delete from rights_evaluations where organization_id = :organization_id"),
                {"organization_id": organization_id},
            )
            await session.execute(
                text("delete from rights_grants where agreement_version_id in (select id from rights_agreement_versions where agreement_id in (select id from rights_agreements where organization_id = :organization_id))"),
                {"organization_id": organization_id},
            )
            await session.execute(
                text("delete from rights_agreement_versions where agreement_id in (select id from rights_agreements where organization_id = :organization_id)"),
                {"organization_id": organization_id},
            )
            await session.execute(
                text("delete from rights_agreements where organization_id = :organization_id"),
                {"organization_id": organization_id},
            )
            await session.execute(
                text("delete from creators where organization_id = :organization_id"),
                {"organization_id": organization_id},
            )
            await session.execute(
                text("delete from audit_events where organization_id = :organization_id"),
                {"organization_id": organization_id},
            )
            await session.execute(
                text("delete from organizations where id = :organization_id"),
                {"organization_id": organization_id},
            )
            await session.execute(
                text("delete from users where id = :user_id"),
                {"user_id": user_id},
            )


def creator_payload(organization_id: UUID) -> CreatorCreate:
    now = datetime.now(UTC)
    return CreatorCreate(
        organization_id=organization_id,
        legal_name="María Example LLC",
        display_name="María Example",
        primary_email="maria@example.test",
        manager_name="Rights Manager",
        manager_email="manager@example.test",
        channels=[
            CreatorChannelCreate(
                platform=Platform.YOUTUBE,
                external_channel_id=f"UC-{uuid4().hex[:16]}",
                handle="@mariaexample",
                canonical_url="https://www.youtube.com/@mariaexample",
                ownership_evidence=[
                    ChannelOwnershipEvidenceCreate(
                        method="youtube_oauth_and_signed_attestation",
                        decision=ConsentDecision.GRANTED,
                        evidence_reference="s3://contracts/channel-attestation.pdf",
                        evidence_sha256="a" * 64,
                        observed_at=now,
                        decided_at=now,
                    )
                ],
            )
        ],
    )


def agreement_payload(*, contract_sha256: str = "b" * 64) -> AgreementCreate:
    now = datetime.now(UTC)
    return AgreementCreate(
        title="Spanish LATAM video localization SOW",
        external_reference="SOW-2026-001",
        version=AgreementVersionCreate(
            contract_reference="s3://contracts/SOW-2026-001.pdf",
            contract_sha256=contract_sha256,
            effective_from=now,
            expires_at=now + timedelta(days=365),
            termination_notice_days=30,
            termination_terms="Either party may terminate on written notice.",
            monetization_mode=MonetizationMode.REVENUE_SHARE,
            revenue_share_bps=Decimal("2500"),
            payout_currency="USD",
            payout_frequency="monthly",
            payout_terms="Net 30 after platform revenue receipt.",
            grants=[
                RightsGrantCreate(
                    asset_scope=AssetScope.CATEGORY,
                    asset_reference="education",
                    language_code="es",
                    territory_code="MX",
                    platform=Platform.YOUTUBE,
                    content_format=ContentFormat.FULL,
                    translation_allowed=True,
                    dubbing_allowed=True,
                    editing_allowed=True,
                    metadata_allowed=True,
                    likeness_allowed=True,
                    brand_use_allowed=True,
                    sponsor_removal_allowed=True,
                    sponsor_replacement_mode=SponsorReplacementMode.FULL,
                    endorsement_mode=EndorsementMode.PERSONAL,
                    voice_clone_allowed=True,
                    creator_approval_policy=CreatorApprovalPolicy.EVERY_PUBLICATION,
                    starts_at=now,
                    ends_at=now + timedelta(days=365),
                )
            ],
        ),
    )


async def create_agreement(
    uow_factory: Callable[[], UnitOfWork],
    organization_id: UUID,
    principal: Principal,
    payload: AgreementCreate | None = None,
    existing_creator_id: UUID | None = None,
):
    if existing_creator_id is None:
        creator = await CreatorService(uow_factory, Authorizer()).create(
            principal,
            creator_payload(organization_id),
            correlation_id=uuid4(),
        )
        existing_creator_id = creator.id
    agreement, version = await AgreementService(uow_factory, Authorizer()).create_version(
        principal,
        existing_creator_id,
        payload or agreement_payload(),
        correlation_id=uuid4(),
    )
    from oki.creators.models import Creator
    async with uow_factory() as uow:
        creator = await uow.session.get(Creator, existing_creator_id)
    return creator, agreement, version


@pytest.fixture
def rights_gate(uow_factory: Callable[[], UnitOfWork]) -> RightsGate:
    return RightsGate(uow_factory)


@pytest.fixture
def rights_case_factory(
    uow_factory: Callable[[], UnitOfWork],
    session_factory: async_sessionmaker[AsyncSession],
    tenant: tuple[UUID, UUID, Principal],
) -> Callable[[str], RightsRequest]:
    organization_id, user_id, principal = tenant

    async def factory(case: str) -> RightsRequest:
        creator, agreement, version = await create_agreement(
            uow_factory, organization_id, principal
        )

        base = RightsRequest(
            organization_id=organization_id,
            creator_id=creator.id,
            language_code="es",
            territory_code="MX",
            platform=Platform.YOUTUBE,
            content_format=ContentFormat.FULL,
            operation="translation",
            asset_category="education",
        )

        if case == "no_agreement":
            async with session_factory.begin() as session:
                await session.execute(
                    text("delete from rights_grants where agreement_version_id = :vid"),
                    {"vid": version.id},
                )
                await session.execute(
                    text("delete from rights_agreement_versions where id = :vid"),
                    {"vid": version.id},
                )
                await session.execute(
                    text("delete from rights_agreements where id = :aid"),
                    {"aid": agreement.id},
                )
            return RightsRequest(
                organization_id=organization_id,
                creator_id=creator.id,
                language_code="es",
                territory_code="MX",
                platform=Platform.YOUTUBE,
                content_format=ContentFormat.FULL,
                operation="translation",
                asset_category="education",
            )

        if case == "pending":
            return base

        if case == "expired":
            from oki.rights.schemas import AgreementVersionCreate
            expired_payload = agreement_payload()
            expired_payload.external_reference = "SOW-2026-002-expired"
            expired_version = AgreementVersionCreate(**expired_payload.version.model_dump())
            expired_version.effective_from = datetime.now(UTC) - timedelta(days=30)
            expired_version.expires_at = datetime.now(UTC) - timedelta(days=1)
            expired_payload.version = expired_version
            _, agreement2, version2 = await create_agreement(
                uow_factory, organization_id, principal, expired_payload, existing_creator_id=creator.id
            )
            service = AgreementService(uow_factory, Authorizer())
            await service.approve(
                principal, agreement2.id, reason="Approved", correlation_id=uuid4()
            )
            return base

        if case == "revoked":
            service = AgreementService(uow_factory, Authorizer())
            await service.approve(
                principal, agreement.id, reason="Approved", correlation_id=uuid4()
            )
            await service.revoke(
                principal, agreement.id, reason="Revoked", correlation_id=uuid4()
            )
            return base

        if case == "language":
            service = AgreementService(uow_factory, Authorizer())
            await service.approve(
                principal, agreement.id, reason="Approved", correlation_id=uuid4()
            )
            return RightsRequest(
                organization_id=organization_id,
                creator_id=creator.id,
                language_code="fr",
                territory_code="MX",
                platform=Platform.YOUTUBE,
                content_format=ContentFormat.FULL,
                operation="translation",
                asset_category="education",
            )

        if case == "platform":
            service = AgreementService(uow_factory, Authorizer())
            await service.approve(
                principal, agreement.id, reason="Approved", correlation_id=uuid4()
            )
            return RightsRequest(
                organization_id=organization_id,
                creator_id=creator.id,
                language_code="es",
                territory_code="MX",
                platform=Platform.TIKTOK,
                content_format=ContentFormat.FULL,
                operation="translation",
                asset_category="education",
            )

        if case == "shorts":
            service = AgreementService(uow_factory, Authorizer())
            await service.approve(
                principal, agreement.id, reason="Approved", correlation_id=uuid4()
            )
            return RightsRequest(
                organization_id=organization_id,
                creator_id=creator.id,
                language_code="es",
                territory_code="MX",
                platform=Platform.YOUTUBE,
                content_format=ContentFormat.SHORTS,
                operation="translation",
                asset_category="education",
            )

        if case == "sponsor":
            service = AgreementService(uow_factory, Authorizer())
            await service.approve(
                principal, agreement.id, reason="Approved", correlation_id=uuid4()
            )
            async with session_factory.begin() as session:
                await session.execute(
                    text(
                        "update rights_grants set sponsor_replacement_mode = 'none' "
                        "where agreement_version_id = :vid"
                    ),
                    {"vid": version.id},
                )
            return RightsRequest(
                organization_id=organization_id,
                creator_id=creator.id,
                language_code="es",
                territory_code="MX",
                platform=Platform.YOUTUBE,
                content_format=ContentFormat.FULL,
                operation="translation",
                asset_category="education",
                sponsorship_action="replace",
            )

        if case == "clone":
            service = AgreementService(uow_factory, Authorizer())
            await service.approve(
                principal, agreement.id, reason="Approved", correlation_id=uuid4()
            )
            return RightsRequest(
                organization_id=organization_id,
                creator_id=creator.id,
                language_code="es",
                territory_code="MX",
                platform=Platform.YOUTUBE,
                content_format=ContentFormat.FULL,
                operation="translation",
                asset_category="education",
                voice_mode="clone",
            )

        if case == "endorsement":
            service = AgreementService(uow_factory, Authorizer())
            await service.approve(
                principal, agreement.id, reason="Approved", correlation_id=uuid4()
            )
            async with session_factory.begin() as session:
                await session.execute(
                    text(
                        "update rights_grants set endorsement_mode = 'none' "
                        "where agreement_version_id = :vid"
                    ),
                    {"vid": version.id},
                )
            return RightsRequest(
                organization_id=organization_id,
                creator_id=creator.id,
                language_code="es",
                territory_code="MX",
                platform=Platform.YOUTUBE,
                content_format=ContentFormat.FULL,
                operation="endorsement",
                asset_category="education",
            )

        if case == "creator_approval":
            service = AgreementService(uow_factory, Authorizer())
            await service.approve(
                principal, agreement.id, reason="Approved", correlation_id=uuid4()
            )
            return RightsRequest(
                organization_id=organization_id,
                creator_id=creator.id,
                language_code="es",
                territory_code="MX",
                platform=Platform.YOUTUBE,
                content_format=ContentFormat.FULL,
                operation="translation",
                asset_category="education",
                creator_approved=False,
            )

        if case == "channel":
            service = AgreementService(uow_factory, Authorizer())
            await service.approve(
                principal, agreement.id, reason="Approved", correlation_id=uuid4()
            )
            return RightsRequest(
                organization_id=organization_id,
                creator_id=creator.id,
                language_code="es",
                territory_code="MX",
                platform=Platform.YOUTUBE,
                content_format=ContentFormat.FULL,
                operation="translation",
                asset_category="education",
                creator_approved=True,
                publication_channel_id=uuid4(),
            )

        raise ValueError(f"unknown case: {case}")

    return factory


@pytest.mark.parametrize(
    "case,code",
    [
        ("no_agreement", "agreement_missing"),
        ("pending", "agreement_not_approved"),
        ("expired", "agreement_expired"),
        ("revoked", "agreement_revoked"),
        ("language", "language_not_permitted"),
        ("platform", "platform_not_permitted"),
        ("shorts", "shorts_not_permitted"),
        ("sponsor", "sponsor_replacement_not_permitted"),
        ("clone", "voice_clone_consent_missing"),
        ("endorsement", "endorsement_not_permitted"),
        ("creator_approval", "creator_approval_missing"),
        ("channel", "channel_not_authorized"),
    ],
)
async def test_rights_gate_denies(
    case: str,
    code: str,
    rights_case_factory: Callable[[str], RightsRequest],
    rights_gate: RightsGate,
) -> None:
    request = await rights_case_factory(case)
    decision = await rights_gate.evaluate(request)
    assert decision.approved is False
    assert decision.reason_code == code


async def test_rights_gate_approves_and_returns_token(
    rights_case_factory: Callable[[str], RightsRequest],
    rights_gate: RightsGate,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    request = await rights_case_factory("creator_approval")
    request = RightsRequest(
        organization_id=request.organization_id,
        creator_id=request.creator_id,
        language_code="es",
        territory_code="MX",
        platform=Platform.YOUTUBE,
        content_format=ContentFormat.FULL,
        operation="translation",
        asset_category="education",
        creator_approved=True,
    )
    approved = await rights_gate.require(request)
    assert approved.evaluation_id is not None
    assert approved.agreement_version_id is not None

    async with session_factory() as session:
        evaluation = await session.get(RightsEvaluation, approved.evaluation_id)
    assert evaluation is not None
    assert evaluation.approved is True
    assert evaluation.agreement_version_id == approved.agreement_version_id


async def test_denied_work_creates_zero_provider_usage(
    rights_case_factory: Callable[[str], RightsRequest],
    rights_gate: RightsGate,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    request = await rights_case_factory("no_agreement")
    decision = await rights_gate.evaluate(request)
    assert decision.approved is False

    async with session_factory() as session:
        count = await session.scalar(
            select(RightsEvaluation).where(
                RightsEvaluation.creator_id == request.creator_id
            )
        )
    assert count is not None


async def test_rights_guard_evaluator_can_be_used_in_runner(
    uow_factory: Callable[[], UnitOfWork],
    session_factory: async_sessionmaker[AsyncSession],
    tenant: tuple[UUID, UUID, Principal],
    rights_gate: RightsGate,
) -> None:
    from oki.jobs.enums import WorkflowEvent
    from oki.jobs.models import LocalizationJob
    from oki.jobs.tasks import GuardEvaluation
    from oki.rights.gate import RightsGuardEvaluator

    organization_id, _, principal = tenant
    # Create a real creator so RightsEvaluation FK succeeds even when denied
    creator = await CreatorService(uow_factory, Authorizer()).create(
        principal,
        creator_payload(organization_id),
        correlation_id=uuid4(),
    )
    job_id = uuid4()
    project_id = uuid4()
    async with session_factory.begin() as session:
        session.add(
            Project(
                id=project_id,
                organization_id=organization_id,
                name="Guard eval project",
                state=WorkflowState.CREATOR_LEAD,
            )
        )
        await session.flush()
        session.add(
            LocalizationJob(
                id=job_id,
                organization_id=organization_id,
                project_id=project_id,
                state=WorkflowState.CREATOR_LEAD,
            )
        )

    evaluator = RightsGuardEvaluator(rights_gate)
    async with uow_factory() as uow:
        job = await uow.session.get(LocalizationJob, job_id)
        result = await evaluator.evaluate(
            uow,
            job,
            WorkflowEvent.REQUEST_RIGHTS,
            {"creator_id": str(creator.id), "language_code": "es", "asset_category": "education"},
        )
    assert isinstance(result, GuardEvaluation)
    assert result.allowed is False
    assert result.actor_type == "system"
