from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from oki.api.errors import register_problem_handlers
from oki.api.middleware import install_middleware
from oki.config import Settings
from oki.db.uow import UnitOfWork
from oki.identity.authorization import Authorizer
from oki.identity.dependencies import current_principal
from oki.identity.enums import Action
from oki.identity.schemas import Principal, PrincipalMembership
from oki.jobs.models import OutboxEvent
from oki.rights.models import AgreementDecision, AuditEvent
from oki.rights.router import router as rights_router
from oki.rights.service import AgreementService
from oki.creators.router import router as creators_router
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
async def identity_rows(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[tuple[UUID, UUID, UUID]]:
    organization_id = uuid4()
    legal_user_id = uuid4()
    publisher_user_id = uuid4()
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "insert into organizations (id, slug, name) "
                "values (:id, :slug, 'Rights API tenant')"
            ),
            {"id": organization_id, "slug": f"rights-api-{organization_id}"},
        )
        for user_id, role in (
            (legal_user_id, "legal"),
            (publisher_user_id, "publisher"),
        ):
            await session.execute(
                text(
                    "insert into users (id, keycloak_subject, email, display_name) "
                    "values (:id, :subject, :email, :display_name)"
                ),
                {
                    "id": user_id,
                    "subject": f"rights-api-{user_id}",
                    "email": f"rights-api-{user_id}@example.test",
                    "display_name": role.title(),
                },
            )
    try:
        yield organization_id, legal_user_id, publisher_user_id
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
                text("delete from users where id in (:legal, :publisher)"),
                {"legal": legal_user_id, "publisher": publisher_user_id},
            )


@pytest.fixture
def principals(
    identity_rows: tuple[UUID, UUID, UUID],
) -> tuple[Principal, Principal]:
    organization_id, legal_user_id, publisher_user_id = identity_rows
    legal_actions = frozenset(
        {
            Action.CREATOR_CREATE,
            Action.CREATOR_READ,
            Action.AGREEMENT_CREATE,
            Action.AGREEMENT_APPROVE,
            Action.AGREEMENT_REVOKE,
            Action.VOICE_CONSENT_RECORD,
        }
    )
    publisher_actions = frozenset(
        {
            Action.CREATOR_READ,
            Action.AGREEMENT_CREATE,
        }
    )

    def make_principal(user_id: UUID, role: str, actions: frozenset[Action]) -> Principal:
        return Principal(
            subject=f"rights-api-{user_id}",
            user_id=user_id,
            email=f"rights-api-{user_id}@example.test",
            display_name=role.title(),
            memberships=(
                PrincipalMembership(
                    organization_id=organization_id,
                    role_names=frozenset({role}),
                    actions=actions,
                    creator_organization_ids=frozenset({organization_id}),
                ),
            ),
        )

    return (
        make_principal(legal_user_id, "legal_reviewer", legal_actions),
        make_principal(publisher_user_id, "publisher", publisher_actions),
    )


@pytest.fixture
async def client_and_principal(
    session_factory: async_sessionmaker[AsyncSession],
    principals: tuple[Principal, Principal],
) -> AsyncIterator[tuple[httpx.AsyncClient, dict[str, Principal]]]:
    app = FastAPI()
    install_middleware(app)
    register_problem_handlers(app)
    uow_factory = lambda: UnitOfWork(session_factory)
    app.state.creator_service = CreatorService(uow_factory, Authorizer())
    app.state.agreement_service = AgreementService(uow_factory, Authorizer())
    app.include_router(creators_router)
    app.include_router(rights_router)

    principal_box = {"principal": principals[0]}

    async def override_principal() -> Principal:
        return principal_box["principal"]

    app.dependency_overrides[current_principal] = override_principal
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client, principal_box


def creator_json(organization_id: UUID) -> dict[str, object]:
    now = datetime.now(UTC).isoformat()
    return {
        "organization_id": str(organization_id),
        "legal_name": "María API LLC",
        "display_name": "María API",
        "primary_email": "maria-api@example.test",
        "manager_name": "Rights Manager",
        "manager_email": "manager-api@example.test",
        "channels": [
            {
                "platform": "youtube",
                "external_channel_id": "UC-api-licensed",
                "handle": "@mariaapi",
                "canonical_url": "https://www.youtube.com/@mariaapi",
                "ownership_evidence": [
                    {
                        "method": "youtube_oauth_and_signed_attestation",
                        "decision": "granted",
                        "evidence_reference": "s3://contracts/api-channel.pdf",
                        "evidence_sha256": "e" * 64,
                        "observed_at": now,
                        "decided_at": now,
                    }
                ],
            }
        ],
    }


def agreement_json() -> dict[str, object]:
    now = datetime.now(UTC)
    return {
        "title": "API Spanish localization SOW",
        "external_reference": "SOW-API-001",
        "version": {
            "contract_reference": "s3://contracts/SOW-API-001.pdf",
            "contract_sha256": "f" * 64,
            "effective_from": now.isoformat(),
            "expires_at": (now + timedelta(days=365)).isoformat(),
            "termination_notice_days": 30,
            "termination_terms": "Written notice required.",
            "monetization_mode": "revenue_share",
            "revenue_share_bps": "3000",
            "payout_currency": "USD",
            "payout_frequency": "monthly",
            "payout_terms": "Net 30.",
            "grants": [
                {
                    "asset_scope": "category",
                    "asset_reference": "education",
                    "language_code": "es",
                    "territory_code": "MX",
                    "platform": "youtube",
                    "content_format": "full",
                    "translation_allowed": True,
                    "dubbing_allowed": True,
                    "editing_allowed": True,
                    "metadata_allowed": True,
                    "likeness_allowed": True,
                    "brand_use_allowed": True,
                    "sponsor_removal_allowed": True,
                    "sponsor_replacement_mode": "full",
                    "endorsement_mode": "personal",
                    "voice_clone_allowed": True,
                    "creator_approval_policy": "every_publication",
                    "starts_at": now.isoformat(),
                    "ends_at": (now + timedelta(days=365)).isoformat(),
                }
            ],
        },
    }


async def create_pending_agreement(
    client: httpx.AsyncClient,
    organization_id: UUID,
) -> tuple[dict[str, object], dict[str, object]]:
    creator_response = await client.post("/api/creators", json=creator_json(organization_id))
    assert creator_response.status_code == 201, creator_response.text
    creator = creator_response.json()
    agreement_response = await client.post(
        f"/api/creators/{creator['id']}/agreements",
        json=agreement_json(),
    )
    assert agreement_response.status_code == 201, agreement_response.text
    return creator, agreement_response.json()


async def test_sow_creator_and_agreement_routes_preserve_legal_history(
    client_and_principal: tuple[httpx.AsyncClient, dict[str, Principal]],
    identity_rows: tuple[UUID, UUID, UUID],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    client, _ = client_and_principal
    organization_id, _, _ = identity_rows
    creator, agreement = await create_pending_agreement(client, organization_id)

    creator_response = await client.get(f"/api/creators/{creator['id']}")
    assert creator_response.status_code == 200
    assert creator_response.json()["channels"][0]["ownership_verified"] is True

    approval = await client.post(
        f"/api/agreements/{agreement['id']}/approve",
        json={"reason": "Signed contract verified"},
    )
    assert approval.status_code == 200, approval.text
    revocation = await client.post(
        f"/api/agreements/{agreement['id']}/revoke",
        json={"reason": "Creator terminated the agreement"},
    )
    assert revocation.status_code == 200, revocation.text

    async with session_factory() as session:
        decision_count = await session.scalar(
            select(func.count())
            .select_from(AgreementDecision)
            .where(AgreementDecision.agreement_id == UUID(str(agreement["id"])))
        )
        audit_count = await session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.organization_id == organization_id)
        )
        outbox_count = await session.scalar(
            select(func.count())
            .select_from(OutboxEvent)
            .where(OutboxEvent.organization_id == organization_id)
        )

    assert decision_count == 2
    assert audit_count == 4
    assert outbox_count == 4


async def test_publisher_cannot_legally_approve_agreement(
    client_and_principal: tuple[httpx.AsyncClient, dict[str, Principal]],
    identity_rows: tuple[UUID, UUID, UUID],
    principals: tuple[Principal, Principal],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    client, principal_box = client_and_principal
    organization_id, _, _ = identity_rows
    _, agreement = await create_pending_agreement(client, organization_id)
    principal_box["principal"] = principals[1]

    response = await client.post(f"/api/agreements/{agreement['id']}/approve")

    assert response.status_code == 403
    assert response.json()["code"] == "action_denied"
    async with session_factory() as session:
        decision_count = await session.scalar(
            select(func.count())
            .select_from(AgreementDecision)
            .where(AgreementDecision.agreement_id == UUID(str(agreement["id"])))
        )
    assert decision_count == 0


async def test_creator_scope_cannot_cross_before_disclosure(
    client_and_principal: tuple[httpx.AsyncClient, dict[str, Principal]],
    identity_rows: tuple[UUID, UUID, UUID],
    principals: tuple[Principal, Principal],
) -> None:
    client, principal_box = client_and_principal
    organization_id, _, _ = identity_rows
    creator, _ = await create_pending_agreement(client, organization_id)
    legal = principals[0]
    principal_box["principal"] = Principal(
        subject=legal.subject,
        user_id=legal.user_id,
        email=legal.email,
        display_name=legal.display_name,
        memberships=(),
    )

    response = await client.get(f"/api/creators/{creator['id']}")

    assert response.status_code == 403
    assert response.json()["code"] == "resource_scope_denied"
