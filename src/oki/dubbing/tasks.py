from typing import Any
from uuid import UUID


async def run_dubbing_task(
    job_id: UUID,
    *,
    hatchet_workflow_run_id: str | None = None,
    hatchet_task_run_id: str | None = None,
) -> dict[str, Any]:
    """Hatchet task stub for dubbing execution.

    TODO: wire to DubbingService, TTS provider, and pronunciation dictionary.
    """
    del hatchet_workflow_run_id, hatchet_task_run_id
    return {
        "job_id": str(job_id),
        "status": "pending",
        "message": "Dubbing task is a stub",
    }
