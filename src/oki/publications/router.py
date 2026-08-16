from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from oki.api.errors import ProblemException, generate_correlation_id, parse_correlation_id
from oki.identity.dependencies import current_principal
from oki.identity.schemas import Principal
from oki.publications.schemas import PublicationCreate, PublicationResponse, UploadPrivateRequest
from oki.publications.service import PublicationService

router = APIRouter(prefix="/api", tags=["publications"])


def _service(request: Request) -> PublicationService:
    service = getattr(request.app.state, "publication_service", None)
    if not isinstance(service, PublicationService):
        raise ProblemException(
            status_code=503,
            code="publication_service_unavailable",
            title="Publication service unavailable",
            detail="Publication management is not available.",
            retryable=True,
        )
    return service


def _correlation_id(request: Request) -> UUID:
    value = parse_correlation_id(str(getattr(request.state, "correlation_id", "")))
    return UUID(value or generate_correlation_id())


@router.get("/publications", response_model=list[PublicationResponse])
async def list_publications(
    request: Request,
    principal: Principal = Depends(current_principal),
) -> list[PublicationResponse]:
    publications = await _service(request).list_publications(principal)
    return [PublicationResponse.model_validate(p) for p in publications]


@router.post(
    "/publications",
    response_model=PublicationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_publication(
    payload: PublicationCreate,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> PublicationResponse:
    publication = await _service(request).create(
        payload.job_id,
        principal,
        _correlation_id(request),
    )
    return PublicationResponse.model_validate(publication)


@router.post(
    "/publications/{publication_id}/upload-private",
    response_model=PublicationResponse,
)
async def upload_private(
    publication_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
    payload: UploadPrivateRequest | None = None,
) -> PublicationResponse:
    publication = await _service(request).upload_private(
        publication_id,
        principal,
        _correlation_id(request),
    )
    return PublicationResponse.model_validate(publication)


@router.post(
    "/publications/{publication_id}/publish",
    response_model=PublicationResponse,
)
async def publish_publication(
    publication_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> PublicationResponse:
    publication = await _service(request).publish(
        publication_id,
        principal,
        _correlation_id(request),
    )
    return PublicationResponse.model_validate(publication)


@router.post(
    "/publications/{publication_id}/unpublish",
    response_model=PublicationResponse,
)
async def unpublish_publication(
    publication_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> PublicationResponse:
    publication = await _service(request).unpublish(
        publication_id,
        principal,
        _correlation_id(request),
    )
    return PublicationResponse.model_validate(publication)
