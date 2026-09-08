from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile

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


@router.post("/jobs/{job_id}/clone-voice-from-video", response_model=VoiceProfileResponse)
async def clone_voice_from_video(
    job_id: UUID,
    request: Request,
    name: str = Form(...),
    language_code: str = Form(default="es"),
    principal: Principal = Depends(current_principal),
) -> VoiceProfileResponse:
    """Extract audio from the job's source video and create an ElevenLabs voice clone."""
    import asyncio
    import tempfile
    from pathlib import Path

    import boto3

    from oki.assets.models import SourceAsset
    from oki.config import Settings
    from oki.jobs.models import LocalizationJob
    from oki.providers.elevenlabs import ElevenLabsClient
    from oki.voices.schemas import VoiceProfileCreate
    from sqlalchemy import select

    settings = Settings()
    voice_svc = _service(request)

    async with voice_svc._uow_factory() as uow:
        job = await uow.session.get(LocalizationJob, job_id)
        if job is None:
            from oki.api.errors import ProblemException
            raise ProblemException(status_code=404, code="job_not_found", title="Job not found", detail="")

        asset = await uow.session.scalar(
            select(SourceAsset).where(SourceAsset.localization_job_id == job_id)
        )
        if asset is None:
            asset = await uow.session.scalar(
                select(SourceAsset)
                .where(SourceAsset.project_id == job.project_id)
                .order_by(SourceAsset.created_at.desc())
            )
        if asset is None or not asset.storage_key:
            from oki.api.errors import ProblemException
            raise ProblemException(status_code=404, code="no_asset", title="No source asset", detail="Upload a video first.")

    s3 = boto3.client(
        "s3",
        endpoint_url=str(settings.s3_endpoint_url) if settings.s3_endpoint_url else None,
        aws_access_key_id=settings.s3_access_key or "",
        aws_secret_access_key=settings.s3_secret_key or "",
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        video_path = tmp / "source.mp4"
        audio_path = tmp / "voice_sample.mp3"

        resp = s3.get_object(Bucket=settings.s3_bucket, Key=asset.storage_key)
        video_path.write_bytes(resp["Body"].read())

        # Extract clean mono audio, 16kHz, suitable for voice cloning
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: __import__("subprocess").run(
                [
                    settings.ffmpeg_path, "-y", "-i", str(video_path),
                    "-vn", "-ac", "1", "-ar", "16000",
                    "-b:a", "128k", str(audio_path),
                ],
                check=True, capture_output=True,
            ),
        )

        audio_bytes = audio_path.read_bytes()

    client = ElevenLabsClient(settings)
    result = await client.clone_voice(
        name=name,
        audio_samples=[("voice_sample.mp3", audio_bytes, "audio/mpeg")],
    )
    voice_id = result.get("voice_id", "")

    payload = VoiceProfileCreate(
        name=name,
        mode="creator_approved_clone",
        language_code=language_code,
        provider_key="elevenlabs",
        provider_voice_id=voice_id,
    )
    profile = await _service(request).create_profile(principal, payload)
    return VoiceProfileResponse.model_validate(profile)


@router.post("/voices/clone", response_model=VoiceProfileResponse)
async def clone_voice(
    request: Request,
    name: str = Form(...),
    language_code: str = Form(default="es"),
    description: str = Form(default=""),
    files: list[UploadFile] = File(...),
    principal: Principal = Depends(current_principal),
) -> VoiceProfileResponse:
    """Create an ElevenLabs Instant Voice Clone and save it as a VoiceProfile."""
    from oki.config import Settings
    from oki.providers.elevenlabs import ElevenLabsClient

    settings = Settings()
    client = ElevenLabsClient(settings)

    samples = []
    for upload in files:
        data = await upload.read()
        samples.append((upload.filename or "sample.mp3", data, upload.content_type or "audio/mpeg"))

    result = await client.clone_voice(name=name, audio_samples=samples, description=description)
    voice_id = result.get("voice_id", "")

    from oki.voices.schemas import VoiceProfileCreate
    payload = VoiceProfileCreate(
        name=name,
        mode="creator_approved_clone",
        language_code=language_code,
        provider_key="elevenlabs",
        provider_voice_id=voice_id,
    )
    profile = await _service(request).create_profile(principal, payload)
    return VoiceProfileResponse.model_validate(profile)


# Must be defined BEFORE /voices/{profile_id} to avoid "elevenlabs" being parsed as a UUID
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
