from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from oki.api.errors import ProblemException
from oki.identity.dependencies import current_principal
from oki.identity.schemas import Principal
from oki.sponsors.schemas import (
    SponsorCandidateResponse,
    SponsorDecisionResponse,
    SponsorListResponse,
    SponsorReviewRequest,
    ManualSponsorCreateRequest,
    ManualSponsorUpdateRequest,
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


@router.post("/jobs/{job_id}/sponsors/manual", response_model=SponsorCandidateResponse, status_code=status.HTTP_201_CREATED)
async def create_manual_sponsor(
    job_id: UUID,
    request: Request,
    payload: ManualSponsorCreateRequest,
    principal: Principal = Depends(current_principal),
) -> SponsorCandidateResponse:
    segment = await _review_service(request).create_manual(principal, job_id, payload)
    return SponsorCandidateResponse(
        id=segment.id,
        job_id=segment.job_id,
        asset_id=segment.asset_id,
        start_time=float(segment.start_time),
        end_time=float(segment.end_time),
        sponsor_name=segment.sponsor_name,
        status=segment.status.value,
        detection_reason="manual",
        confidence=None,
        replacement_type=segment.replacement_type,
        proposed_replacement_ad_id=None,
        proposed_replacement_ad_name=None,
        created_at=segment.created_at,
        updated_at=segment.updated_at,
    )


@router.put("/sponsors/{segment_id}", response_model=SponsorCandidateResponse)
async def update_manual_sponsor(
    segment_id: UUID,
    request: Request,
    payload: ManualSponsorUpdateRequest,
    principal: Principal = Depends(current_principal),
) -> SponsorCandidateResponse:
    segment = await _review_service(request).update_manual(principal, segment_id, payload)
    return SponsorCandidateResponse(
        id=segment.id,
        job_id=segment.job_id,
        asset_id=segment.asset_id,
        start_time=float(segment.start_time),
        end_time=float(segment.end_time),
        sponsor_name=segment.sponsor_name,
        status=segment.status.value,
        detection_reason="manual",
        confidence=None,
        replacement_type=segment.replacement_type,
        proposed_replacement_ad_id=None,
        proposed_replacement_ad_name=None,
        created_at=segment.created_at,
        updated_at=segment.updated_at,
    )


@router.delete("/sponsors/{segment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_manual_sponsor(
    segment_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> None:
    await _review_service(request).delete_manual(principal, segment_id)
