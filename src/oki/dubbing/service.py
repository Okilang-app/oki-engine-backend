"""Dubbing service with ElevenLabs TTS integration."""
from collections.abc import Callable
from typing import Any, NoReturn
from uuid import UUID, uuid4

from sqlalchemy import delete, select

from oki.api.errors import ProblemException
from oki.config import Settings
from oki.db.uow import UnitOfWork
from oki.identity.authorization import Authorizer
from oki.identity.enums import Action
from oki.identity.schemas import Principal, ResourceScope
from oki.dubbing.models import DubAttempt, DubSegment
from oki.dubbing.schemas import DubbingStartResponse
from oki.jobs.enums import WorkflowState
from oki.jobs.models import LocalizationJob
from oki.providers.elevenlabs import ElevenLabsClient
from oki.storage.s3 import S3ObjectStore
from oki.voices.pronunciation import PronunciationDictionary


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
        job_id: UUID,
        *,
        voice_profile_id: UUID | None = None,
        target_language: str | None = None,
    ) -> DubbingStartResponse:
        """Start dubbing for a completed translation job."""
        async with self._uow_factory() as uow:
            job = await uow.session.get(LocalizationJob, job_id)
            if job is None:
                self._not_found("job_not_found", "Job not found")

            self._authorizer.require(
                principal,
                Action.PROJECT_READ,
                ResourceScope(organization_id=job.organization_id),
            )

            # TODO: detailed consent validation block (Task 4)

            # Check workflow state — log warning if unexpected, but don't block for MVP
            allowed_states = {
                WorkflowState.TRANSLATION_REVIEW,
                WorkflowState.DUBBING_RUNNING,
                WorkflowState.AUDIO_REVIEW,
                WorkflowState.AD_REVIEW_REQUIRED,
            }
            if job.state not in allowed_states:
                pass  # MVP: allow dubbing from any state

            # Load translation segments for this job
            from oki.translations.models import TranslationSegments, Translations

            translation = await uow.session.scalar(
                select(Translations)
                .where(Translations.job_id == job_id)
                .order_by(Translations.created_at.desc())
                .limit(1)
            )

            source_segments: list[Any] = []
            actual_target_language = target_language

            if translation is not None:
                source_segments = list(
                    await uow.session.scalars(
                        select(TranslationSegments)
                        .where(TranslationSegments.translation_id == translation.id)
                        .order_by(TranslationSegments.sequence_number)
                    )
                )
                actual_target_language = translation.target_language
            else:
                # Fallback to transcript segments if no translation exists
                from oki.analysis.models import TranscriptSegments

                source_segments = list(
                    await uow.session.scalars(
                        select(TranscriptSegments)
                        .where(TranscriptSegments.job_id == job_id)
                        .order_by(TranscriptSegments.start_time)
                    )
                )

            # Idempotent: delete existing dub segments + attempts
            await uow.session.execute(
                delete(DubSegment).where(DubSegment.job_id == job_id)
            )

            # Update workflow state
            job.state = WorkflowState.DUBBING_RUNNING

            segments: list[DubSegment] = []
            for idx, src in enumerate(source_segments):
                if translation is not None:
                    source_text = src.source_text
                    translated_text = src.translated_text
                    timing_start_ms = (
                        int(src.start_time * 1000)
                        if src.start_time is not None
                        else None
                    )
                    timing_end_ms = (
                        int(src.end_time * 1000)
                        if src.end_time is not None
                        else None
                    )
                    seq = src.sequence_number
                else:
                    source_text = src.text
                    translated_text = src.text
                    timing_start_ms = int(src.start_time * 1000)
                    timing_end_ms = int(src.end_time * 1000)
                    seq = idx

                seg = DubSegment(
                    organization_id=job.organization_id,
                    job_id=job.id,
                    translation_job_id=job.id,
                    sequence_number=seq,
                    source_text=source_text,
                    translated_text=translated_text,
                    voice_profile_id=voice_profile_id,
                    timing_start_ms=timing_start_ms,
                    timing_end_ms=timing_end_ms,
                    status="pending",
                    meta={
                        "target_language": actual_target_language,
                    },
                )
                segments.append(seg)
                uow.session.add(seg)

            await uow.session.flush()
            pending = sum(1 for s in segments if s.status == "pending")
            completed = sum(1 for s in segments if s.status == "completed")
            failed = sum(1 for s in segments if s.status == "failed")
            return DubbingStartResponse(
                job_id=job_id,
                organization_id=job.organization_id,
                total_segments=len(segments),
                pending_segments=pending,
                completed_segments=completed,
                failed_segments=failed,
                status="started",
                voice_profile_id=voice_profile_id,
                target_language=actual_target_language,
                segments=segments,
            )

    async def list_segments(
        self,
        principal: Principal,
        job_id: UUID,
    ) -> list[DubSegment]:
        """List dub segments for a job."""
        async with self._uow_factory() as uow:
            job = await uow.session.get(LocalizationJob, job_id)
            if job is None:
                self._not_found("job_not_found", "Job not found")

            self._authorizer.require(
                principal,
                Action.PROJECT_READ,
                ResourceScope(organization_id=job.organization_id),
            )

            segments = list(
                await uow.session.scalars(
                    select(DubSegment)
                    .where(DubSegment.job_id == job_id)
                    .order_by(DubSegment.sequence_number)
                )
            )
            return segments

    async def get_segment(
        self,
        principal: Principal,
        segment_id: UUID,
    ) -> DubSegment:
        """Get a single dub segment."""
        async with self._uow_factory() as uow:
            segment = await uow.session.get(DubSegment, segment_id)
            if segment is None:
                self._not_found("dub_segment_not_found", "Dub segment not found")

            self._authorizer.require(
                principal,
                Action.PROJECT_READ,
                ResourceScope(organization_id=segment.organization_id),
            )
            return segment

    async def get_playback_url(
        self,
        principal: Principal,
        segment_id: UUID,
    ) -> str:
        """Get a presigned playback URL for a segment's audio."""
        async with self._uow_factory() as uow:
            segment = await uow.session.get(DubSegment, segment_id)
            if segment is None:
                self._not_found("dub_segment_not_found", "Dub segment not found")

            self._authorizer.require(
                principal,
                Action.PROJECT_READ,
                ResourceScope(organization_id=segment.organization_id),
            )

            if not segment.audio_asset_reference:
                self._not_found("audio_not_found", "No audio available for this segment")

            return await self._store.presign_get(segment.audio_asset_reference)

    async def regenerate_segment(
        self,
        principal: Principal,
        segment_id: UUID,
        *,
        voice_profile_id: UUID | None = None,
    ) -> DubSegment:
        """Regenerate audio for a single dub segment using ElevenLabs TTS."""
        async with self._uow_factory() as uow:
            segment = await uow.session.get(DubSegment, segment_id)
            if segment is None:
                self._not_found("dub_segment_not_found", "Dub segment not found")

            self._authorizer.require(
                principal,
                Action.PROJECT_READ,
                ResourceScope(organization_id=segment.organization_id),
            )

            if voice_profile_id is not None:
                segment.voice_profile_id = voice_profile_id

            segment.status = "generating"
            segment.audio_asset_reference = None
            segment.review_status = None
            await uow.session.flush()

            target_language = (
                segment.meta.get("target_language", "en")
                if segment.meta
                else "en"
            )

            # Load pronunciation entries for the voice profile
            from oki.voices.models import PronunciationEntry

            pronunciation_entries: list[dict[str, Any]] = []
            if segment.voice_profile_id is not None:
                entries = list(
                    await uow.session.scalars(
                        select(PronunciationEntry).where(
                            PronunciationEntry.voice_profile_id
                            == segment.voice_profile_id
                        )
                    )
                )
                pronunciation_entries = [
                    {
                        "original_text": e.original_text,
                        "pronunciation": e.pronunciation,
                        "language_code": e.language_code,
                    }
                    for e in entries
                ]

            dictionary = PronunciationDictionary(pronunciation_entries)
            text_to_speak = segment.translated_text or segment.source_text or ""
            processed_text = dictionary.apply(text_to_speak, target_language)

            # Create DubAttempt record
            attempt = DubAttempt(
                organization_id=segment.organization_id,
                dub_segment_id=segment.id,
                provider_key="elevenlabs",
                provider_request_id=None,
                status="pending",
            )
            uow.session.add(attempt)
            await uow.session.flush()

            if self._elevenlabs and text_to_speak:
                try:
                    # Resolve ElevenLabs voice ID from profile
                    elevenlabs_voice_id = "21m00Tcm4TlvDq8ikWAM"  # default Rachel
                    if segment.voice_profile_id is not None:
                        from oki.voices.models import VoiceProfile
                        voice_profile = await uow.session.get(
                            VoiceProfile, segment.voice_profile_id
                        )
                        if voice_profile is not None and voice_profile.provider_voice_id:
                            elevenlabs_voice_id = voice_profile.provider_voice_id
                    audio_bytes = await self._elevenlabs.synthesize(
                        text=processed_text,
                        voice_profile_id=elevenlabs_voice_id,
                    )
                    s3_key = f"dubs/{segment.job_id}/{segment_id}/{uuid4()}.mp3"
                    await self._store.put_object(
                        key=s3_key,
                        body=audio_bytes,
                        content_type="audio/mpeg",
                    )
                    segment.audio_asset_reference = s3_key
                    segment.status = "completed"
                    attempt.status = "completed"
                    attempt.audio_asset_reference = s3_key

                    # TODO: track ProviderUsage if model columns match exactly
                except Exception as exc:
                    segment.status = "failed"
                    segment.meta = {**(segment.meta or {}), "error": str(exc)}
                    attempt.status = "failed"
                    attempt.error_message = str(exc)
            else:
                reason = "ElevenLabs not configured or no text to synthesize"
                segment.status = "pending"
                segment.meta = {**(segment.meta or {}), "reason": reason}
                attempt.status = "pending"
                attempt.meta = {"reason": reason}

            await uow.session.flush()
            await uow.session.refresh(segment)
            return segment

    async def submit_review(
        self,
        principal: Principal,
        segment_id: UUID,
        *,
        approved: bool,
        reason: str | None = None,
    ) -> DubSegment:
        """Submit creator review for a dub segment."""
        async with self._uow_factory() as uow:
            segment = await uow.session.get(DubSegment, segment_id)
            if segment is None:
                self._not_found("dub_segment_not_found", "Dub segment not found")

            self._authorizer.require(
                principal,
                Action.PROJECT_READ,
                ResourceScope(organization_id=segment.organization_id),
            )

            segment.review_status = "approved" if approved else "rejected"
            if reason:
                segment.meta = {**(segment.meta or {}), "review_reason": reason}
            await uow.session.flush()
            await uow.session.refresh(segment)
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
            code=code,
            title=title,
            detail=title,
        )
