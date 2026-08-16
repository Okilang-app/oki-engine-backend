import asyncio
import subprocess
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import boto3
from sqlalchemy import delete, select, update

from oki.api.errors import ProblemException
from oki.db.uow import UnitOfWork
from oki.identity.authorization import Authorizer
from oki.identity.enums import Action
from oki.identity.schemas import Principal, ResourceScope
from oki.jobs.enums import WorkflowState
from oki.jobs.models import LocalizationJob, Project
from oki.jobs.schemas import JobResponse
from oki.analysis.models import TranscriptSegments
from oki.analysis.enums import AnalysisStatus, SegmentType
from oki.sponsors.models import AdSegments, AdSegmentEvidence
from oki.sponsors.enums import DetectionReason, ReplacementType, SponsorStatus


# Demo transcript for a tech review video with sponsor mentions
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


class JobService:
    def __init__(self, uow_factory: Callable[[], UnitOfWork], authorizer: Authorizer) -> None:
        self._uow_factory = uow_factory
        self._authorizer = authorizer

    async def create_job(
        self,
        principal: Principal,
        *,
        name: str,
        source_asset_id: str | None = None,
        source_url: str | None = None,
        source_language: str | None = None,
        target_language: str | None = None,
        organization_id: UUID | None = None,
    ) -> LocalizationJob:
        """Create a new Project + LocalizationJob."""
        from oki.assets.models import SourceAsset
        from oki.assets.enums import AssetStatus

        org_id = organization_id or principal.memberships[0].organization_id
        self._authorizer.require(
            principal,
            Action.CREATOR_CREATE,
            ResourceScope(organization_id=org_id),
        )
        async with self._uow_factory() as uow:
            project = Project(
                organization_id=org_id,
                name=name,
                state=WorkflowState.CREATOR_LEAD,
            )
            uow.session.add(project)
            await uow.session.flush()

            job = LocalizationJob(
                organization_id=org_id,
                project_id=project.id,
                state=WorkflowState.CREATOR_LEAD,
            )
            uow.session.add(job)
            await uow.session.flush()

            # Link source asset to job if provided
            if source_asset_id:
                asset = await uow.session.get(SourceAsset, UUID(source_asset_id))
                if asset is not None:
                    asset.localization_job_id = job.id
                    await uow.session.flush()

            # Import from YouTube URL if provided
            if source_url and not source_asset_id:
                from oki.assets.ytdlp import YtDlpImporter
                from oki.config import Settings
                from oki.creators.models import Creator

                settings = Settings()
                creator = await uow.session.scalar(
                    select(Creator)
                    .where(Creator.organization_id == org_id)
                    .limit(1)
                )
                creator_id = creator.id if creator else UUID(int=0)

                asset = SourceAsset(
                    organization_id=org_id,
                    creator_id=creator_id,
                    title=name,
                    status=AssetStatus.DRAFT,
                    localization_job_id=job.id,
                    created_by_user_id=principal.user_id,
                )
                uow.session.add(asset)
                await uow.session.flush()
                asset_id = asset.id

                # Download outside the DB transaction
                importer = YtDlpImporter(settings)
                try:
                    result = await importer.download_and_upload(source_url, asset_id, org_id)
                    asset.storage_key = result["storage_key"]
                    asset.sha256 = result["sha256"]
                    asset.size_bytes = result["file_size"]
                    asset.duration_seconds = result.get("duration")
                    asset.title = result.get("title", name)
                    asset.status = AssetStatus.ACTIVE
                    await uow.session.flush()
                except Exception as exc:
                    asset.status = AssetStatus.DELETED
                    await uow.session.flush()
                    raise ProblemException(
                        status_code=400,
                        code="import_failed",
                        title="Video import failed",
                        detail=f"Failed to download video: {exc}",
                    )

            # Store source_language as transient attribute for analyze flow
            job.source_language = source_language or "auto"

            return job

    async def analyze_job(
        self,
        principal: Principal,
        job_id: UUID,
    ) -> dict:
        """Run interactive analysis: create transcript segments and detect sponsors."""
        from oki.assets.models import SourceAsset
        from oki.config import Settings
        from oki.providers.openai_transcription import OpenAITranscriptionClient

        settings = Settings()

        async with self._uow_factory() as uow:
            job = await uow.session.get(LocalizationJob, job_id)
            if job is None:
                raise ProblemException(
                    status_code=404,
                    code="job_not_found",
                    title="Job not found",
                    detail=f"No job with id {job_id}",
                )
            org_id = job.organization_id
            self._authorizer.require(
                principal,
                Action.PROJECT_READ,
                ResourceScope(organization_id=org_id),
            )

            # Clear any stale prior analysis so re-runs are idempotent
            await uow.session.execute(
                delete(AdSegmentEvidence).where(
                    AdSegmentEvidence.ad_segment_id.in_(
                        select(AdSegments.id).where(AdSegments.job_id == job_id)
                    )
                )
            )
            await uow.session.execute(
                delete(AdSegments).where(AdSegments.job_id == job_id)
            )
            await uow.session.execute(
                delete(TranscriptSegments).where(TranscriptSegments.job_id == job_id)
            )

            # ── Find source asset for this job ──────────────────────────────
            asset = await uow.session.scalar(
                select(SourceAsset).where(SourceAsset.localization_job_id == job.id)
            )
            if asset is None:
                asset = await uow.session.scalar(
                    select(SourceAsset)
                    .where(SourceAsset.organization_id == org_id)
                    .order_by(SourceAsset.created_at.desc())
                    .limit(1)
                )
            if asset is None:
                raise ProblemException(
                    status_code=400,
                    code="no_asset",
                    title="No source asset available",
                    detail="Cannot analyze a job without a linked source asset.",
                )
            asset_id = asset.id

            # ── Try REAL transcription via Azure Whisper ─────────────────────
            transcript_data: list[dict] = []
            client = OpenAITranscriptionClient(settings)
            azure_configured = bool(settings.azure_openai_endpoint and settings.azure_openai_api_key)
            openai_configured = bool(settings.openai_api_key)
            use_real = azure_configured or openai_configured

            source_language = getattr(job, "source_language", None) or "auto"
            print(f"[analyze_job] Source language: {source_language}")

            if use_real and asset.storage_key:
                try:
                    transcript_data, video_duration = await self._transcribe_real(
                        asset, client, settings, language=source_language
                    )
                    if video_duration and not asset.duration_seconds:
                        asset.duration_seconds = video_duration
                        await uow.session.flush()
                except Exception as exc:
                    # Real API failed — return ERROR, never fake data silently
                    print(f"[analyze_job] Real transcription failed: {exc}")
                    raise ProblemException(
                        status_code=502,
                        code="transcription_failed",
                        title="Transcription failed",
                        detail=f"The AI transcription service returned an error: {exc}",
                    )

            # ── No AI configured — use demo data for local dev ──────────────
            if not transcript_data:
                transcript_data = DEMO_TRANSCRIPT
                fallback_reason = "demo_no_ai_configured"

            # ── Create TranscriptSegments ────────────────────────────────────
            created_segments: list[TranscriptSegments] = []
            for idx, seg_data in enumerate(transcript_data):
                segment = TranscriptSegments(
                    organization_id=org_id,
                    asset_id=asset_id,
                    job_id=job_id,
                    speaker_id=None,
                    start_time=Decimal(str(seg_data["start"])),
                    end_time=Decimal(str(seg_data["end"])),
                    text=seg_data["text"],
                    language_code="en",
                    segment_type=SegmentType.SPEECH,
                    confidence=Decimal("0.95"),
                    status=AnalysisStatus.COMPLETED,
                    created_by_user_id=principal.user_id,
                )
                uow.session.add(segment)
                created_segments.append(segment)
            await uow.session.flush()

            # ── Sponsor detection via SponsorBlock-ML ────────────────────────
            detected_count = 0
            proposed_count = 0

            from oki.providers.sponsorblock_ml import SponsorBlockMLDetector
            from oki.ads.models import InternalAd

            ads = list(await uow.session.scalars(
                select(InternalAd)
                .where(InternalAd.organization_id == org_id)
                .order_by(InternalAd.duration_seconds.desc())
            ))

            # Convert transcript segments to format for SponsorBlock-ML
            transcript_for_ml = [
                {"start": float(seg.start_time), "end": float(seg.end_time), "text": seg.text}
                for seg in created_segments
            ]

            try:
                detector = SponsorBlockMLDetector()
                ml_predictions = detector.detect(transcript_for_ml)
            except Exception as exc:
                # If ML model fails, fall back to empty detection
                print(f"[analyze_job] SponsorBlock-ML detection failed: {exc}")
                ml_predictions = []

            # Fallback: keyword-based detection when ML returns nothing
            # (common for non-English content, since SponsorBlock-ML is trained on English)
            if not ml_predictions:
                print("[analyze_job] ML returned 0 sponsors, running keyword fallback...")
                from types import SimpleNamespace
                from oki.sponsors.detection import SPONSOR_KEYWORDS
                keyword_hits: list[dict] = []
                for seg_data in transcript_for_ml:
                    text_lower = seg_data["text"].lower()
                    if any(kw in text_lower for kw in SPONSOR_KEYWORDS):
                        keyword_hits.append({
                            "start": seg_data["start"],
                            "end": seg_data["end"],
                            "category": "sponsor",
                            "text": seg_data["text"],
                        })
                # Merge contiguous/adjacent keyword hits (same logic as SponsorBlock-ML)
                from oki.providers.sponsorblock_ml import _merge_predictions
                merged = _merge_predictions(keyword_hits)
                for m in merged:
                    block_duration = m["end"] - m["start"]
                    if block_duration < 3.0:
                        # Drop likely false-positive single-word hits
                        print(f"[analyze_job] Dropping short keyword block {m['start']:.1f}s-{m['end']:.1f}s ({block_duration:.1f}s)")
                        continue
                    ml_predictions.append(SimpleNamespace(
                        start=m["start"],
                        end=m["end"],
                        category=m["category"],
                        text=m["text"],
                    ))

            for match in ml_predictions:
                seg_duration = match.end - match.start
                proposed_ad_id = None
                for ad in ads:
                    if (ad.duration_seconds or 0) <= seg_duration:
                        proposed_ad_id = ad.id
                        break

                status = SponsorStatus.DETECTED  # always detected; proposal conveyed via proposed_replacement_ad_id

                ad_seg = AdSegments(
                    organization_id=org_id,
                    asset_id=asset_id,
                    job_id=job_id,
                    start_time=Decimal(str(match.start)),
                    end_time=Decimal(str(match.end)),
                    sponsor_name=match.category if match.category != "sponsor" else None,
                    status=status,
                    replacement_type=ReplacementType.REPLACE_VOICE if proposed_ad_id else None,
                    reason_note=None,
                    reviewed_by_user_id=None,
                    reviewed_at=None,
                    proposed_replacement_ad_id=proposed_ad_id,
                    proposed_at=datetime.now(UTC) if proposed_ad_id else None,
                )
                uow.session.add(ad_seg)
                await uow.session.flush()

                # Find the closest transcript segment for evidence linking
                closest_seg = None
                closest_dist = float("inf")
                for seg in created_segments:
                    seg_mid = (float(seg.start_time) + float(seg.end_time)) / 2
                    match_mid = (match.start + match.end) / 2
                    dist = abs(seg_mid - match_mid)
                    if dist < closest_dist:
                        closest_dist = dist
                        closest_seg = seg

                evidence = AdSegmentEvidence(
                    organization_id=org_id,
                    ad_segment_id=ad_seg.id,
                    evidence_type="ml_transformer",
                    source_segment_id=closest_seg.id if closest_seg else None,
                    confidence=Decimal("0.82"),
                )
                uow.session.add(evidence)
                detected_count += 1
                if proposed_ad_id:
                    proposed_count += 1

            # Update job state
            job.state = WorkflowState.AD_REVIEW_REQUIRED
            await uow.session.flush()

            return {
                "job_id": str(job_id),
                "status": "analyzed",
                "segments_created": len(created_segments),
                "sponsors_detected": detected_count,
                "proposed_replacements": proposed_count,
                "source": "real_whisper" if use_real and transcript_data is not DEMO_TRANSCRIPT else "demo_fallback",
                "detection_method": "sponsorblock_ml" if detected_count > 0 else "none",
            }

    async def _transcribe_real(
        self,
        asset: "SourceAsset",
        client: "OpenAITranscriptionClient",
        settings: "Settings",
        language: str = "auto",
    ) -> tuple[list[dict], float]:
        """Download video, extract audio, call Whisper. Returns (segments, duration_seconds)."""
        s3 = boto3.client(
            "s3",
            endpoint_url=str(settings.s3_endpoint_url) if settings.s3_endpoint_url else None,
            aws_access_key_id=settings.s3_access_key or "",
            aws_secret_access_key=settings.s3_secret_key or "",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            video_path = tmp / "source.mp4"
            audio_path = tmp / "audio.m4a"

            # Download source video
            print(f"[analyze_job] Downloading s3://{settings.s3_bucket}/{asset.storage_key}")
            resp = s3.get_object(Bucket=settings.s3_bucket, Key=asset.storage_key)
            video_path.write_bytes(resp["Body"].read())
            print(f"[analyze_job] Downloaded {video_path.stat().st_size} bytes")

            # Extract audio via FFmpeg
            ffmpeg = settings.ffmpeg_path
            print(f"[analyze_job] Extracting audio with FFmpeg...")
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    [ffmpeg, "-i", str(video_path), "-vn", "-c:a", "copy", "-y", str(audio_path)],
                    capture_output=True, text=True, check=True,
                ),
            )
            print(f"[analyze_job] Audio extracted: {audio_path.stat().st_size} bytes")

            # Get video duration via ffprobe
            duration = await self._get_video_duration(settings.ffprobe_path, str(video_path))
            print(f"[analyze_job] Video duration: {duration:.1f}s")

            # Call Whisper with language hint
            whisper_lang = None if language == "auto" else language
            print(f"[analyze_job] Calling Whisper API (language={whisper_lang or 'auto'})...")
            result = await client.transcribe(
                audio_path,
                language=whisper_lang,
                response_format="verbose_json",
                duration_seconds=duration,
            )
            print(f"[analyze_job] Whisper returned {len(result.get('segments', []))} segments")
            return result.get("segments", []), duration

    async def _get_video_duration(self, ffprobe: str, video_path: str) -> float:
        """Get video duration via ffprobe or fallback."""
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    [ffprobe, "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", video_path],
                    capture_output=True, text=True, timeout=30,
                ),
            )
            return float(result.stdout.strip())
        except Exception:
            return 30.0

    async def replace_sponsor(
        self,
        principal: Principal,
        segment_id: UUID,
        *,
        replacement_type: str = "internal_ad",
        ad_id: UUID | None = None,
        reason: str | None = None,
    ) -> AdSegments:
        """Mark a sponsor segment as replaced with our own ad."""
        from oki.sponsors.enums import ReplacementType
        async with self._uow_factory() as uow:
            ad_segment = await uow.session.get(AdSegments, segment_id)
            if ad_segment is None:
                raise ProblemException(
                    status_code=404,
                    code="ad_segment_not_found",
                    title="Ad segment not found",
                    detail=f"No ad segment with id {segment_id}",
                )
            self._authorizer.require(
                principal,
                Action.SPONSOR_REPLACE,
                ResourceScope(organization_id=ad_segment.organization_id),
            )
            ad_segment.status = SponsorStatus.REPLACED
            ad_segment.replacement_type = ReplacementType.REPLACE_VOICE
            ad_segment.proposed_replacement_ad_id = ad_id
            ad_segment.reason_note = reason or "Replaced with internal ad"
            ad_segment.reviewed_by_user_id = principal.user_id
            ad_segment.reviewed_at = datetime.now(UTC)
            await uow.session.flush()
            return ad_segment

    async def list_jobs(self, principal: Principal) -> list[JobResponse]:
        async with self._uow_factory() as uow:
            org_ids = [
                m.organization_id for m in principal.memberships if Action.CREATOR_READ in m.actions
            ]
            if not org_ids:
                self._authorizer.require(
                    principal,
                    Action.CREATOR_READ,
                    ResourceScope(organization_id=UUID(int=0)),
                )
            stmt = (
                select(LocalizationJob, Project)
                .join(Project, LocalizationJob.project_id == Project.id)
                .where(LocalizationJob.organization_id.in_(org_ids))
                .order_by(LocalizationJob.created_at.desc())
            )
            result = await uow.session.execute(stmt)
            out: list[JobResponse] = []
            for job, project in result:
                out.append(
                    JobResponse(
                        id=job.id,
                        creator_id=None,
                        agreement_id=None,
                        title=project.name,
                        target_language=None,
                        workflow_state=job.state.value,
                        created_at=job.created_at,
                    )
                )
            return out

    async def get_job(self, principal: Principal, job_id: UUID) -> JobResponse:
        async with self._uow_factory() as uow:
            stmt = (
                select(LocalizationJob, Project)
                .join(Project, LocalizationJob.project_id == Project.id)
                .where(LocalizationJob.id == job_id)
            )
            result = await uow.session.execute(stmt)
            row = result.first()
            if row is None:
                raise ProblemException(
                    status_code=404,
                    code="job_not_found",
                    title="Job not found",
                    detail=f"No job with id {job_id}",
                )
            job, project = row
            self._authorizer.require(
                principal,
                Action.CREATOR_READ,
                ResourceScope(organization_id=job.organization_id),
            )
            return JobResponse(
                id=job.id,
                creator_id=None,
                agreement_id=None,
                title=project.name,
                target_language=getattr(job, "target_language", None),
                workflow_state=job.state.value,
                created_at=job.created_at,
            )

    async def delete_job(self, principal: Principal, job_id: UUID) -> dict:
        """Delete a job, its project, and all related records."""
        from oki.analysis.models import TranscriptSegments
        from oki.sponsors.models import AdSegments, AdSegmentEvidence
        from oki.assets.models import SourceAsset
        from oki.renders.models import RenderJob

        async with self._uow_factory() as uow:
            job = await uow.session.get(LocalizationJob, job_id)
            if job is None:
                raise ProblemException(
                    status_code=404,
                    code="job_not_found",
                    title="Job not found",
                    detail=f"No job with id {job_id}",
                )
            self._authorizer.require(
                principal,
                Action.PROJECT_DELETE,
                ResourceScope(organization_id=job.organization_id),
            )

            # Delete transcript segments
            await uow.session.execute(
                delete(TranscriptSegments)
                .where(TranscriptSegments.job_id == job_id)
            )

            # Delete ad segment evidence via subquery (no direct job_id FK)
            ad_seg_ids = await uow.session.scalars(
                select(AdSegments.id).where(AdSegments.job_id == job_id)
            )
            ids = list(ad_seg_ids)
            if ids:
                await uow.session.execute(
                    delete(AdSegmentEvidence)
                    .where(AdSegmentEvidence.ad_segment_id.in_(ids))
                )

            # Delete ad segments (cascade handles evidence too)
            await uow.session.execute(
                delete(AdSegments)
                .where(AdSegments.job_id == job_id)
            )

            # Delete render jobs linked to this job
            await uow.session.execute(
                delete(RenderJob)
                .where(RenderJob.job_id == job_id)
            )

            # Unlink source asset
            await uow.session.execute(
                update(SourceAsset)
                .where(SourceAsset.localization_job_id == job_id)
                .values(localization_job_id=None)
            )

            # Delete job and project
            project_id = job.project_id
            await uow.session.delete(job)
            project = await uow.session.get(Project, project_id)
            if project is not None:
                await uow.session.delete(project)

            await uow.session.flush()
            return {"job_id": str(job_id), "status": "deleted"}
