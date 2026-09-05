"""Translation execution task — seeds segments from transcript and translates each one."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from oki.config import Settings
from oki.db.uow import UnitOfWork
from oki.providers.openai_translation import OpenAITranslationClient


async def translation_execution_task(
    translation_id: UUID,
    job_id: UUID,
    asset_id: UUID,
    source_language: str,
    target_language: str,
) -> dict:
    """Execute translation for all segments of an asset.

    Loads TranscriptSegments for the job, calls OpenAI translation for each,
    creates TranslationSegments and saves back_translation per segment.
    """
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
                return {
                    "task": "translation_execution",
                    "status": "not_found",
                    "translation_id": str(translation_id),
                }

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
                return {
                    "task": "translation_execution",
                    "status": "no_segments",
                    "segments_created": 0,
                }

            await uow.session.execute(
                delete(TranslationSegments).where(
                    TranslationSegments.translation_id == translation_id
                )
            )
            translation.status = TranslationStatus.IN_PROGRESS
            await uow.session.flush()

        # Translation runs outside the transaction — expensive and retryable
        client = OpenAITranslationClient(settings)
        openai_configured = bool(
            settings.openai_api_key or settings.azure_openai_endpoint
        )

        translated_segments: list[dict] = []
        for seg in segments:
            if openai_configured:
                try:
                    result = await client.translate(
                        text=seg.text,
                        target_language=target_language,
                        source_language=(
                            source_language if source_language != "auto" else None
                        ),
                    )
                    translated_text = result["translated_text"]
                    bt_result = await client.translate(
                        text=translated_text,
                        target_language=(
                            source_language if source_language != "auto" else "en"
                        ),
                        source_language=target_language,
                    )
                    back_translation: str | None = bt_result["translated_text"]
                except Exception:
                    translated_text = seg.text
                    back_translation = None
            else:
                translated_text = f"[{target_language.upper()}] {seg.text}"
                back_translation = None

            translated_segments.append(
                {
                    "source_segment_id": seg.id,
                    "sequence_number": len(translated_segments),
                    "source_text": seg.text,
                    "translated_text": translated_text,
                    "back_translation": back_translation,
                    "start_time": seg.start_time,
                    "end_time": seg.end_time,
                    "organization_id": seg.organization_id,
                }
            )

        async with UnitOfWork(session_factory) as uow:
            translation = await uow.session.get(Translations, translation_id)
            if translation is None:
                return {
                    "task": "translation_execution",
                    "status": "lost",
                    "translation_id": str(translation_id),
                }

            for ts_data in translated_segments:
                uow.session.add(
                    TranslationSegments(
                        organization_id=ts_data["organization_id"],
                        translation_id=translation_id,
                        source_segment_id=ts_data["source_segment_id"],
                        sequence_number=ts_data["sequence_number"],
                        source_text=ts_data["source_text"],
                        translated_text=ts_data["translated_text"],
                        back_translation=ts_data.get("back_translation"),
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
