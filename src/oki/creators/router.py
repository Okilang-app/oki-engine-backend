from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from oki.api.errors import generate_correlation_id, parse_correlation_id
from oki.creators.models import Creator
from oki.creators.schemas import (
    ChannelOwnershipEvidenceResponse,
    CreatorBrandGuideResponse,
    CreatorChannelResponse,
    CreatorCreate,
    CreatorResponse,
    CreatorRestrictionResponse,
)
from oki.creators.service import CreatorDetails, CreatorService
from oki.identity.dependencies import current_principal
from oki.identity.schemas import Principal
from oki.rights.enums import ConsentDecision

router = APIRouter(prefix="/api", tags=["creators"])


def _service(request: Request) -> CreatorService:
    service = getattr(request.app.state, "creator_service", None)
    if not isinstance(service, CreatorService):
        from oki.api.errors import ProblemException

        raise ProblemException(
            status_code=503,
            code="creator_service_unavailable",
            title="Creator service unavailable",
            detail="Creator management is not available.",
            retryable=True,
        )
    return service


def _correlation_id(request: Request) -> UUID:
    value = parse_correlation_id(str(getattr(request.state, "correlation_id", "")))
    return UUID(value or generate_correlation_id())


def _list_response(creator: Creator) -> CreatorResponse:
    return CreatorResponse(
        id=creator.id,
        organization_id=creator.organization_id,
        legal_name=creator.legal_name,
        display_name=creator.display_name,
        primary_email=creator.primary_email,
        manager_name=creator.manager_name,
        manager_email=creator.manager_email,
        status=creator.status,
        channels=[],
        brand_guides=[],
        restrictions=[],
        created_at=creator.created_at,
        updated_at=creator.updated_at,
        version=creator.version,
    )


def _response(details: CreatorDetails) -> CreatorResponse:
    creator = details.creator
    return CreatorResponse(
        id=creator.id,
        organization_id=creator.organization_id,
        legal_name=creator.legal_name,
        display_name=creator.display_name,
        primary_email=creator.primary_email,
        manager_name=creator.manager_name,
        manager_email=creator.manager_email,
        status=creator.status,
        channels=[
            CreatorChannelResponse(
                id=channel.id,
                platform=channel.platform,
                external_channel_id=channel.external_channel_id,
                handle=channel.handle,
                canonical_url=channel.canonical_url,
                ownership_verified=bool(evidence)
                and evidence[-1].decision is ConsentDecision.GRANTED,
                ownership_evidence=[
                    ChannelOwnershipEvidenceResponse.model_validate(record)
                    for record in evidence
                ],
                created_at=channel.created_at,
            )
            for channel, evidence in details.channels
        ],
        brand_guides=[
            CreatorBrandGuideResponse.model_validate(guide) for guide in details.brand_guides
        ],
        restrictions=[
            CreatorRestrictionResponse.model_validate(restriction)
            for restriction in details.restrictions
        ],
        created_at=creator.created_at,
        updated_at=creator.updated_at,
        version=creator.version,
    )


@router.post("/creators", response_model=CreatorResponse, status_code=status.HTTP_201_CREATED)
async def create_creator(
    payload: CreatorCreate,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> CreatorResponse:
    service = _service(request)
    creator = await service.create(
        principal,
        payload,
        correlation_id=_correlation_id(request),
    )
    return _response(await service.get_details(principal, creator.id))


@router.get("/creators", response_model=list[CreatorResponse])
async def list_creators(
    request: Request,
    principal: Principal = Depends(current_principal),
) -> list[CreatorResponse]:
    return [_list_response(c) for c in await _service(request).list_creators(principal)]


@router.get("/creators/{creator_id}", response_model=CreatorResponse)
async def get_creator(
    creator_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> CreatorResponse:
    return _response(await _service(request).get_details(principal, creator_id))
