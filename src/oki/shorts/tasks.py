from typing import Any
from uuid import UUID


async def generate_shorts_task(
    job_id: UUID,
    *,
    hatchet_workflow_run_id: str | None = None,
    hatchet_task_run_id: str | None = None,
) -> dict[str, Any]:
    """Hatchet task stub for generating short candidates from a localization job.

    TODO: wire to ShortService and ML pipeline.
    """
    del hatchet_workflow_run_id, hatchet_task_run_id
    return {
        "job_id": str(job_id),
        "status": "pending",
        "message": "Generate shorts task is a stub",
    }
