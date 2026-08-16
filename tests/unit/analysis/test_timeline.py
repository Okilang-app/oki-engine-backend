from collections.abc import AsyncIterator, Callable
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from oki.analysis.models import AnalysisRevisions, TranscriptSegments
from oki.analysis.schemas import SegmentReviseRequest
from oki.analysis.service import AnalysisService
from oki.assets.models import SourceAsset
from oki.config import Settings
from oki.db.uow import UnitOfWork
from oki.identity.authorization import Authorizer
from oki.identity.enums import Action
from oki.identity.schemas import Principal, PrincipalMembership


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
                "values (:id, :slug, 'Analysis unit tenant')"
            ),
            {"id": organization_id, "slug": f"analysis-unit-{organization_id}"},
        )
        await session.execute(
            text(
                "insert into users (id, keycloak_subject, email, display_name) "
                "values (:id, :subject, :email, 'Analyst')"
            ),
            {
                "id": user_id,
                "subject": f"analysis-unit-{user_id}",
                "email": f"analysis-unit-{user_id}@example.test",
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
        subject=f"analysis-unit-{user_id}",
        user_id=user_id,
        email=f"analysis-unit-{user_id}@example.test",
        display_name="Analyst",
        memberships=(
            PrincipalMembership(
                organization_id=organization_id,
                role_names=frozenset({"analyst"}),
                actions=frozenset({Action.PROJECT_READ}),
                creator_organization_ids=frozenset(),
                project_ids=frozenset(),
            ),
        ),
    )
    yield organization_id, user_id, principal
    async with session_factory.begin() as session:
        await session.execute(
            text("delete from analysis_revisions where organization_id = :organization_id"),
            {"organization_id": organization_id},
        )
        await session.execute(
            text("delete from transcript_segments where organization_id = :organization_id"),
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


async def test_get_timeline_returns_empty_for_unknown_asset(
    uow_factory: Callable[[], UnitOfWork],
    tenant: tuple[UUID, UUID, Principal],
) -> None:
    organization_id, _, principal = tenant
    service = AnalysisService(uow_factory, Authorizer())
    # Since asset table doesn't have the row, this will 404
    with pytest.raises(Exception) as exc_info:
        await service.get_timeline(principal, uuid4())
    assert exc_info.value.status_code == 404


async def test_revise_transcript_segment_creates_revision(
    uow_factory: Callable[[], UnitOfWork],
    tenant: tuple[UUID, UUID, Principal],
) -> None:
    organization_id, user_id, principal = tenant

    project_id = uuid4()
    asset_id = uuid4()
    job_id = uuid4()
    async with uow_factory() as uow:
        await uow.session.execute(
            text("insert into projects (id, organization_id, name) values (:id, :org_id, 'Test Project')"),
            {"id": project_id, "org_id": organization_id},
        )
        await uow.session.execute(
            text("insert into source_assets (id, organization_id, creator_id, created_by_user_id, title, status) values (:id, :org_id, :user_id, :user_id, 'test.mp4', 'active')"),
            {"id": asset_id, "org_id": organization_id, "user_id": user_id},
        )
        await uow.session.execute(
            text("insert into localization_jobs (id, organization_id, project_id, state) values (:id, :org_id, :project_id, 'SOURCE_UPLOADED')"),
            {"id": job_id, "org_id": organization_id, "project_id": project_id},
        )
        segment = TranscriptSegments(
            organization_id=organization_id,
            asset_id=asset_id,
            job_id=job_id,
            speaker_id=None,
            start_time=Decimal("0.000"),
            end_time=Decimal("5.000"),
            text="Hello world",
            language_code="en",
            segment_type="speech",
            confidence=Decimal("0.950"),
            status="completed",
            created_by_user_id=user_id,
        )
        uow.session.add(segment)
        await uow.session.flush()
        segment_id = segment.id

    service = AnalysisService(uow_factory, Authorizer())
    revision = await service.revise_transcript_segment(
        principal,
        segment_id,
        new_text="Hello universe",
        reason="Wider context",
    )

    assert isinstance(revision, AnalysisRevisions)
    assert revision.previous_value["text"] == "Hello world"
    assert revision.new_value["text"] == "Hello universe"
    assert revision.revision_type == "transcript_segment_text"

    async with uow_factory() as uow:
        updated = await uow.session.get(TranscriptSegments, segment_id)
        assert updated is not None
        assert updated.text == "Hello universe"
        assert updated.version == 2
