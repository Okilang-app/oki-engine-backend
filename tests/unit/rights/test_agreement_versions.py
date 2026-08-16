from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from oki.api.errors import ProblemException
from oki.config import Settings
from oki.db.uow import UnitOfWork
from oki.identity.authorization import Authorizer
from oki.identity.enums import Action
from oki.identity.schemas import Principal, PrincipalMembership
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
    AgreementDecision,
    RightsAgreementVersion,
    RightsEvaluation,
    RightsGrant,
)
from oki.rights.schemas import (
    AgreementCreate,
    AgreementVersionCreate,
    EndorsementConsentCreate,
    RightsGrantCreate,
    VoiceConsentCreate,
)
from oki.rights.service import AgreementService
from oki.creators.schemas import (
    ChannelOwnershipEvidenceCreate,
    CreatorChannelCreate,
    CreatorCreate,
)
from oki.creators.service import CreatorService


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(Settings(environment="test").database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture
def uow_factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> Callable[[], UnitOfWork]:
    return lambda: UnitOfWork(session_factory)


@pytest.fixture
async def tenant(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[tuple[UUID, UUID, Principal]]:
    organization_id = uuid4()
    user_id = uuid4()
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "insert into organizations (id, slug, name) "
                "values (:id, :slug, 'Rights unit tenant')"
            ),
            {"id": organization_id, "slug": f"rights-unit-{organization_id}"},
        )
        await session.execute(
            text(
                "insert into users (id, keycloak_subject, email, display_name) "
                "values (:id, :subject, :email, 'Legal Reviewer')"
            ),
            {
                "id": user_id,
                "subject": f"rights-unit-{user_id}",
                "email": f"rights-unit-{user_id}@example.test",
            },
        )

    principal = Principal(
        subject=f"rights-unit-{user_id}",
        user_id=user_id,
        email=f"rights-unit-{user_id}@example.test",
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
                external_channel_id="UC-licensed-channel",
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


async def test_approved_agreement_version_cannot_be_edited(
    uow_factory: Callable[[], UnitOfWork],
    tenant: tuple[UUID, UUID, Principal],
) -> None:
    organization_id, _, principal = tenant
    _, agreement, version = await create_agreement(uow_factory, organization_id, principal)
    service = AgreementService(uow_factory, Authorizer())
    await service.approve(
        principal,
        agreement.id,
        reason="Countersigned SOW verified by legal.",
        correlation_id=uuid4(),
    )

    with pytest.raises(ProblemException) as error:
        await service.update_version(
            principal,
            version.id,
            {"termination_terms": "Changed after approval"},
            correlation_id=uuid4(),
        )

    assert error.value.code == "agreement_version_immutable"


async def test_every_grant_dimension_is_explicit_and_version_bound(
    uow_factory: Callable[[], UnitOfWork],
    session_factory: async_sessionmaker[AsyncSession],
    tenant: tuple[UUID, UUID, Principal],
) -> None:
    organization_id, _, principal = tenant
    _, _, version = await create_agreement(uow_factory, organization_id, principal)

    async with session_factory() as session:
        grant = await session.scalar(
            select(RightsGrant).where(RightsGrant.agreement_version_id == version.id)
        )

    assert grant is not None
    assert grant.asset_scope is AssetScope.CATEGORY
    assert grant.asset_reference == "education"
    assert grant.language_code == "es"
    assert grant.territory_code == "MX"
    assert grant.platform is Platform.YOUTUBE
    assert grant.content_format is ContentFormat.FULL
    assert grant.translation_allowed is True
    assert grant.dubbing_allowed is True
    assert grant.editing_allowed is True
    assert grant.metadata_allowed is True
    assert grant.likeness_allowed is True
    assert grant.brand_use_allowed is True
    assert grant.sponsor_removal_allowed is True
    assert grant.sponsor_replacement_mode is SponsorReplacementMode.FULL
    assert grant.endorsement_mode is EndorsementMode.PERSONAL
    assert grant.voice_clone_allowed is True
    assert grant.creator_approval_policy is CreatorApprovalPolicy.EVERY_PUBLICATION
    assert grant.starts_at is not None and grant.ends_at is not None


async def test_approval_and_revocation_append_decisions_without_mutating_version(
    uow_factory: Callable[[], UnitOfWork],
    session_factory: async_sessionmaker[AsyncSession],
    tenant: tuple[UUID, UUID, Principal],
) -> None:
    organization_id, _, principal = tenant
    _, agreement, version = await create_agreement(uow_factory, organization_id, principal)
    service = AgreementService(uow_factory, Authorizer())

    approved = await service.approve(
        principal,
        agreement.id,
        reason="Approved",
        correlation_id=uuid4(),
    )
    revoked = await service.revoke(
        principal,
        agreement.id,
        reason="Creator exercised termination right",
        correlation_id=uuid4(),
    )

    async with session_factory() as session:
        decisions = list(
            await session.scalars(
                select(AgreementDecision)
                .where(AgreementDecision.agreement_id == agreement.id)
                .order_by(AgreementDecision.decided_at)
            )
        )
        persisted_version = await session.get(RightsAgreementVersion, version.id)

    assert approved.decision is AgreementDecisionType.APPROVED
    assert revoked.decision is AgreementDecisionType.REVOKED
    assert [decision.decision for decision in decisions] == [
        AgreementDecisionType.APPROVED,
        AgreementDecisionType.REVOKED,
    ]
    assert all(decision.agreement_version_id == version.id for decision in decisions)
    assert persisted_version is not None
    assert persisted_version.contract_sha256 == "b" * 64


async def test_voice_and_endorsement_consents_are_separate_version_bound_records(
    uow_factory: Callable[[], UnitOfWork],
    tenant: tuple[UUID, UUID, Principal],
) -> None:
    organization_id, _, principal = tenant
    _, agreement, version = await create_agreement(uow_factory, organization_id, principal)
    service = AgreementService(uow_factory, Authorizer())
    now = datetime.now(UTC)

    voice = await service.record_voice_consent(
        principal,
        agreement.id,
        VoiceConsentCreate(
            agreement_version_id=version.id,
            decision=ConsentDecision.GRANTED,
            language_code="es",
            territory_code="MX",
            platform=Platform.YOUTUBE,
            provider="elevenlabs",
            purpose="Spanish dubbing for licensed full videos",
            evidence_reference="s3://contracts/voice-consent.pdf",
            evidence_sha256="c" * 64,
            effective_from=now,
            expires_at=now + timedelta(days=180),
        ),
        correlation_id=uuid4(),
    )
    endorsement = await service.record_endorsement_consent(
        principal,
        agreement.id,
        EndorsementConsentCreate(
            agreement_version_id=version.id,
            decision=ConsentDecision.GRANTED,
            language_code="es",
            territory_code="MX",
            platform=Platform.YOUTUBE,
            approved_language="I personally use and recommend Oki.",
            evidence_reference="s3://contracts/endorsement-consent.pdf",
            evidence_sha256="d" * 64,
            effective_from=now,
            expires_at=now + timedelta(days=90),
        ),
        correlation_id=uuid4(),
    )

    assert voice.agreement_version_id == version.id
    assert endorsement.agreement_version_id == version.id
    assert voice.id != endorsement.id


async def test_rights_evaluation_persists_exact_version_and_is_append_only(
    uow_factory: Callable[[], UnitOfWork],
    session_factory: async_sessionmaker[AsyncSession],
    tenant: tuple[UUID, UUID, Principal],
) -> None:
    organization_id, user_id, principal = tenant
    creator, _, version = await create_agreement(uow_factory, organization_id, principal)
    evaluation_id = uuid4()
    async with session_factory.begin() as session:
        session.add(
            RightsEvaluation(
                id=evaluation_id,
                organization_id=organization_id,
                creator_id=creator.id,
                project_id=None,
                asset_reference="asset-future-001",
                asset_category="education",
                language_code="es",
                territory_code="MX",
                platform=Platform.YOUTUBE,
                content_format=ContentFormat.FULL,
                operation="translation",
                voice_mode="licensed_neutral_voice",
                sponsorship_action="retain",
                publication_channel_id=None,
                approved=True,
                reason_code="rights_granted",
                reason_details={"stage": "command_acceptance"},
                agreement_version_id=version.id,
                correlation_id=uuid4(),
                actor_user_id=user_id,
            )
        )

    async with session_factory() as session:
        persisted = await session.get(RightsEvaluation, evaluation_id)
        update_allowed = await session.scalar(
            text("select has_table_privilege('oki_app', 'rights_evaluations', 'UPDATE')")
        )
        delete_allowed = await session.scalar(
            text("select has_table_privilege('oki_app', 'rights_evaluations', 'DELETE')")
        )

    assert persisted is not None
    assert persisted.agreement_version_id == version.id
    assert persisted.reason_details == {"stage": "command_acceptance"}
    assert update_allowed is False
    assert delete_allowed is False


async def test_creator_scope_cannot_cross_organization(
    uow_factory: Callable[[], UnitOfWork],
    tenant: tuple[UUID, UUID, Principal],
) -> None:
    organization_id, user_id, principal = tenant
    creator = await CreatorService(uow_factory, Authorizer()).create(
        principal,
        creator_payload(organization_id),
        correlation_id=uuid4(),
    )
    foreign_principal = Principal(
        subject=principal.subject,
        user_id=user_id,
        email=principal.email,
        display_name=principal.display_name,
        memberships=(),
    )

    with pytest.raises(ProblemException) as error:
        await CreatorService(uow_factory, Authorizer()).get(
            foreign_principal,
            creator.id,
        )

    assert error.value.code == "resource_scope_denied"
