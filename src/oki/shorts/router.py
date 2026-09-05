from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from oki.api.errors import ProblemException, generate_correlation_id, parse_correlation_id
from oki.identity.dependencies import current_principal
from oki.identity.schemas import Principal
from oki.shorts.enums import ShortStatus
from oki.shorts.schemas import (
    GenerateShortsRequest,
    ReviseShortRequest,
    ShortCandidateDetailResponse,
    ShortCandidateResponse,
    ShortVersionResponse,
)
from oki.shorts.service import ShortService

router = APIRouter(prefix="/api", tags=["shorts"])


def _service(request: Request) -> ShortService:
    service = getattr(request.app.state, "shorts_service", None)
    if service is None:
        raise ProblemException(
            status_code=503,
            code="service_unavailable",
            title="Shorts service unavailable",
            detail="The shorts service is not available.",
            retryable=True,
        )
    return service


def _correlation_id(request: Request) -> UUID:
    value = parse_correlation_id(str(getattr(request.state, "correlation_id", "")))
    return UUID(value or generate_correlation_id())


@router.post("/jobs/generate-shorts", response_model=ShortCandidateResponse)
async def generate_shorts(
    payload: GenerateShortsRequest,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> ShortCandidateResponse:
    candidate = await _service(request).generate(
        job_id=payload.job_id,
        principal=principal,
        correlation_id=_correlation_id(request),
    )
    return ShortCandidateResponse.model_validate(candidate)


@router.get("/shorts", response_model=list[ShortCandidateResponse])
async def list_shorts(
    request: Request,
    principal: Principal = Depends(current_principal),
    job_id: UUID | None = Query(None),
    status: ShortStatus | None = Query(None),
) -> list[ShortCandidateResponse]:
    candidates = await _service(request).list_shorts(
        principal=principal,
        job_id=job_id,
        status=status,
    )
    return [ShortCandidateResponse.model_validate(c) for c in candidates]


@router.get("/shorts/{short_id}", response_model=ShortCandidateDetailResponse)
async def get_short(
    short_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> ShortCandidateDetailResponse:
    details = await _service(request).get_short(
        principal=principal,
        candidate_id=short_id,
    )
    return ShortCandidateDetailResponse(
        id=details.candidate.id,
        organization_id=details.candidate.organization_id,
        job_id=details.candidate.job_id,
        status=details.candidate.status,
        source_timestamps=details.candidate.source_timestamps,
        detected_hooks=details.candidate.detected_hooks,
        raw_score=details.candidate.raw_score,
        created_by_user_id=details.candidate.created_by_user_id,
        created_at=details.candidate.created_at,
        updated_at=details.candidate.updated_at,
        versions=[ShortVersionResponse.model_validate(v) for v in details.versions],
        scores=[
            {
                "id": s.id,
                "candidate_id": s.candidate_id,
                "version_id": s.version_id,
                "factor_scores": s.factor_scores,
                "total_score": s.total_score,
                "scored_at": s.scored_at,
            }
            for s in details.scores
        ],
    )


@router.post("/shorts/{short_id}/revise", response_model=ShortVersionResponse)
async def revise_short(
    short_id: UUID,
    request: Request,
    payload: ReviseShortRequest,
    principal: Principal = Depends(current_principal),
) -> ShortVersionResponse:
    version = await _service(request).revise(
        candidate_id=short_id,
        principal=principal,
        correlation_id=_correlation_id(request),
        revision_notes=payload.revision_notes,
    )
    return ShortVersionResponse.model_validate(version)


@router.post("/shorts/{short_id}/approve", response_model=ShortCandidateResponse)
async def approve_short(
    short_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> ShortCandidateResponse:
    await _service(request).approve(
        short_id=short_id,
        principal=principal,
        correlation_id=_correlation_id(request),
    )
    # Return refreshed candidate via get_short
    details = await _service(request).get_short(
        principal=principal,
        candidate_id=short_id,
    )
    return ShortCandidateResponse.model_validate(details.candidate)


@router.post("/shorts/{short_id}/publish", response_model=ShortCandidateResponse)
async def publish_short(
    short_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> ShortCandidateResponse:
    candidate = await _service(request).publish_short(
        short_id=short_id,
        principal=principal,
        correlation_id=_correlation_id(request),
    )
    return ShortCandidateResponse.model_validate(candidate)
