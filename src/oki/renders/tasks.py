from typing import Any
from uuid import UUID


async def run_render_task(
    job_id: UUID,
    render_attempt_id: UUID,
    *,
    hatchet_workflow_run_id: str | None = None,
    hatchet_task_run_id: str | None = None,
) -> dict[str, Any]:
    """Hatchet task stub for render execution.

    TODO: wire to RenderService, FFmpegPlanBuilder, and RenderQa.
    """
    del hatchet_workflow_run_id, hatchet_task_run_id
    return {
        "job_id": str(job_id),
        "render_attempt_id": str(render_attempt_id),
        "status": "pending",
        "message": "Render task is a stub",
    }
