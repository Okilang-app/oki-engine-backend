"""Dubbing execution task — calls ElevenLabs TTS for each approved translation segment."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from oki.config import Settings
from oki.db.uow import UnitOfWork


async def run_dubbing_task(
    job_id: UUID,
    *,
    hatchet_workflow_run_id: str | None = None,
    hatchet_task_run_id: str | None = None,
) -> dict[str, Any]:
    """Execute TTS dubbing for all segments in an approved translation."""
    from oki.jobs.models import LocalizationJob
    from oki.translations.models import TranslationSegments, Translations
    from oki.translations.enums import TranslationStatus

    settings = Settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with UnitOfWork(session_factory) as uow:
            job = await uow.session.get(LocalizationJob, job_id)
            if job is None:
                return {"job_id": str(job_id), "status": "not_found"}

            translation = await uow.session.scalar(
                select(Translations)
                .where(
                    Translations.job_id == job_id,
                    Translations.status == TranslationStatus.APPROVED,
                )
                .limit(1)
            )
            if translation is None:
                return {"job_id": str(job_id), "status": "no_approved_translation"}

            segments = list(await uow.session.scalars(
                select(TranslationSegments)
                .where(TranslationSegments.translation_id == translation.id)
                .order_by(TranslationSegments.sequence_number)
            ))

        if not segments:
            return {"job_id": str(job_id), "status": "no_segments"}

        from oki.providers.elevenlabs import ElevenLabsClient
        from oki.storage.s3 import S3ObjectStore

        store = S3ObjectStore(settings)
        elevenlabs = ElevenLabsClient(settings) if settings.elevenlabs_api_key else None

        dub_results: list[dict] = []
        for seg in segments:
            if not seg.translated_text:
                dub_results.append({"segment_id": str(seg.id), "status": "skipped_empty"})
                continue
            if elevenlabs is None:
                dub_results.append({"segment_id": str(seg.id), "status": "skipped_no_tts"})
                continue
            try:
                audio_bytes = await elevenlabs.synthesize(text=seg.translated_text)
                storage_key = f"dubs/{job_id}/{seg.id}.mp3"
                await store.put_object(storage_key, audio_bytes, content_type="audio/mpeg")
                dub_results.append({
                    "segment_id": str(seg.id),
                    "storage_key": storage_key,
                    "status": "completed",
                })
            except Exception as exc:
                dub_results.append({
                    "segment_id": str(seg.id),
                    "status": "failed",
                    "error": str(exc)[:200],
                })

        completed = sum(1 for r in dub_results if r["status"] == "completed")
        return {
            "job_id": str(job_id),
            "status": "completed",
            "segments_dubbed": completed,
            "total_segments": len(segments),
            "hatchet_workflow_run_id": hatchet_workflow_run_id,
        }
    finally:
        await engine.dispose()
