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
from oki.jobs.models import LocalizationJob, OutboxEvent, Project, WorkflowTransition
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
from oki.rights.schemas import AgreementCreate, AgreementVersionCreate, RightsGrantCreate
from oki.rights.service import AgreementService
from oki.rights.revocation import RevocationService


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
                "values (:id, :slug, 'Task 2 revocation tenant')"
            ),
            {"id": organization_id, "slug": f"task-2-revoke-{organization_id}"},
        )
        await session.execute(
            text(
                "insert into users (id, keycloak_subject, email, display_name) "
                "values (:id, :subject, :email, 'Legal Reviewer')"
            ),
            {
                "id": user_id,
                "subject": f"task-2-revoke-{user_id}",
                "email": f"task-2-revoke-{user_id}@example.test",
            },
        )

    principal = Principal(
        subject=f"task-2-revoke-{user_id}",
        user_id=user_id,
        email=f"task-2-revoke-{user_id}@example.test",
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
                text("delete from workflow_transitions where organization_id = :organization_id"),
                {"organization_id": organization_id},
            )
            await session.execute(
                text("delete from outbox_events where organization_id = :organization_id"),
                {"organization_id": organization_id},
            )
            await session.execute(
                text("delete from localization_jobs where organization_id = :organization_id"),
                {"organization_id": organization_id},
            )
            await session.execute(
                text("delete from projects where organization_id = :organization_id"),
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
                text("delete from creator_channels where organization_id = :organization_id"),
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
):
    creator = await CreatorService(uow_factory, Authorizer()).create(
        principal,
        creator_payload(organization_id),
        correlation_id=uuid4(),
    )
    agreement, version = await AgreementService(uow_factory, Authorizer()).create_version(
        principal,
        creator.id,
        agreement_payload(),
        correlation_id=uuid4(),
    )
    return creator, agreement, version


@pytest.fixture
def revocation_service(uow_factory: Callable[[], UnitOfWork]) -> RevocationService:
    return RevocationService(uow_factory)


async def test_revocation_propagates_to_active_jobs(
    uow_factory: Callable[[], UnitOfWork],
    session_factory: async_sessionmaker[AsyncSession],
    tenant: tuple[UUID, UUID, Principal],
    revocation_service: RevocationService,
) -> None:
    organization_id, _, principal = tenant
    creator, agreement, version = await create_agreement(
        uow_factory, organization_id, principal
    )
    service = AgreementService(uow_factory, Authorizer())
    await service.approve(principal, agreement.id, reason="Approved", correlation_id=uuid4())

    # Create a project and job
    project_id = uuid4()
    job_id = uuid4()
    async with session_factory.begin() as session:
        session.add(
            Project(
                id=project_id,
                organization_id=organization_id,
                name="Revocation test project",
                state=WorkflowState.CREATOR_LEAD,
            )
        )
        await session.flush()
        session.add(
            LocalizationJob(
                id=job_id,
                organization_id=organization_id,
                project_id=project_id,
                state=WorkflowState.RIGHTS_APPROVED,
            )
        )

    affected = await revocation_service.propagate(version.id)
    assert affected == 1

    async with session_factory() as session:
        job = await session.get(LocalizationJob, job_id)
        transitions = list(
            await session.scalars(
                select(WorkflowTransition).where(WorkflowTransition.job_id == job_id)
            )
        )
        outbox = list(
            await session.scalars(
                select(OutboxEvent).where(OutboxEvent.aggregate_id == job_id)
            )
        )

    assert job is not None
    assert job.state == WorkflowState.RIGHTS_REVOKED
    assert len(transitions) == 1
    assert transitions[0].event == WorkflowEvent.REVOKE_RIGHTS
    assert transitions[0].guard_result is True
    assert len(outbox) == 1
    assert outbox[0].event_type == "workflow.revoked"


async def test_revocation_is_idempotent_for_already_revoked_jobs(
    uow_factory: Callable[[], UnitOfWork],
    session_factory: async_sessionmaker[AsyncSession],
    tenant: tuple[UUID, UUID, Principal],
    revocation_service: RevocationService,
) -> None:
    organization_id, _, principal = tenant
    creator, agreement, version = await create_agreement(
        uow_factory, organization_id, principal
    )
    service = AgreementService(uow_factory, Authorizer())
    await service.approve(principal, agreement.id, reason="Approved", correlation_id=uuid4())

    project_id = uuid4()
    job_id = uuid4()
    async with session_factory.begin() as session:
        session.add(
            Project(
                id=project_id,
                organization_id=organization_id,
                name="Idempotent test project",
                state=WorkflowState.CREATOR_LEAD,
            )
        )
        await session.flush()
        session.add(
            LocalizationJob(
                id=job_id,
                organization_id=organization_id,
                project_id=project_id,
                state=WorkflowState.RIGHTS_REVOKED,
            )
        )

    affected = await revocation_service.propagate(version.id)
    assert affected == 0


async def test_revocation_returns_zero_for_missing_version(
    revocation_service: RevocationService,
) -> None:
    affected = await revocation_service.propagate(uuid4())
    assert affected == 0
