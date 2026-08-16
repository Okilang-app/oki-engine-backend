from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from oki.config import Settings
from oki.db.uow import UnitOfWork
from oki.analytics.attribution import AttributionService
from oki.analytics.models import AttributionLinks, OkiConversionEvents


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
async def tenant(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[UUID]:
    organization_id = uuid4()
    async with session_factory.begin() as session:
        await session.execute(
            text("insert into organizations (id, slug, name) values (:id, :slug, 'Attr test')"),
            {"id": organization_id, "slug": f"attr-test-{organization_id.hex[:8]}"},
        )
    yield organization_id


async def test_resolve_missing_event(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    service = AttributionService(uow_factory)
    event_id = uuid4()
    result = await service.resolve(event_id)
    assert result["resolved"] is False
    assert result["reason"] == "Event not found"


async def test_resolve_event_with_attribution(
    uow_factory: Callable[[], UnitOfWork],
    tenant: UUID,
) -> None:
    organization_id = tenant
    service = AttributionService(uow_factory)
    user_id = uuid4()
    creator_id = uuid4()
    async with uow_factory() as uow:
        await uow.session.execute(
            text("insert into users (id, keycloak_subject, email, display_name) values (:id, :sub, :email, 'Analytics Test')"),
            {"id": user_id, "sub": f"analytics-{user_id.hex}", "email": f"analytics-{user_id.hex}@example.test"},
        )
        await uow.session.execute(
            text(
                "insert into creators (id, organization_id, legal_name, display_name, primary_email, created_by_user_id, status) "
                "values (:id, :org_id, 'Test Creator', 'TestCreator', 'creator@example.test', :user_id, 'active')"
            ),
            {"id": creator_id, "org_id": organization_id, "user_id": user_id},
        )
        event = OkiConversionEvents(
            organization_id=organization_id,
            event_type="subscription",
            attributed_creator_id=creator_id,
            attributed_job_id=None,
            attributed_language="es",
            attributed_campaign_id="summer2026",
            value=99.99,
            currency="USD",
            event_metadata={"plan": "pro"},
            occurred_at=datetime(2026, 8, 15, 10, 0, tzinfo=UTC),
        )
        uow.session.add(event)
        await uow.session.flush()
        link = AttributionLinks(
            organization_id=organization_id,
            event_id=event.id,
            source="youtube_description",
            link_token="tok_123",
            landing_url="https://oki.app/es",
        )
        uow.session.add(link)
        await uow.session.flush()

    result = await service.resolve(event.id)
    assert result["resolved"] is True
    assert result["chain"]["language"] == "es"
    assert result["chain"]["campaign_id"] == "summer2026"
    assert len(result["chain"]["sources"]) == 1
    assert result["chain"]["sources"][0]["source"] == "youtube_description"
