from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from oki.api.errors import ProblemException, generate_correlation_id, parse_correlation_id
from oki.identity.dependencies import current_principal
from oki.identity.schemas import Principal
from oki.reviews.schemas import (
    DecisionRequest,
    ReviewDecisionResponse,
    ReviewPackageResponse,
)
from oki.reviews.service import ReviewService

router = APIRouter(prefix="/api", tags=["reviews"])


def _service(request: Request) -> ReviewService:
    service = getattr(request.app.state, "reviews_service", None)
    if not isinstance(service, ReviewService):
        raise ProblemException(
            status_code=503,
            code="reviews_service_unavailable",
            title="Reviews service unavailable",
            detail="Review management is not available.",
            retryable=True,
        )
    return service


def _correlation_id(request: Request) -> UUID:
    value = parse_correlation_id(str(getattr(request.state, "correlation_id", "")))
    return UUID(value or generate_correlation_id())


@router.get("/reviews/{job_id}", response_model=ReviewPackageResponse)
async def get_review_package(
    job_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> ReviewPackageResponse:
    details = await _service(request).get_package_by_job(job_id, principal)
    return ReviewPackageResponse.model_validate(details.package)


@router.post("/reviews/{job_id}/approve", response_model=ReviewDecisionResponse)
async def approve_review(
    job_id: UUID,
    request: Request,
    payload: DecisionRequest | None = None,
    principal: Principal = Depends(current_principal),
) -> ReviewDecisionResponse:
    data = payload or DecisionRequest()
    decision = await _service(request).approve_job(
        job_id,
        principal,
        reason=data.reason,
        correlation_id=_correlation_id(request),
    )
    return ReviewDecisionResponse.model_validate(decision)


@router.post("/reviews/{job_id}/reject", response_model=ReviewDecisionResponse)
async def reject_review(
    job_id: UUID,
    request: Request,
    payload: DecisionRequest | None = None,
    principal: Principal = Depends(current_principal),
) -> ReviewDecisionResponse:
    data = payload or DecisionRequest()
    decision = await _service(request).reject_job(
        job_id,
        principal,
        reason=data.reason,
        correlation_id=_correlation_id(request),
    )
    return ReviewDecisionResponse.model_validate(decision)
