from uuid import UUID

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request, status
import jwt

from oki.api.errors import ProblemException, generate_correlation_id, parse_correlation_id
from oki.config import get_settings
from oki.identity.dependencies import current_principal
from oki.identity.schemas import Principal
from oki.reviews.enums import ReviewDecisionType
from oki.reviews.schemas import (
    CommentCreate,
    CommentResponse,
    DecisionRequest,
    ReviewDecisionResponse,
    ReviewPackageResponse,
    ReviewPackageVersionResponse,
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


@router.post("/reviews/{job_id}/create-package", response_model=ReviewPackageResponse)
async def create_review_package(
    job_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> ReviewPackageResponse:
    package = await _service(request).create_package(
        job_id,
        principal,
        _correlation_id(request),
    )
    return ReviewPackageResponse.model_validate(package)


@router.post("/reviews/{package_id}/comment", response_model=CommentResponse)
async def add_comment(
    package_id: UUID,
    request: Request,
    payload: CommentCreate,
    principal: Principal = Depends(current_principal),
) -> CommentResponse:
    comment = await _service(request).comment(
        package_id,
        text=payload.text,
        principal=principal,
        correlation_id=_correlation_id(request),
        line_reference=payload.line_reference,
    )
    return CommentResponse.model_validate(comment)


@router.get("/reviews/{job_id}/versions", response_model=list[ReviewPackageVersionResponse])
async def list_review_versions(
    job_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> list[ReviewPackageVersionResponse]:
    versions = await _service(request).get_versions_by_job(job_id, principal)
    return [ReviewPackageVersionResponse.model_validate(v) for v in versions]


@router.post("/reviews/{version_id}/invalidate", status_code=status.HTTP_204_NO_CONTENT)
async def invalidate_version(
    version_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> None:
    await _service(request).invalidate_for_change(
        version_id,
        principal,
        _correlation_id(request),
    )


@router.post("/reviews/{job_id}/request-changes", response_model=ReviewDecisionResponse)
async def request_changes(
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
        decision=ReviewDecisionType.CHANGES_REQUESTED,
    )
    return ReviewDecisionResponse.model_validate(decision)

@router.post("/reviews/{job_id}/creator-link")
async def create_creator_link(
    job_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> dict:
    correlation_id = generate_correlation_id()
    package = await _service(request).create_package(
        job_id, principal, correlation_id
    )
    settings = get_settings()
    secret = settings.review_link_secret or "change-me"
    token = jwt.encode(
        {
            "sub": str(principal.user_id),
            "scope": "review",
            "pkg": str(package.id),
            "exp": datetime.now(timezone.utc) + timedelta(days=7),
        },
        secret,
        algorithm="HS256",
    )
    return {"token": token, "expires_in_days": 7}


@router.get("/reviews/creator/{token}")
async def get_creator_review(token: str) -> dict:
    settings = get_settings()
    secret = settings.review_link_secret or "change-me"
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise ProblemException(
            status_code=401,
            code="invalid_token",
            title="Invalid token",
            detail="The review link is invalid or expired.",
        )
    return {
        "package_id": payload.get("pkg"),
        "user_id": payload.get("sub"),
        "scope": payload.get("scope"),
    }
