"""Seed the database with a complete demo scenario for MVP testing."""
import asyncio
from uuid import UUID, uuid4
from decimal import Decimal
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

# Need to be in the project root for imports
import sys
sys.path.insert(0, "src")

from oki.creators.models import Creator, CreatorChannel
from oki.assets.models import SourceAsset
from oki.jobs.models import Project, LocalizationJob
from oki.jobs.enums import WorkflowState
from oki.analysis.models import TranscriptSegments
from oki.analysis.enums import AnalysisStatus, SegmentType
from oki.sponsors.models import AdSegments, AdSegmentEvidence
from oki.sponsors.enums import SponsorStatus
from oki.identity.models import User

ORG_ID = UUID(int=0)  # Matches LocalMembershipResolver fallback
USER_ID = UUID(int=0)  # Matches LocalMembershipResolver fallback principal

DEMO_TRANSCRIPT = [
    {"start": 0.0, "end": 8.5, "text": "Hey everyone, welcome back to the channel. Today we're reviewing something really exciting."},
    {"start": 8.5, "end": 35.0, "text": "Before we start, I want to thank our sponsor NordVPN. With NordVPN you can browse securely from anywhere. Use code TECH20 for 20% off your first year. Link in the description below."},
    {"start": 35.0, "end": 120.0, "text": "So this new laptop is absolutely incredible. The build quality is top notch, the screen is bright and color accurate, and the battery lasts over 14 hours in my testing."},
    {"start": 120.0, "end": 145.0, "text": "This video is sponsored by Squarespace. Whether you need a domain, website, or online store, make your next move with Squarespace. Use our link for 10% off."},
    {"start": 145.0, "end": 280.0, "text": "Back to the laptop. The keyboard has excellent travel and the trackpad is the best I've used on a Windows machine. Performance in video editing is surprisingly good thanks to the dedicated GPU."},
    {"start": 280.0, "end": 310.0, "text": "Quick shoutout to our affiliate partner Amazon. If you buy anything through our links, we get a small commission at no extra cost to you. It really helps the channel."},
    {"start": 310.0, "end": 420.0, "text": "In conclusion, this is probably the best ultrabook you can buy right now. The price is competitive, the performance is excellent, and the battery life is class leading."},
    {"start": 420.0, "end": 450.0, "text": "Thanks for watching. Don't forget to subscribe and hit the bell icon. I'll see you in the next one."},
]


async def seed():
    engine = create_async_engine("postgresql+asyncpg://oki:oki@localhost:55432/oki")
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    async with async_session() as session:
        # 1. Ensure organization exists
        org_exists = await session.scalar(
            select(text("1")).select_from(text("organizations")).where(text(f"id = '{ORG_ID}'::uuid")).limit(1)
        )
        if not org_exists:
            print("Creating demo organization...")
            await session.execute(
                text("INSERT INTO organizations (id, name, slug, is_active) VALUES (:id, 'Demo Org', 'demo-org', true) ON CONFLICT DO NOTHING"),
                {"id": ORG_ID}
            )

        # 2. Ensure user exists
        user = await session.get(User, USER_ID)
        if user is None:
            print("Creating demo user...")
            user = User(
                id=USER_ID,
                keycloak_subject="engineer@oki.test",
                email="engineer@oki.test",
                display_name="Test Engineer",
                is_active=True,
            )
            session.add(user)
            await session.flush()

        # 3. Create creator
        creator = await session.scalar(select(Creator).where(Creator.organization_id == ORG_ID).limit(1))
        if creator is None:
            print("Creating demo creator (MrBeast)...")
            creator = Creator(
                organization_id=ORG_ID,
                legal_name="MrBeast",
                display_name="MrBeast",
                primary_email="contact@mrbeast.org",
                manager_name="Jimmy Donaldson",
                manager_email="mgmt@mrbeast.org",
                status="active",
                created_by_user_id=USER_ID,
            )
            session.add(creator)
            await session.flush()

            channel = CreatorChannel(
                organization_id=ORG_ID,
                creator_id=creator.id,
                platform="youtube",
                external_channel_id="UCX6OQ3DkcsbYNE6H8uQQuVA",
                handle="@MrBeast",
                canonical_url="https://youtube.com/@MrBeast",
                created_by_user_id=USER_ID,
            )
            session.add(channel)
            await session.flush()
            print(f"  Creator ID: {creator.id}")

        # 4. Create asset
        asset = await session.scalar(select(SourceAsset).where(SourceAsset.organization_id == ORG_ID).limit(1))
        if asset is None:
            print("Creating demo asset (video)...")
            asset = SourceAsset(
                organization_id=ORG_ID,
                creator_id=creator.id,
                title="Laptop Review Demo",
                description="Demo video for sponsor detection MVP",
                status="active",
                storage_key="demo/laptop_review.mp4",
                storage_bucket="oki-local",
                sha256="a" * 64,
                size_bytes=524288000,
                duration_seconds=450,
                container_format="mp4",
                created_by_user_id=USER_ID,
            )
            session.add(asset)
            await session.flush()
            print(f"  Asset ID: {asset.id}")

        # 5. Create project + job
        job = await session.scalar(select(LocalizationJob).where(LocalizationJob.organization_id == ORG_ID).limit(1))
        if job is None:
            print("Creating demo project + job...")
            project = Project(
                organization_id=ORG_ID,
                name="Laptop Review - Ad Replacement",
                state=WorkflowState.AD_REVIEW_REQUIRED,
            )
            session.add(project)
            await session.flush()

            job = LocalizationJob(
                organization_id=ORG_ID,
                project_id=project.id,
                state=WorkflowState.AD_REVIEW_REQUIRED,
            )
            session.add(job)
            await session.flush()
            print(f"  Job ID: {job.id}")
            print(f"  Project ID: {project.id}")
        else:
            project = await session.get(Project, job.project_id)
            print(f"Using existing Job ID: {job.id}")

        # 6. Create transcript segments (only if not already exists)
        existing_segs = await session.scalar(
            select(TranscriptSegments).where(TranscriptSegments.job_id == job.id).limit(1)
        )
        if existing_segs is None:
            print("Creating demo transcript segments...")
            sponsor_keywords = {
                "sponsor", "sponsored", "promo code", "promo", "discount code",
                "use code", "thanks to", "brought to you by", "partner", "affiliate",
            }
            detected = 0
            for seg_data in DEMO_TRANSCRIPT:
                segment = TranscriptSegments(
                    organization_id=ORG_ID,
                    asset_id=asset.id if asset else job.id,
                    job_id=job.id,
                    speaker_id=None,
                    start_time=Decimal(str(seg_data["start"])),
                    end_time=Decimal(str(seg_data["end"])),
                    text=seg_data["text"],
                    language_code="en",
                    segment_type=SegmentType.SPEECH,
                    confidence=Decimal("0.95"),
                    status=AnalysisStatus.COMPLETED,
                    created_by_user_id=USER_ID,
                )
                session.add(segment)
                await session.flush()

                text_lower = seg_data["text"].lower()
                if any(kw in text_lower for kw in sponsor_keywords):
                    ad_seg = AdSegments(
                        organization_id=ORG_ID,
                        asset_id=asset.id if asset else job.id,
                        job_id=job.id,
                        start_time=segment.start_time,
                        end_time=segment.end_time,
                        sponsor_name=None,
                        status=SponsorStatus.DETECTED,
                        replacement_type=None,
                        reason_note=None,
                    )
                    session.add(ad_seg)
                    await session.flush()

                    evidence = AdSegmentEvidence(
                        organization_id=ORG_ID,
                        ad_segment_id=ad_seg.id,
                        evidence_type="keyword",
                        source_segment_id=segment.id,
                        confidence=Decimal("0.78"),
                    )
                    session.add(evidence)
                    detected += 1
            print(f"  Created {len(DEMO_TRANSCRIPT)} transcript segments")
            print(f"  Detected {detected} sponsor segments")
        else:
            print("Transcript segments already exist.")

        await session.commit()
        print("\nDemo scenario seeded successfully!")
        print(f"\nNext steps:")
        print(f"  1. Open http://localhost:3000/projects")
        print(f"  2. Click 'Analyze' on the Laptop Review project")
        print(f"  3. Review {detected if existing_segs is None else 'existing'} detected sponsor segments")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
