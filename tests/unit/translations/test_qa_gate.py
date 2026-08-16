from collections.abc import AsyncIterator, Callable
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from oki.config import Settings
from oki.db.uow import UnitOfWork
from oki.identity.authorization import Authorizer
from oki.identity.enums import Action
from oki.identity.schemas import Principal, PrincipalMembership
from oki.translations.enums import QaDimension, TranslationStatus
from oki.translations.models import Translations
from oki.translations.service import TranslationQaService, TranslationService


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
async def tenant(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[tuple[UUID, UUID, Principal]]:
    organization_id = uuid4()
    user_id = uuid4()
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "insert into organizations (id, slug, name) "
                "values (:id, :slug, 'Translation unit tenant')"
            ),
            {"id": organization_id, "slug": f"translation-unit-{organization_id}"},
        )
        await session.execute(
            text(
                "insert into users (id, keycloak_subject, email, display_name) "
                "values (:id, :subject, :email, 'Translator')"
            ),
            {
                "id": user_id,
                "subject": f"translation-unit-{user_id}",
                "email": f"translation-unit-{user_id}@example.test",
            },
        )
        await session.execute(
            text(
                "insert into creators (id, organization_id, legal_name, display_name, primary_email, created_by_user_id, status) "
                "values (:id, :org_id, 'Test Creator', 'TestCreator', 'creator@example.test', :user_id, 'active')"
            ),
            {"id": user_id, "org_id": organization_id, "user_id": user_id},
        )

    principal = Principal(
        subject=f"translation-unit-{user_id}",
        user_id=user_id,
        email=f"translation-unit-{user_id}@example.test",
        display_name="Translator",
        memberships=(
            PrincipalMembership(
                organization_id=organization_id,
                role_names=frozenset({"translator"}),
                actions=frozenset({Action.PROJECT_READ, Action.CREATOR_REVIEW_SUBMIT}),
                creator_organization_ids=frozenset(),
                project_ids=frozenset(),
            ),
        ),
    )
    yield organization_id, user_id, principal
    async with session_factory.begin() as session:
        await session.execute(
            text("delete from translation_qa_reviews where organization_id = :organization_id"),
            {"organization_id": organization_id},
        )
        await session.execute(
            text("delete from translation_revisions where organization_id = :organization_id"),
            {"organization_id": organization_id},
        )
        await session.execute(
            text("delete from translation_segments where organization_id = :organization_id"),
            {"organization_id": organization_id},
        )
        await session.execute(
            text("delete from translations where organization_id = :organization_id"),
            {"organization_id": organization_id},
        )
        await session.execute(
            text("delete from source_assets where organization_id = :organization_id"),
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
            text("delete from creators where organization_id = :organization_id"),
            {"organization_id": organization_id},
        )
        await session.execute(
            text("delete from users where id = :user_id"),
            {"user_id": user_id},
        )
        await session.execute(
            text("delete from organizations where id = :organization_id"),
            {"organization_id": organization_id},
        )


async def test_qa_service_evaluates_all_seven_dimensions() -> None:
    qa = TranslationQaService()
    scores = await qa.evaluate(
        translation_id=uuid4(),
        segments=[{"text": "Hello world"}],
    )
    assert len(scores) == 7
    for dim in QaDimension:
        assert dim in scores
        assert 1 <= scores[dim] <= 10


async def test_translation_start_creates_pending_record(
    uow_factory: Callable[[], UnitOfWork],
    tenant: tuple[UUID, UUID, Principal],
) -> None:
    organization_id, user_id, principal = tenant

    # Need a job row to satisfy FK
    job_id = uuid4()
    project_id = uuid4()
    async with uow_factory() as uow:
        await uow.session.execute(
            text(
                "insert into projects (id, organization_id, name, state) "
                "values (:project_id, :org_id, 'Test Project', 'SOURCE_UPLOADED')"
            ),
            {"project_id": project_id, "org_id": organization_id},
        )
        await uow.session.execute(
            text(
                "insert into source_assets (id, organization_id, creator_id, created_by_user_id, title, status) "
                "values (:asset_id, :org_id, :user_id, :user_id, 'test-asset.mp4', 'active')"
            ),
            {"asset_id": job_id, "org_id": organization_id, "user_id": user_id},
        )
        await uow.session.execute(
            text(
                "insert into localization_jobs (id, organization_id, project_id, state) "
                "values (:job_id, :org_id, :project_id, 'SOURCE_UPLOADED')"
            ),
            {"job_id": job_id, "org_id": organization_id, "project_id": project_id},
        )

    service = TranslationService(uow_factory, Authorizer())
    translation = await service.start(
        principal,
        job_id=job_id,
        target_language="es",
        source_language="en",
    )
    assert translation.source_language == "en"
    assert translation.target_language == "es"
    assert translation.status == TranslationStatus.PENDING
    assert translation.organization_id == organization_id

    async with uow_factory() as uow:
        persisted = await uow.session.get(Translations, translation.id)
        assert persisted is not None
        assert persisted.status == TranslationStatus.PENDING
