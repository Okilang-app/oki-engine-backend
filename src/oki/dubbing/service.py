"""Dubbing service with ElevenLabs TTS integration."""
from collections.abc import Callable
from typing import NoReturn
from uuid import UUID, uuid4

from sqlalchemy import select

from oki.api.errors import ProblemException
from oki.config import Settings
from oki.db.uow import UnitOfWork
from oki.identity.authorization import Authorizer
from oki.identity.enums import Action
from oki.identity.schemas import Principal, ResourceScope
from oki.dubbing.models import DubAttempt, DubSegment
from oki.providers.elevenlabs import ElevenLabsClient
from oki.storage.s3 import S3ObjectStore


class DubbingService:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        authorizer: Authorizer,
        store: S3ObjectStore,
    ) -> None:
        self._uow_factory = uow_factory
        self._authorizer = authorizer
        self._store = store
        self._elevenlabs: ElevenLabsClient | None = None
        self._settings = Settings()
        if self._settings.elevenlabs_api_key:
            self._elevenlabs = ElevenLabsClient(self._settings)

    async def start(
        self,
        principal: Principal,
        translation_id: UUID,
        *,
        correlation_id: UUID,
    ) -> list[DubSegment]:
        """Start dubbing for a completed translation job."""
        async with self._uow_factory() as uow:
            from oki.jobs.models import LocalizationJob

            job = await uow.session.get(LocalizationJob, translation_id)
            if job is None:
                self._not_found("translation_job_not_found", "Translation job not found")

            self._authorizer.require(
                principal,
                Action.CREATOR_READ,
                ResourceScope(organization_id=job.organization_id),
            )

            # For MVP, create placeholder segments from transcript segments
            from oki.sponsors.models import TranscriptSegments
            transcript_segs = list(await uow.session.scalars(
                select(TranscriptSegments)
                .where(TranscriptSegments.job_id == job.id)
                .order_by(TranscriptSegments.sequence_number)
            ))

            segments: list[DubSegment] = []
            for idx, ts in enumerate(transcript_segs):
                seg = DubSegment(
                    organization_id=job.organization_id,
                    job_id=job.id,
                    translation_job_id=job.id,
                    sequence_number=idx,
                    source_text=ts.text or "",
                    translated_text=ts.text or "",  # Same for MVP until translation wired
                    voice_profile_id=None,
                    timing_start_ms=int(ts.start_time * 1000) if ts.start_time else None,
                    timing_end_ms=int(ts.end_time * 1000) if ts.end_time else None,
                    status="pending",
                )
                segments.append(seg)
                uow.session.add(seg)

            await uow.session.flush()
            return segments

    async def regenerate_segment(
        self,
        principal: Principal,
        segment_id: UUID,
        *,
        correlation_id: UUID,
    ) -> DubSegment:
        """Regenerate audio for a single dub segment using ElevenLabs TTS."""
        async with self._uow_factory() as uow:
            segment = await uow.session.get(DubSegment, segment_id)
            if segment is None:
                self._not_found("dub_segment_not_found", "Dub segment not found")

            self._authorizer.require(
                principal,
                Action.CREATOR_READ,
                ResourceScope(organization_id=segment.organization_id),
            )

            segment.status = "generating"
            segment.audio_asset_reference = None
            segment.review_status = None
            await uow.session.flush()

            # If ElevenLabs is configured, generate real audio
            if self._elevenlabs and segment.translated_text:
                try:
                    voice_id = str(
                        segment.voice_profile_id
                        or "21m00Tcm4TlvDq8ikWAM"  # default Rachel
                    )
                    audio_bytes = await self._elevenlabs.synthesize(
                        text=segment.translated_text,
                        voice_profile_id=voice_id,
                    )
                    # Upload to S3
                    s3_key = f"dubs/{segment.job_id}/{segment_id}.mp3"
                    await self._store.put_object(
                        key=s3_key,
                        body=audio_bytes,
                        content_type="audio/mpeg",
                    )
                    segment.audio_asset_reference = s3_key
                    segment.status = "completed"
                except Exception as exc:
                    segment.status = "failed"
                    segment.meta = {"error": str(exc)}
            else:
                segment.status = "pending"
                segment.meta = {
                    "reason": "ElevenLabs not configured or no translated text"
                }

            await uow.session.flush()
            return segment

    async def submit_review(
        self,
        principal: Principal,
        dub_id: UUID,
        *,
        approved: bool,
        reason: str | None = None,
    ) -> DubSegment:
        """Submit creator review for a dub segment."""
        async with self._uow_factory() as uow:
            segment = await uow.session.get(DubSegment, dub_id)
            if segment is None:
                self._not_found("dub_segment_not_found", "Dub segment not found")

            self._authorizer.require(
                principal,
                Action.CREATOR_READ,
                ResourceScope(organization_id=segment.organization_id),
            )

            segment.review_status = "approved" if approved else "rejected"
            if reason:
                segment.meta = {**segment.meta, "review_reason": reason}
            await uow.session.flush()
            return segment

    @staticmethod
    def _scope(organization_id: UUID) -> ResourceScope:
        return ResourceScope(
            organization_id=organization_id,
        )

    @staticmethod
    def _not_found(code: str, title: str) -> NoReturn:
        raise ProblemException(
            status_code=404,
            type_uri=f"https://oki.example/errors/{code}",
            title=title,
        )
