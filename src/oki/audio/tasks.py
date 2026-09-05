"""Audio mix task — advances mix version through plan and marks completion."""
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
    hatchet_workflow_run_id: str | None = None,
    hatchet_task_run_id: str | None = None,
) -> dict[str, Any]:
    """Execute audio mixing for a localization job mix version.

    Marks the mix as processing, runs the mix plan, then saves the result.
    If stems are present, performs source separation + mixing via AudioMixer.
    Falls back to plan-only mode when no stems are uploaded.
    """
    from oki.audio.models import AudioMixVersion
    from oki.jobs.models import LocalizationJob

    settings = Settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with UnitOfWork(session_factory) as uow:
            mix = await uow.session.get(AudioMixVersion, mix_version_id)
            if mix is None:
                return {"mix_version_id": str(mix_version_id), "status": "not_found"}

            job = await uow.session.get(LocalizationJob, job_id)
            if job is None:
                return {"job_id": str(job_id), "status": "job_not_found"}

            # Idempotency: already completed
            if mix.status == "completed":
                return {
                    "job_id": str(job_id),
                    "mix_version_id": str(mix_version_id),
                    "status": "already_done",
                }

            mix.status = "processing"
            current_plan = dict(mix.mix_plan or {})
            await uow.session.flush()

        # Mixing runs outside the transaction
        from oki.audio.mixing import AudioMixer

        mixer = AudioMixer(
            output_bucket=settings.s3_bucket,
            s3_endpoint=settings.s3_endpoint_url,
        )
        dialogue_tracks = current_plan.get("dialogue_tracks", [])
        music_stems = current_plan.get("music_stems", [])
        sfx_stems = current_plan.get("sfx_stems", [])

        mix_plan_result = mixer.mix(
            dialogue_tracks=dialogue_tracks,
            music_stems=music_stems,
            sfx_stems=sfx_stems,
        )

        async with UnitOfWork(session_factory) as uow:
            mix = await uow.session.get(AudioMixVersion, mix_version_id)
            if mix is None:
                return {"mix_version_id": str(mix_version_id), "status": "lost"}
            mix.mix_plan = {**current_plan, **mix_plan_result, "steps": ["completed"]}
            mix.status = "completed"
            await uow.session.flush()

        return {
            "job_id": str(job_id),
            "mix_version_id": str(mix_version_id),
            "status": "completed",
            "hatchet_workflow_run_id": hatchet_workflow_run_id,
        }
    finally:
        await engine.dispose()
