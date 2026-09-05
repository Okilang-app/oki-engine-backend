from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from oki.api.errors import ProblemException, generate_correlation_id, parse_correlation_id
from oki.identity.dependencies import current_principal
from oki.identity.schemas import Principal
from oki.campaigns.schemas import (
    CampaignCreate,
    CampaignResponse,
    CampaignUpdate,
    CreativeCreate,
    CreativeResponse,
    CreativeUpdate,
)
from oki.campaigns.service import CampaignService

router = APIRouter(prefix="/api", tags=["campaigns"])


def _service(request: Request) -> CampaignService:
    service = getattr(request.app.state, "campaign_service", None)
    if not isinstance(service, CampaignService):
        raise ProblemException(
            status_code=503,
            code="campaign_service_unavailable",
            title="Campaign service unavailable",
            detail="Campaign management is not available.",
            retryable=True,
        )
    return service


def _correlation_id(request: Request) -> UUID:
    value = parse_correlation_id(str(getattr(request.state, "correlation_id", "")))
    return UUID(value or generate_correlation_id())


@router.get("/campaigns", response_model=list[CampaignResponse])
async def list_campaigns(
    request: Request,
    principal: Principal = Depends(current_principal),
) -> list[CampaignResponse]:
    campaigns = await _service(request).list_campaigns(principal)
    return [CampaignResponse.model_validate(c) for c in campaigns]


@router.post("/campaigns", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    request: Request,
    payload: CampaignCreate,
    principal: Principal = Depends(current_principal),
) -> CampaignResponse:
    correlation_id = _correlation_id(request)
    campaign = await _service(request).create_campaign(principal, payload)
    return CampaignResponse.model_validate(campaign)


@router.put("/campaigns/{campaign_id}", response_model=CampaignResponse)
async def update_campaign(
    request: Request,
    campaign_id: UUID,
    payload: CampaignUpdate,
    principal: Principal = Depends(current_principal),
) -> CampaignResponse:
    correlation_id = _correlation_id(request)
    campaign = await _service(request).update_campaign(principal, campaign_id, payload)
    return CampaignResponse.model_validate(campaign)


@router.get("/campaigns/{campaign_id}/creatives", response_model=list[CreativeResponse])
async def get_campaign_creatives(
    request: Request,
    campaign_id: UUID,
    principal: Principal = Depends(current_principal),
) -> list[CreativeResponse]:
    creatives = await _service(request).get_campaign_creatives(principal, campaign_id)
    return [CreativeResponse.model_validate(c) for c in creatives]


@router.post(
    "/campaigns/{campaign_id}/creatives",
    response_model=CreativeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_creative(
    request: Request,
    campaign_id: UUID,
    payload: CreativeCreate,
    principal: Principal = Depends(current_principal),
) -> CreativeResponse:
    correlation_id = _correlation_id(request)
    creative = await _service(request).create_creative(principal, campaign_id, payload)
    return CreativeResponse.model_validate(creative)


@router.put("/campaigns/{campaign_id}/creatives/{creative_id}", response_model=CreativeResponse)
async def update_creative(
    request: Request,
    campaign_id: UUID,
    creative_id: UUID,
    payload: CreativeUpdate,
    principal: Principal = Depends(current_principal),
) -> CreativeResponse:
    correlation_id = _correlation_id(request)
    creative = await _service(request).update_creative(principal, campaign_id, creative_id, payload)
    return CreativeResponse.model_validate(creative)


@router.delete("/campaigns/{campaign_id}/creatives/{creative_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_creative(
    request: Request,
    campaign_id: UUID,
    creative_id: UUID,
    principal: Principal = Depends(current_principal),
) -> None:
    correlation_id = _correlation_id(request)
    await _service(request).deactivate_creative(principal, campaign_id, creative_id)
