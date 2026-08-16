from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status

from oki.api.errors import generate_correlation_id, parse_correlation_id
from oki.identity.dependencies import current_principal
from oki.identity.schemas import Principal
from oki.renders.schemas import (
    CreateRenderRequest,
    RenderJobResponse,
    RenderResponse,
    UpdateRenderStatusRequest,
)
from oki.renders.service import RenderService

router = APIRouter(prefix="/api", tags=["renders"])


def _service(request: Request) -> RenderService:
    service = getattr(request.app.state, "render_service", None)
    if service is None:
        raise RuntimeError("RenderService not available")
    return service


def _correlation_id(request: Request) -> UUID:
    value = parse_correlation_id(str(getattr(request.state, "correlation_id", "")))
    return UUID(value or generate_correlation_id())


@router.post("/jobs/render", response_model=RenderJobResponse)
async def start_render(
    request: Request,
    payload: CreateRenderRequest,
    principal: Principal = Depends(current_principal),
) -> RenderJobResponse:
    """Backward-compat: create a RenderJob from a job_id and queue execution."""
    render_job = await _service(request).create_render_job(
        principal,
        project_id=payload.project_id,
        job_id=payload.job_id,
    )
    return RenderJobResponse.model_validate(render_job)


@router.get("/renders", response_model=list[RenderJobResponse])
async def list_render_jobs(
    request: Request,
    principal: Principal = Depends(current_principal),
) -> list[RenderJobResponse]:
    jobs = await _service(request).list_render_jobs(principal)
    return [RenderJobResponse.model_validate(job) for job in jobs]


@router.post(
    "/renders",
    response_model=RenderJobResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_render_job(
    request: Request,
    payload: CreateRenderRequest,
    principal: Principal = Depends(current_principal),
) -> RenderJobResponse:
    job = await _service(request).create_render_job(
        principal,
        project_id=payload.project_id,
        job_id=payload.job_id,
    )
    return RenderJobResponse.model_validate(job)


@router.get("/renders/{render_id}", response_model=RenderJobResponse)
async def get_render_job(
    request: Request,
    render_id: UUID,
    principal: Principal = Depends(current_principal),
) -> RenderJobResponse:
    job = await _service(request).get_render_job(principal, render_id)
    return RenderJobResponse.model_validate(job)


@router.post("/renders/{render_id}/execute")
async def execute_render(
    render_id: UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    principal: Principal = Depends(current_principal),
) -> dict:
    """Trigger the actual video rendering in a background task."""
    # Verify access
    job = await _service(request).get_render_job(principal, render_id)
    # Run in background
    background_tasks.add_task(_service(request).execute_render_job, render_id)
    return {"render_id": str(render_id), "status": "started"}


@router.get("/renders/{render_id}/playback-url")
async def get_render_playback_url(
    render_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> dict:
    """Return a presigned URL to download the rendered output video."""
    from oki.config import Settings
    from botocore.config import Config as BotoConfig
    settings = Settings()
    import boto3
    s3 = boto3.client(
        "s3",
        endpoint_url=str(settings.s3_public_url or settings.s3_endpoint_url),
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        config=BotoConfig(signature_version="s3v4"),
    )
    job = await _service(request).get_render_job(principal, render_id)
    if not job.output_storage_key:
        raise RuntimeError("Render output not available yet")
    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket, "Key": job.output_storage_key},
        ExpiresIn=3600,
    )
    return {"playback_url": url, "render_id": str(render_id)}


@router.post("/renders/{render_id}/status", response_model=RenderJobResponse)
async def update_render_status(
    request: Request,
    render_id: UUID,
    payload: UpdateRenderStatusRequest,
    principal: Principal = Depends(current_principal),
) -> RenderJobResponse:
    job = await _service(request).update_render_status(
        principal,
        render_id,
        status=payload.status,
        progress_percent=payload.progress_percent,
        output_storage_key=payload.output_storage_key,
    )
    return RenderJobResponse.model_validate(job)
