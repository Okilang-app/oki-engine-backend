from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from oki.api.errors import ProblemException
from oki.identity.dependencies import current_principal
from oki.identity.schemas import Principal
from oki.sponsors.schemas import (
    SponsorDecisionResponse,
    SponsorListResponse,
    SponsorReviewRequest,
)
from oki.sponsors.service import SponsorDetectionService, SponsorReviewService

router = APIRouter(prefix="/api", tags=["sponsors"])


def _detection_service(request: Request) -> SponsorDetectionService:
    service = getattr(request.app.state, "sponsor_detection_service", None)
    if not isinstance(service, SponsorDetectionService):
        raise ProblemException(
            status_code=503,
            code="sponsor_detection_service_unavailable",
            title="Sponsor detection service unavailable",
            detail="Sponsor detection is not available.",
            retryable=True,
        )
    return service


def _review_service(request: Request) -> SponsorReviewService:
    service = getattr(request.app.state, "sponsor_review_service", None)
    if not isinstance(service, SponsorReviewService):
        raise ProblemException(
            status_code=503,
            code="sponsor_review_service_unavailable",
            title="Sponsor review service unavailable",
            detail="Sponsor review is not available.",
            retryable=True,
        )
    return service


@router.get("/jobs/{job_id}/sponsors", response_model=SponsorListResponse)
async def get_sponsors(
    job_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> SponsorListResponse:
    candidates = await _detection_service(request).detect(principal, job_id)
    return SponsorListResponse(job_id=job_id, candidates=candidates)


@router.post("/sponsors/{segment_id}/approve", response_model=SponsorDecisionResponse)
async def approve_sponsor(
    segment_id: UUID,
    request: Request,
    payload: SponsorReviewRequest | None = None,
    principal: Principal = Depends(current_principal),
) -> SponsorDecisionResponse:
    data = payload or SponsorReviewRequest()
    segment = await _review_service(request).approve(
        principal,
        segment_id,
        reason=data.reason,
    )
    return SponsorDecisionResponse(
        id=segment.id,  # Returns the segment id as proxy; real impl may return review row
        ad_segment_id=segment.id,
        decision="approve",
        boundaries_start=None,
        boundaries_end=None,
        reason=data.reason,
        reviewed_by_user_id=principal.user_id,
        reviewed_at=segment.reviewed_at,
        created_at=segment.created_at,
    )


@router.post("/sponsors/{segment_id}/reject", response_model=SponsorDecisionResponse)
async def reject_sponsor(
    segment_id: UUID,
    request: Request,
    payload: SponsorReviewRequest | None = None,
    principal: Principal = Depends(current_principal),
) -> SponsorDecisionResponse:
    data = payload or SponsorReviewRequest()
    segment = await _review_service(request).reject(
        principal,
        segment_id,
        reason=data.reason,
    )
    return SponsorDecisionResponse(
        id=segment.id,
        ad_segment_id=segment.id,
        decision="reject",
        boundaries_start=None,
        boundaries_end=None,
        reason=data.reason,
        reviewed_by_user_id=principal.user_id,
        reviewed_at=segment.reviewed_at,
        created_at=segment.created_at,
    )


@router.post("/sponsors/{segment_id}/replace", response_model=SponsorDecisionResponse)
async def replace_sponsor(
    segment_id: UUID,
    request: Request,
    payload: SponsorReviewRequest | None = None,
    principal: Principal = Depends(current_principal),
) -> SponsorDecisionResponse:
    data = payload or SponsorReviewRequest()
    from oki.jobs.service import JobService
    jobs_svc = getattr(request.app.state, "jobs_service", None)
    if not isinstance(jobs_svc, JobService):
        raise ProblemException(
            status_code=503,
            code="jobs_service_unavailable",
            title="Jobs service unavailable",
            detail="Cannot replace sponsor without jobs service.",
            retryable=True,
        )
    segment = await jobs_svc.replace_sponsor(
        principal,
        segment_id,
        replacement_type="internal_ad",
        ad_id=data.ad_id,
        reason=data.reason,
    )
    return SponsorDecisionResponse(
        id=segment.id,
        ad_segment_id=segment.id,
        decision="replace",
        boundaries_start=None,
        boundaries_end=None,
        reason=data.reason or "Replaced with internal ad",
        reviewed_by_user_id=principal.user_id,
        reviewed_at=segment.reviewed_at,
        created_at=segment.created_at,
    )
