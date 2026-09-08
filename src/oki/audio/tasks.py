"""Audio mix task — delegates to the pipeline in dubbing/tasks.py."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from oki.config import Settings
from oki.db.uow import UnitOfWork


async def run_audio_mix_task(
    job_id: UUID,
    mix_version_id: UUID,
    *,
    mix_overrides: dict | None = None,
    hatchet_workflow_run_id: str | None = None,
    hatchet_task_run_id: str | None = None,
) -> dict[str, Any]:
    """Re-run the audio mix pipeline for an existing set of TTS segments.

    Looks up completed DubSegments for the job and passes them to the pipeline.
    """
    from sqlalchemy import select
    from oki.audio.models import AudioMixVersion
    from oki.dubbing.models import DubSegment
    from oki.dubbing.tasks import run_audio_mix_pipeline

    settings = Settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with UnitOfWork(session_factory) as uow:
            mix = await uow.session.get(AudioMixVersion, mix_version_id)
            if mix is None:
                return {"mix_version_id": str(mix_version_id), "status": "not_found"}

            if mix.status == "completed":
                return {"mix_version_id": str(mix_version_id), "status": "already_done"}

            dub_segments = list(await uow.session.scalars(
                select(DubSegment)
                .where(
                    DubSegment.job_id == job_id,
                    DubSegment.audio_asset_reference.isnot(None),
                )
                .order_by(DubSegment.sequence_number)
            ))

        if not dub_segments:
            async with UnitOfWork(session_factory) as uow:
                mix_row = await uow.session.get(AudioMixVersion, mix_version_id)
                if mix_row:
                    mix_row.status = "failed"
                    mix_row.mix_plan = {"error": "no_dubbed_segments"}
                    await uow.session.flush()
            return {"job_id": str(job_id), "status": "no_dubbed_segments"}

        tts_results = [
            {
                "segment_id": str(s.id),
                "storage_key": s.audio_asset_reference,
                "start_time": (s.timing_start_ms / 1000.0) if s.timing_start_ms is not None else None,
                "end_time": (s.timing_end_ms / 1000.0) if s.timing_end_ms is not None else None,
                "status": "completed",
            }
            for s in dub_segments
        ]

        return await run_audio_mix_pipeline(
            job_id=job_id,
            tts_results=tts_results,
            session_factory=session_factory,
            settings=settings,
            mix_overrides=mix_overrides,
        )
    finally:
        await engine.dispose()
