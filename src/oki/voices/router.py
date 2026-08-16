from uuid import UUID

from fastapi import APIRouter, Depends, Request

from oki.api.errors import generate_correlation_id, parse_correlation_id
from oki.identity.dependencies import current_principal
from oki.identity.schemas import Principal
from oki.voices.schemas import VoiceProfileResponse
from oki.voices.service import VoiceService

router = APIRouter(prefix="/api", tags=["voices"])


def _service(request: Request) -> VoiceService:
    service = getattr(request.app.state, "voice_service", None)
    if service is None:
        raise RuntimeError("VoiceService not available")
    return service


def _correlation_id(request: Request) -> UUID:
    value = parse_correlation_id(str(getattr(request.state, "correlation_id", "")))
    return UUID(value or generate_correlation_id())


@router.get("/voices", response_model=list[VoiceProfileResponse])
async def list_voices(
    request: Request,
    principal: Principal = Depends(current_principal),
) -> list[VoiceProfileResponse]:
    profiles = await _service(request).list_profiles(principal)
    return [VoiceProfileResponse.model_validate(p) for p in profiles]


@router.get("/voices/{profile_id}", response_model=VoiceProfileResponse)
async def get_voice(
    request: Request,
    profile_id: UUID,
    principal: Principal = Depends(current_principal),
) -> VoiceProfileResponse:
    profile = await _service(request).get_profile(principal, profile_id)
    return VoiceProfileResponse.model_validate(profile)
