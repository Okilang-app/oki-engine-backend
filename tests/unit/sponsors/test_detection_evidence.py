from collections.abc import AsyncIterator, Callable
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from oki.config import Settings
from oki.db.uow import UnitOfWork
from oki.identity.authorization import Authorizer
from oki.identity.enums import Action
from oki.identity.schemas import Principal, PrincipalMembership
from oki.assets.models import SourceAsset
from oki.sponsors.detection import StubSponsorDetector
from oki.sponsors.enums import DetectionReason, SponsorStatus
from oki.sponsors.models import AdSegmentEvidence, AdSegments
from oki.sponsors.service import SponsorDetectionService, SponsorReviewService


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
                "values (:id, :slug, 'Sponsors unit tenant')"
            ),
            {"id": organization_id, "slug": f"sponsors-unit-{organization_id}"},
        )
        await session.execute(
            text(
                "insert into users (id, keycloak_subject, email, display_name) "
                "values (:id, :subject, :email, 'Reviewer')"
            ),
            {
                "id": user_id,
                "subject": f"sponsors-unit-{user_id}",
                "email": f"sponsors-unit-{user_id}@example.test",
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
        subject=f"sponsors-unit-{user_id}",
        user_id=user_id,
        email=f"sponsors-unit-{user_id}@example.test",
        display_name="Reviewer",
        memberships=(
            PrincipalMembership(
                organization_id=organization_id,
                role_names=frozenset({"reviewer"}),
                actions=frozenset({Action.PROJECT_READ, Action.SPONSOR_REPLACE}),
                creator_organization_ids=frozenset(),
                project_ids=frozenset(),
            ),
        ),
    )
    yield organization_id, user_id, principal
    async with session_factory.begin() as session:
        await session.execute(
            text("delete from ad_segment_reviews where organization_id = :organization_id"),
            {"organization_id": organization_id},
        )
        await session.execute(
            text("delete from ad_segment_evidence where organization_id = :organization_id"),
            {"organization_id": organization_id},
        )
        await session.execute(
            text("delete from replacement_plans where organization_id = :organization_id"),
            {"organization_id": organization_id},
        )
        await session.execute(
            text("delete from ad_segments where organization_id = :organization_id"),
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
        await session.execute(
            text("delete from organizations where id = :organization_id"),
            {"organization_id": organization_id},
        )


async def test_stub_detector_finds_sponsor_keywords() -> None:
    detector = StubSponsorDetector()
    segments = [
        {"segment_id": str(uuid4()), "text": "This video is sponsored by Acme.", "start_time": 0.0, "end_time": 3.0},
        {"segment_id": str(uuid4()), "text": "Thanks for watching.", "start_time": 3.0, "end_time": 5.0},
        {"segment_id": str(uuid4()), "text": "Use promo code OKI for a discount.", "start_time": 5.0, "end_time": 8.0},
    ]
    candidates = await detector.detect_from_transcript(
        job_id=uuid4(),
        asset_id=uuid4(),
        organization_id=uuid4(),
        segments=segments,
    )
    assert len(candidates) == 2
    assert all(c.status == SponsorStatus.DETECTED for c in candidates)
    assert all(c.detection_reason == DetectionReason.KEYWORD for c in candidates)


async def test_build_evidence_links_to_segment() -> None:
    detector = StubSponsorDetector()
    ad_segment_id = uuid4()
    org_id = uuid4()
    source_segment_id = uuid4()
    evidence = detector.build_evidence(
        ad_segment_id=ad_segment_id,
        organization_id=org_id,
        source_segment_id=source_segment_id,
        confidence=0.75,
    )
    assert evidence.ad_segment_id == ad_segment_id
    assert evidence.organization_id == org_id
    assert evidence.source_segment_id == source_segment_id
    assert evidence.evidence_type == DetectionReason.KEYWORD
    assert float(evidence.confidence) == 0.75  # type: ignore[arg-type]


async def test_approve_and_reject_update_status(
    uow_factory: Callable[[], UnitOfWork],
    tenant: tuple[UUID, UUID, Principal],
) -> None:
    organization_id, user_id, principal = tenant

    asset_id = uuid4()
    job_id = uuid4()
    project_id = uuid4()
    async with uow_factory() as uow:
        await uow.session.execute(
            text("insert into projects (id, organization_id, name) values (:id, :org_id, 'Test Project')"),
            {"id": project_id, "org_id": organization_id},
        )
        await uow.session.execute(
            text("insert into localization_jobs (id, organization_id, project_id, state) values (:id, :org_id, :project_id, 'SOURCE_UPLOADED')"),
            {"id": job_id, "org_id": organization_id, "project_id": project_id},
        )
        await uow.session.execute(
            text("insert into source_assets (id, organization_id, creator_id, created_by_user_id, title, status) values (:id, :org_id, :user_id, :user_id, 'test.mp4', 'active')"),
            {"id": asset_id, "org_id": organization_id, "user_id": user_id},
        )
        ad = AdSegments(
            organization_id=organization_id,
            asset_id=asset_id,
            job_id=job_id,
            start_time=Decimal("10.000"),
            end_time=Decimal("20.000"),
            sponsor_name="Acme",
            status=SponsorStatus.DETECTED,
            replacement_type=None,
            reason_note=None,
            reviewed_by_user_id=None,
            reviewed_at=None,
        )
        uow.session.add(ad)
        await uow.session.flush()
        ad_id = ad.id

    review_service = SponsorReviewService(uow_factory, Authorizer())

    approved = await review_service.approve(principal, ad_id, reason="Looks correct")
    assert approved.status == SponsorStatus.CONFIRMED
    assert approved.reviewed_by_user_id == user_id

    # Reset for reject
    asset_id2 = uuid4()
    job_id2 = uuid4()
    async with uow_factory() as uow:
        project_id2 = uuid4()
        await uow.session.execute(
            text("insert into projects (id, organization_id, name) values (:id, :org_id, 'Test Project')"),
            {"id": project_id2, "org_id": organization_id},
        )
        await uow.session.execute(
            text("insert into localization_jobs (id, organization_id, project_id, state) values (:id, :org_id, :project_id, 'SOURCE_UPLOADED')"),
            {"id": job_id2, "org_id": organization_id, "project_id": project_id2},
        )
        await uow.session.execute(
            text("insert into source_assets (id, organization_id, creator_id, created_by_user_id, title, status) values (:id, :org_id, :user_id, :user_id, 'test.mp4', 'active')"),
            {"id": asset_id2, "org_id": organization_id, "user_id": user_id},
        )
        ad2 = AdSegments(
            organization_id=organization_id,
            asset_id=asset_id2,
            job_id=job_id2,
            start_time=Decimal("30.000"),
            end_time=Decimal("40.000"),
            sponsor_name="Beta",
            status=SponsorStatus.DETECTED,
            replacement_type=None,
            reason_note=None,
            reviewed_by_user_id=None,
            reviewed_at=None,
        )
        uow.session.add(ad2)
        await uow.session.flush()
        ad2_id = ad2.id

    rejected = await review_service.reject(principal, ad2_id, reason="False positive")
    assert rejected.status == SponsorStatus.REJECTED
    assert rejected.reviewed_by_user_id == user_id
