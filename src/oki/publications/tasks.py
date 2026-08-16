from typing import Any
from uuid import UUID


async def upload_to_platform_task(
    publication_id: UUID,
    *,
    hatchet_workflow_run_id: str | None = None,
    hatchet_task_run_id: str | None = None,
) -> dict[str, Any]:
    """Hatchet task stub for uploading a private video to the target platform.

    TODO: wire to PlatformUploadService and YouTube Data API v3.
    """
    del hatchet_workflow_run_id, hatchet_task_run_id
    return {
        "publication_id": str(publication_id),
        "status": "pending",
        "message": "Upload to platform task is a stub",
    }


async def publish_task(
    publication_id: UUID,
    *,
    hatchet_workflow_run_id: str | None = None,
    hatchet_task_run_id: str | None = None,
) -> dict[str, Any]:
    """Hatchet task stub for transitioning a private video to public.

    TODO: wire to PlatformPublishService and YouTube Data API v3.
    """
    del hatchet_workflow_run_id, hatchet_task_run_id
    return {
        "publication_id": str(publication_id),
        "status": "pending",
        "message": "Publish task is a stub",
    }
