from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from oki.api.errors import ProblemException, generate_correlation_id, parse_correlation_id
from oki.identity.dependencies import current_principal
from oki.identity.schemas import Principal
from oki.analytics.schemas import (
    CampaignMetricsResponse,
    CreatorMetricsResponse,
    OkiConversionEventResponse,
    VideoMetricsResponse,
)
from oki.analytics.service import AnalyticsService

router = APIRouter(prefix="/api", tags=["analytics"])


def _service(request: Request) -> AnalyticsService:
    service = getattr(request.app.state, "analytics_service", None)
    if not isinstance(service, AnalyticsService):
        raise ProblemException(
            status_code=503,
            code="analytics_service_unavailable",
            title="Analytics service unavailable",
            detail="Analytics processing is not available.",
            retryable=True,
        )
    return service


@router.get("/analytics/creators", response_model=list[CreatorMetricsResponse])
async def get_creator_metrics(
    request: Request,
    principal: Principal = Depends(current_principal),
) -> list[CreatorMetricsResponse]:
    """List aggregate metrics grouped by creator."""
    org_id = _resolve_organization(principal)
    rows = await _service(request).get_creator_metrics(principal, org_id)
    return [CreatorMetricsResponse.model_validate(row) for row in rows]


@router.get("/analytics/videos", response_model=list[VideoMetricsResponse])
async def get_video_metrics(
    request: Request,
    principal: Principal = Depends(current_principal),
) -> list[VideoMetricsResponse]:
    """List aggregate metrics grouped by video."""
    org_id = _resolve_organization(principal)
    rows = await _service(request).get_video_metrics(principal, org_id)
    return [VideoMetricsResponse.model_validate(row) for row in rows]


@router.get("/analytics/languages", response_model=list[dict])
async def get_language_metrics(
    request: Request,
    principal: Principal = Depends(current_principal),
) -> list[dict]:
    """List metrics broken down by language."""
    org_id = _resolve_organization(principal)
    return await _service(request).get_language_metrics(principal, org_id)


@router.get("/analytics/campaigns", response_model=list[CampaignMetricsResponse])
async def get_campaign_metrics(
    request: Request,
    principal: Principal = Depends(current_principal),
) -> list[CampaignMetricsResponse]:
    """List aggregate metrics grouped by campaign."""
    org_id = _resolve_organization(principal)
    rows = await _service(request).get_campaign_metrics(principal, org_id)
    return [CampaignMetricsResponse.model_validate(row) for row in rows]


@router.get("/analytics/oki-conversions", response_model=list[OkiConversionEventResponse])
async def get_oki_conversions(
    request: Request,
    principal: Principal = Depends(current_principal),
) -> list[OkiConversionEventResponse]:
    """List Oki conversion events."""
    org_id = _resolve_organization(principal)
    events = await _service(request).get_oki_conversions(principal, org_id)
    return [OkiConversionEventResponse.model_validate(event) for event in events]


def _resolve_organization(principal: Principal) -> UUID:
    """Resolve the primary organization from the principal memberships."""
    if not principal.memberships:
        raise ProblemException(
            status_code=403,
            code="no_organization_membership",
            title="No organization membership",
            detail="The authenticated principal has no organization memberships.",
        )
    return principal.memberships[0].organization_id
