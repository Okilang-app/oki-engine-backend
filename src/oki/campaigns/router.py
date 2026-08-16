from uuid import UUID

from fastapi import APIRouter, Depends, Request

from oki.api.errors import generate_correlation_id, parse_correlation_id
from oki.identity.dependencies import current_principal
from oki.identity.schemas import Principal
from oki.campaigns.schemas import CampaignResponse, CreativeResponse
from oki.campaigns.service import CampaignService

router = APIRouter(prefix="/api", tags=["campaigns"])


def _service(request: Request) -> CampaignService:
    service = getattr(request.app.state, "campaign_service", None)
    if service is None:
        raise RuntimeError("CampaignService not available")
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


@router.get("/campaigns/{campaign_id}/creatives", response_model=list[CreativeResponse])
async def get_campaign_creatives(
    request: Request,
    campaign_id: UUID,
    principal: Principal = Depends(current_principal),
) -> list[CreativeResponse]:
    creatives = await _service(request).get_campaign_creatives(principal, campaign_id)
    return [CreativeResponse.model_validate(c) for c in creatives]
