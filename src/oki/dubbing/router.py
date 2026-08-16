from uuid import UUID

from fastapi import APIRouter, Depends, Request

from oki.api.errors import generate_correlation_id, parse_correlation_id
from oki.identity.dependencies import current_principal
from oki.identity.schemas import Principal
from oki.dubbing.schemas import DubbingResponse
from oki.dubbing.service import DubbingService

router = APIRouter(prefix="/api", tags=["dubbing"])


def _service(request: Request) -> DubbingService:
    service = getattr(request.app.state, "dubbing_service", None)
    if service is None:
        raise RuntimeError("DubbingService not available")
    return service


def _correlation_id(request: Request) -> UUID:
    value = parse_correlation_id(str(getattr(request.state, "correlation_id", "")))
    return UUID(value or generate_correlation_id())


@router.post("/jobs/dub", response_model=DubbingResponse)
async def start_dubbing(
    request: Request,
    translation_id: UUID,
    principal: Principal = Depends(current_principal),
) -> DubbingResponse:
    segments = await _service(request).start(
        principal,
        translation_id,
        correlation_id=_correlation_id(request),
    )
    # TODO: compute composite response once Dubbings model exists
    return DubbingResponse(
        job_id=translation_id,
        organization_id=principal.user_id,  # placeholder
        segments=[],
        status="pending",
        created_at=__import__("datetime").datetime.utcnow(),
        updated_at=__import__("datetime").datetime.utcnow(),
    )
