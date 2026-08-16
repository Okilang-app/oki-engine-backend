from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from oki.api.errors import ProblemException, generate_correlation_id, parse_correlation_id
from oki.identity.dependencies import current_principal
from oki.identity.schemas import Principal
from oki.youtube.oauth import YoutubeOAuthService
from oki.youtube.schemas import ChannelResponse, OAuthCallbackRequest

router = APIRouter(prefix="/api", tags=["youtube"])


def _service(request: Request) -> YoutubeOAuthService:
    service = getattr(request.app.state, "youtube_oauth_service", None)
    if not isinstance(service, YoutubeOAuthService):
        raise ProblemException(
            status_code=503,
            code="youtube_service_unavailable",
            title="YouTube service unavailable",
            detail="YouTube OAuth integration is not available.",
            retryable=True,
        )
    return service


@router.post("/youtube/connect", status_code=status.HTTP_200_OK)
async def youtube_connect(
    request: Request,
    callback_url: str,
    principal: Principal = Depends(current_principal),
) -> dict[str, str]:
    return await _service(request).start(callback_url, principal)


@router.post("/youtube/callback", response_model=ChannelResponse, status_code=status.HTTP_200_OK)
async def youtube_callback(
    request: Request,
    payload: OAuthCallbackRequest,
    principal: Principal = Depends(current_principal),
) -> ChannelResponse:
    channel = await _service(request).callback(
        code=payload.code,
        state=payload.state,
        principal=principal,
    )
    return ChannelResponse.model_validate(channel)


@router.post("/youtube/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def youtube_revoke(
    request: Request,
    connection_id: UUID,
    principal: Principal = Depends(current_principal),
) -> None:
    await _service(request).revoke(connection_id, principal)
