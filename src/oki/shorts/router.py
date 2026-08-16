from uuid import UUID

from fastapi import APIRouter, Depends, Request

from oki.api.errors import ProblemException, generate_correlation_id, parse_correlation_id
from oki.identity.dependencies import current_principal
from oki.identity.schemas import Principal
from oki.shorts.schemas import GenerateShortsRequest, ShortCandidateResponse
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
