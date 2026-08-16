from typing import Any
from uuid import UUID


async def run_audio_mix_task(
    job_id: UUID,
    mix_version_id: UUID,
    *,
    hatchet_workflow_run_id: str | None = None,
    hatchet_task_run_id: str | None = None,
) -> dict[str, Any]:
    """Hatchet task stub for audio mixing execution.

    TODO: wire to AudioService, SourceSeparator, AudioMixer, and AudioQa.
    """
    del hatchet_workflow_run_id, hatchet_task_run_id
    return {
        "job_id": str(job_id),
        "mix_version_id": str(mix_version_id),
        "status": "pending",
        "message": "Audio mix task is a stub",
    }
