from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from oki.config import Settings
from oki.db.uow import UnitOfWork
from oki.identity.authorization import Authorizer
from oki.identity.enums import Action
from oki.identity.schemas import Principal, PrincipalMembership
from oki.publications.enums import PublicationStatus
from oki.publications.models import Publications, PublishApprovals
from oki.publications.service import PublicationService
from oki.youtube.models import AuthorizedChannel


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
                "insert into organizations (id, slug, name) values (:id, :slug, 'Pub test')"
            ),
            {"id": organization_id, "slug": f"pub-test-{organization_id.hex[:8]}"},
        )
        await session.execute(
            text("insert into users (id, keycloak_subject, email, display_name) values (:id, :sub, :email, 'Publisher')"),
            {"id": user_id, "sub": f"sub-{user_id.hex}", "email": f"pub-test-{user_id.hex}@example.test"},
        )
        await session.execute(
            text(
                "insert into creators (id, organization_id, legal_name, display_name, primary_email, created_by_user_id, status) "
                "values (:id, :org_id, 'Test Creator', 'TestCreator', 'creator@example.test', :user_id, 'active')"
            ),
            {"id": user_id, "org_id": organization_id, "user_id": user_id},
        )
    principal = Principal(
        subject=f"sub-{user_id.hex}",
        user_id=user_id,
        email=f"pub-test-{user_id.hex}@example.test",
        display_name="Publisher",
        memberships=[
            PrincipalMembership(
                organization_id=organization_id,
                role_names=frozenset({"publisher"}),
                actions=frozenset({
                    Action.PUBLICATION_UPLOAD_PRIVATE,
                    Action.PUBLICATION_RELEASE_PUBLIC,
                    Action.PUBLICATION_UNPUBLISH,
                }),
                creator_organization_ids=frozenset(),
                project_ids=frozenset(),
            )
        ],
    )
    yield organization_id, user_id, principal
    async with session_factory.begin() as session:
        await session.execute(text("delete from publications where organization_id = :org_id"), {"org_id": organization_id})
        await session.execute(text("delete from localization_jobs where organization_id = :org_id"), {"org_id": organization_id})
        await session.execute(text("delete from source_assets where organization_id = :org_id"), {"org_id": organization_id})
        await session.execute(text("delete from creators where organization_id = :org_id"), {"org_id": organization_id})
        await session.execute(text("delete from users where id = :user_id"), {"user_id": user_id})
        await session.execute(text("delete from organizations where id = :org_id"), {"org_id": organization_id})


async def _create_publication(
    uow_factory: Callable[[], UnitOfWork],
    organization_id: UUID,
    user_id: UUID,
    status: PublicationStatus = PublicationStatus.DRAFT,
) -> Publications:
    async with uow_factory() as uow:
        job_id = uuid4()
        project_id = uuid4()
        await uow.session.execute(
            text(
                "insert into projects (id, organization_id, name) values (:id, :org_id, 'Test Project')"
            ),
            {"id": project_id, "org_id": organization_id},
        )
        await uow.session.execute(
            text(
                "insert into source_assets (id, organization_id, creator_id, created_by_user_id, title, status) "
                "values (:id, :org_id, :user_id, :user_id, 'test.mp4', 'active')"
            ),
            {"id": job_id, "org_id": organization_id, "user_id": user_id},
        )
        await uow.session.execute(
            text(
                "insert into localization_jobs (id, organization_id, project_id, state) "
                "values (:id, :org_id, :project_id, 'PUBLISH_READY')"
            ),
            {"id": job_id, "org_id": organization_id, "project_id": project_id},
        )
        pub = Publications(
            organization_id=organization_id,
            job_id=job_id,
            status=status,
            mode="creator_channel_localization",
            created_by_user_id=user_id,
        )
        uow.session.add(pub)
        await uow.session.flush()
        return pub


async def test_publish_requires_private_uploaded(
    uow_factory: Callable[[], UnitOfWork],
    tenant: tuple[UUID, UUID, Principal],
) -> None:
    organization_id, user_id, principal = tenant
    service = PublicationService(uow_factory, Authorizer())
    pub = await _create_publication(uow_factory, organization_id, user_id, status=PublicationStatus.DRAFT)
    from oki.api.errors import ProblemException
    with pytest.raises(ProblemException) as exc_info:
        await service.publish(pub.id, principal, uuid4())
    assert exc_info.value.code == "publication_not_ready"


async def test_publish_requires_approval(
    uow_factory: Callable[[], UnitOfWork],
    tenant: tuple[UUID, UUID, Principal],
) -> None:
    organization_id, user_id, principal = tenant
    service = PublicationService(uow_factory, Authorizer())
    pub = await _create_publication(uow_factory, organization_id, user_id, status=PublicationStatus.PRIVATE_UPLOADED)
    from oki.api.errors import ProblemException
    with pytest.raises(ProblemException) as exc_info:
        await service.publish(pub.id, principal, uuid4())
    assert exc_info.value.code == "publication_not_approved"


async def test_publish_succeeds_with_private_and_approval(
    uow_factory: Callable[[], UnitOfWork],
    tenant: tuple[UUID, UUID, Principal],
) -> None:
    organization_id, user_id, principal = tenant
    service = PublicationService(uow_factory, Authorizer())
    pub = await _create_publication(uow_factory, organization_id, user_id, status=PublicationStatus.PRIVATE_UPLOADED)
    async with uow_factory() as uow:
        approval = PublishApprovals(
            organization_id=organization_id,
            publication_id=pub.id,
            approved_by_user_id=user_id,
            approved_at=datetime.now(UTC),
        )
        uow.session.add(approval)
        await uow.session.flush()
    result = await service.publish(pub.id, principal, uuid4())
    assert result.status == PublicationStatus.PUBLISHED
