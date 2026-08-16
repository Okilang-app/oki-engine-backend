from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from oki.api.errors import ProblemException
from oki.identity.dependencies import current_principal
from oki.identity.schemas import Principal
from oki.analysis.schemas import (
    SegmentReviseRequest,
    SegmentReviseResponse,
    TimelineResponse,
)
from oki.analysis.service import AnalysisService

router = APIRouter(prefix="/api", tags=["analysis"])


def _service(request: Request) -> AnalysisService:
    service = getattr(request.app.state, "analysis_service", None)
    if not isinstance(service, AnalysisService):
        raise ProblemException(
            status_code=503,
            code="analysis_service_unavailable",
            title="Analysis service unavailable",
            detail="Analysis management is not available.",
            retryable=True,
        )
    return service


@router.get("/jobs/{job_id}/timeline", response_model=TimelineResponse)
async def get_timeline(
    job_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> TimelineResponse:
    return await _service(request).get_timeline_by_job(principal, job_id)


@router.post(
    "/jobs/{job_id}/segments/{segment_id}/revise",
    response_model=SegmentReviseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def revise_segment(
    job_id: UUID,
    segment_id: UUID,
    payload: SegmentReviseRequest,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> SegmentReviseResponse:
    revision = await _service(request).revise_transcript_segment(
        principal,
        segment_id,
        new_text=payload.new_text,
        reason=payload.reason,
    )
    return SegmentReviseResponse(
        id=revision.id,
        segment_id=segment_id,
        previous_text=revision.previous_value.get("text", ""),
        new_text=payload.new_text,
        created_by_user_id=revision.created_by_user_id,
        created_at=revision.created_at,
    )
