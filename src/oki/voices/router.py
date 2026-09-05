from uuid import UUID

from fastapi import APIRouter, Depends, Request

from oki.api.errors import generate_correlation_id, parse_correlation_id
from oki.identity.dependencies import current_principal
from oki.identity.schemas import Principal
from oki.voices.schemas import (
    ElevenLabsVoiceResponse,
    VoiceProfileCreate,
    VoiceProfileResponse,
    VoiceProfileUpdate,
)
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


@router.post("/voices", response_model=VoiceProfileResponse)
async def create_voice(
    request: Request,
    payload: VoiceProfileCreate,
    principal: Principal = Depends(current_principal),
) -> VoiceProfileResponse:
    profile = await _service(request).create_profile(principal, payload)
    return VoiceProfileResponse.model_validate(profile)


@router.put("/voices/{profile_id}", response_model=VoiceProfileResponse)
async def update_voice(
    request: Request,
    profile_id: UUID,
    payload: VoiceProfileUpdate,
    principal: Principal = Depends(current_principal),
) -> VoiceProfileResponse:
    profile = await _service(request).update_profile(principal, profile_id, payload)
    return VoiceProfileResponse.model_validate(profile)


@router.get("/voices/elevenlabs", response_model=list[ElevenLabsVoiceResponse])
async def list_elevenlabs_voices(
    request: Request,
    principal: Principal = Depends(current_principal),
) -> list[ElevenLabsVoiceResponse]:
    from oki.config import Settings
    from oki.providers.elevenlabs import ElevenLabsClient

    settings = Settings()
    if not settings.elevenlabs_api_key:
        return []

    client = ElevenLabsClient(settings)
    voices = await client.list_voices()
    return [
        ElevenLabsVoiceResponse(voice_id=v.get("voice_id", ""), name=v.get("name", ""))
        for v in voices
    ]
