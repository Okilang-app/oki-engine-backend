"""Translation execution task — seeds segments from transcript and translates each one."""
from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from oki.config import Settings
from oki.db.uow import UnitOfWork
from oki.providers.openai_translation import OpenAITranslationClient

log = logging.getLogger(__name__)

# Max concurrent translation calls to avoid overwhelming the API
_CONCURRENCY = 8


async def translation_execution_task(
    translation_id: UUID,
    job_id: UUID,
    asset_id: UUID,
    source_language: str,
    target_language: str,
) -> dict:
    from oki.analysis.models import TranscriptSegments
    from oki.translations.models import TranslationSegments, Translations
    from oki.translations.enums import TranslationStatus

    settings = Settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with UnitOfWork(session_factory) as uow:
            translation = await uow.session.get(Translations, translation_id)
            if translation is None:
                return {"task": "translation_execution", "status": "not_found", "translation_id": str(translation_id)}

            segments = list(
                await uow.session.scalars(
                    select(TranscriptSegments)
                    .where(TranscriptSegments.job_id == job_id)
                    .order_by(TranscriptSegments.start_time)
                )
            )

            if not segments:
                translation.status = TranslationStatus.APPROVED
                await uow.session.flush()
                return {"task": "translation_execution", "status": "no_segments", "segments_created": 0}

            await uow.session.execute(
                delete(TranslationSegments).where(TranslationSegments.translation_id == translation_id)
            )
            translation.status = TranslationStatus.IN_PROGRESS
            await uow.session.flush()

        # Translate all segments concurrently (bounded by semaphore)
        client = OpenAITranslationClient(settings)
        openai_configured = bool(settings.openai_api_key or settings.azure_openai_endpoint)
        sem = asyncio.Semaphore(_CONCURRENCY)

        async def translate_one(seg, idx: int) -> dict:
            if not openai_configured:
                log.warning("No OpenAI/Azure configured — using placeholder translation")
                return {
                    "source_segment_id": seg.id,
                    "sequence_number": idx,
                    "source_text": seg.text,
                    "translated_text": f"[{target_language.upper()}] {seg.text}",
                    "start_time": seg.start_time,
                    "end_time": seg.end_time,
                    "organization_id": seg.organization_id,
                }
            async with sem:
                try:
                    result = await client.translate(
                        text=seg.text,
                        target_language=target_language,
                        source_language=(source_language if source_language != "auto" else None),
                    )
                    translated_text = result["translated_text"] or seg.text
                    if not result["translated_text"]:
                        log.warning("translate() returned empty string for segment %s", seg.id)
                except Exception:
                    log.exception("Translation API call failed for segment %s", seg.id)
                    translated_text = seg.text

            return {
                "source_segment_id": seg.id,
                "sequence_number": idx,
                "source_text": seg.text,
                "translated_text": translated_text,
                "start_time": seg.start_time,
                "end_time": seg.end_time,
                "organization_id": seg.organization_id,
            }

        translated_segments = await asyncio.gather(
            *[translate_one(seg, idx) for idx, seg in enumerate(segments)]
        )

        async with UnitOfWork(session_factory) as uow:
            translation = await uow.session.get(Translations, translation_id)
            if translation is None:
                return {"task": "translation_execution", "status": "lost", "translation_id": str(translation_id)}

            for ts_data in translated_segments:
                uow.session.add(
                    TranslationSegments(
                        organization_id=ts_data["organization_id"],
                        translation_id=translation_id,
                        source_segment_id=ts_data["source_segment_id"],
                        sequence_number=ts_data["sequence_number"],
                        source_text=ts_data["source_text"],
                        translated_text=ts_data["translated_text"],
                        start_time=ts_data["start_time"],
                        end_time=ts_data["end_time"],
                        status=TranslationStatus.REVIEW_PENDING,
                    )
                )

            translation.status = TranslationStatus.REVIEW_PENDING
            await uow.session.flush()

        return {
            "task": "translation_execution",
            "translation_id": str(translation_id),
            "segments_created": len(translated_segments),
            "status": "completed",
        }
    finally:
        await engine.dispose()
