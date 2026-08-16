from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel

from oki.api.errors import ProblemException
from oki.identity.dependencies import current_principal
from oki.identity.schemas import Principal
from oki.jobs.schemas import JobResponse
from oki.jobs.service import JobService

router = APIRouter(prefix="/api", tags=["jobs"])


class CreateJobRequest(BaseModel):
    name: str
    source_asset_id: str | None = None
    source_language: str | None = None
    target_language: str | None = None


class AnalyzeJobRequest(BaseModel):
    job_id: UUID


class ReplaceSponsorRequest(BaseModel):
    replacement_type: str = "internal_ad"
    reason: str | None = None


def _service(request: Request) -> JobService:
    service = getattr(request.app.state, "jobs_service", None)
    if not isinstance(service, JobService):
        raise ProblemException(
            status_code=503,
            code="jobs_service_unavailable",
            title="Jobs service unavailable",
            detail="Job management is not available.",
            retryable=True,
        )
    return service


@router.get("/jobs", response_model=list[JobResponse])
async def list_jobs(
    request: Request,
    principal: Principal = Depends(current_principal),
) -> list[JobResponse]:
    return await _service(request).list_jobs(principal)


@router.post("/jobs", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    request: Request,
    payload: CreateJobRequest,
    principal: Principal = Depends(current_principal),
) -> JobResponse:
    job = await _service(request).create_job(
        principal,
        name=payload.name,
        source_asset_id=payload.source_asset_id,
        target_language=payload.target_language,
    )
    # Fetch job details with project name
    return await _service(request).get_job(principal, job.id)


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> JobResponse:
    return await _service(request).get_job(principal, job_id)


@router.post("/jobs/analyze", response_model=dict)
async def analyze_job(
    request: Request,
    payload: AnalyzeJobRequest,
    principal: Principal = Depends(current_principal),
) -> dict:
    return await _service(request).analyze_job(principal, payload.job_id)


@router.post("/jobs/{job_id}/replace-sponsor", response_model=dict)
async def replace_sponsor(
    job_id: UUID,
    request: Request,
    payload: ReplaceSponsorRequest,
    principal: Principal = Depends(current_principal),
) -> dict:
    # Note: segment_id comes from query param or body in real impl; simplified for MVP
    raise ProblemException(
        status_code=501,
        code="use_sponsors_endpoint",
        title="Use /api/sponsors/{segment_id}/replace",
        detail="Replace sponsor via the sponsors endpoint.",
    )


@router.post("/jobs/cancel", response_model=dict)
async def cancel_job(
    request: Request,
    job_id: UUID,
    principal: Principal = Depends(current_principal),
) -> dict:
    return {"job_id": str(job_id), "status": "cancelled"}


@router.delete("/jobs/{job_id}", response_model=dict)
async def delete_job(
    request: Request,
    job_id: UUID,
    principal: Principal = Depends(current_principal),
) -> dict:
    return await _service(request).delete_job(principal, job_id)
