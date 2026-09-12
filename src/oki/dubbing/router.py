from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from oki.identity.dependencies import current_principal
from oki.identity.schemas import Principal
from oki.dubbing.schemas import (
    DubCancelResponse,
    DubPlaybackResponse,
    DubRegenerateRequest,
    DubReviewRequest,
    DubSegmentListResponse,
    DubSegmentResponse,
    DubbingStartRequest,
    DubbingStartResponse,
)
from oki.dubbing.service import DubbingService

router = APIRouter(prefix="/api", tags=["dubbing"])


def _service(request: Request) -> DubbingService:
    service = getattr(request.app.state, "dubbing_service", None)
    if service is None:
        raise RuntimeError("DubbingService not available")
    return service


@router.post(
    "/jobs/{job_id}/dub",
    response_model=DubbingStartResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_dubbing(
    job_id: UUID,
    request: Request,
    payload: DubbingStartRequest | None = None,
    principal: Principal = Depends(current_principal),
) -> DubbingStartResponse:
    body = payload or DubbingStartRequest()
    result = await _service(request).start(
        principal,
        job_id,
        voice_profile_id=body.voice_profile_id,
        target_language=body.target_language,
    )
    return result


@router.get(
    "/jobs/{job_id}/dub-segments",
    response_model=DubSegmentListResponse,
)
async def list_dub_segments(
    job_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> DubSegmentListResponse:
    segments = await _service(request).list_segments(principal, job_id)
    return DubSegmentListResponse(
        job_id=job_id,
        segments=[DubSegmentResponse.model_validate(s) for s in segments],
    )


@router.get(
    "/dub-segments/{segment_id}",
    response_model=DubSegmentResponse,
)
async def get_dub_segment(
    segment_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> DubSegmentResponse:
    segment = await _service(request).get_segment(principal, segment_id)
    return DubSegmentResponse.model_validate(segment)


@router.post(
    "/dub-segments/{segment_id}/regenerate",
    response_model=DubSegmentResponse,
)
async def regenerate_dub_segment(
    segment_id: UUID,
    request: Request,
    payload: DubRegenerateRequest | None = None,
    principal: Principal = Depends(current_principal),
) -> DubSegmentResponse:
    body = payload or DubRegenerateRequest()
    segment = await _service(request).regenerate_segment(
        principal,
        segment_id,
        voice_profile_id=body.voice_profile_id,
    )
    return DubSegmentResponse.model_validate(segment)


@router.post(
    "/dub-segments/{segment_id}/review",
    response_model=DubSegmentResponse,
)
async def review_dub_segment(
    segment_id: UUID,
    request: Request,
    payload: DubReviewRequest,
    principal: Principal = Depends(current_principal),
) -> DubSegmentResponse:
    segment = await _service(request).submit_review(
        principal,
        segment_id,
        approved=payload.approved,
        reason=payload.reason,
    )
    return DubSegmentResponse.model_validate(segment)


@router.post(
    "/jobs/{job_id}/dub/resume",
    status_code=status.HTTP_202_ACCEPTED,
)
async def resume_dubbing(
    job_id: UUID,
    request: Request,
    background_tasks: __import__("fastapi").BackgroundTasks,
    principal: Principal = Depends(current_principal),
) -> dict:
    """Re-run TTS only for pending segments. Optionally stamps a new voice_profile_id first."""
    from oki.dubbing.tasks import run_dubbing_task
    from oki.dubbing.models import DubSegment
    from oki.jobs.models import LocalizationJob
    from sqlalchemy import update as sql_update
    import json as _json

    voice_profile_id: UUID | None = None
    try:
        raw = await request.body()
        data = _json.loads(raw) if raw else {}
        if data.get("voice_profile_id"):
            voice_profile_id = UUID(data["voice_profile_id"])
    except Exception:
        pass

    svc = _service(request)
    async with svc._uow_factory() as uow:
        job = await uow.session.get(LocalizationJob, job_id)
        if job is None:
            from oki.api.errors import ProblemException
            raise ProblemException(status_code=404, code="job_not_found", title="Job not found", detail="")

        # Stamp voice_profile_id on all pending segments if provided
        if voice_profile_id:
            await uow.session.execute(
                sql_update(DubSegment)
                .where(DubSegment.job_id == job_id, DubSegment.status == "pending")
                .values(voice_profile_id=voice_profile_id)
            )
            await uow.session.flush()

    background_tasks.add_task(run_dubbing_task, job_id=job_id, resume_only=True)
    return {"job_id": str(job_id), "status": "resuming"}


@router.post(
    "/jobs/{job_id}/mix",
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_audio_mix(
    job_id: UUID,
    request: Request,
    background_tasks: __import__("fastapi").BackgroundTasks,
    principal: Principal = Depends(current_principal),
) -> dict:
    """Re-run the audio mix + QA pipeline for a job that already has TTS segments."""
    from oki.audio.tasks import run_audio_mix_task
    from oki.audio.models import AudioMixVersion
    import json as _json

    mix_overrides: dict | None = None
    try:
        raw = await request.body()
        data = _json.loads(raw) if raw else {}
        if data.get("overrides"):
            mix_overrides = data["overrides"]
    except Exception:
        pass

    svc = _service(request)
    async with svc._uow_factory() as uow:
        from oki.jobs.models import LocalizationJob
        job = await uow.session.get(LocalizationJob, job_id)
        if job is None:
            from oki.api.errors import ProblemException
            raise ProblemException(status_code=404, code="job_not_found", title="Job not found", detail="")

        from sqlalchemy import select
        prev = await uow.session.scalar(
            select(AudioMixVersion)
            .where(AudioMixVersion.job_id == job_id)
            .order_by(AudioMixVersion.version_number.desc())
            .limit(1)
        )
        version_number = (prev.version_number + 1) if prev else 1
        mix = AudioMixVersion(
            organization_id=job.organization_id,
            job_id=job_id,
            asset_id=job_id,
            version_number=version_number,
            status="pending",
            mix_plan={"overrides": mix_overrides} if mix_overrides else {},
            stems={},
        )
        uow.session.add(mix)
        await uow.session.flush()
        mix_id = mix.id

    background_tasks.add_task(run_audio_mix_task, job_id=job_id, mix_version_id=mix_id, mix_overrides=mix_overrides)
    return {"job_id": str(job_id), "mix_version_id": str(mix_id), "status": "queued"}


@router.get(
    "/jobs/{job_id}/mix/playback-url",
)
async def get_mix_playback_url(
    job_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> dict:
    """Return a presigned URL for the latest completed mix output."""
    from oki.audio.models import AudioMixVersion
    from sqlalchemy import select
    import boto3
    from oki.config import Settings

    svc = _service(request)
    async with svc._uow_factory() as uow:
        mix = await uow.session.scalar(
            select(AudioMixVersion)
            .where(AudioMixVersion.job_id == job_id, AudioMixVersion.status == "completed")
            .order_by(AudioMixVersion.version_number.desc())
            .limit(1)
        )
        if mix is None or not mix.output_asset_reference:
            from oki.api.errors import ProblemException
            raise ProblemException(status_code=404, code="no_mix", title="No completed mix found", detail="")

        output_key = mix.output_asset_reference

    settings = Settings()
    from botocore.config import Config as BotoConfig
    s3 = boto3.client(
        "s3",
        endpoint_url=str(settings.s3_public_url or settings.s3_endpoint_url),
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=BotoConfig(signature_version="s3v4"),
    )
    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket, "Key": output_key},
        ExpiresIn=3600,
    )
    return {"url": url, "output_key": output_key}


@router.get(
    "/jobs/{job_id}/mix",
)
async def get_audio_mix(
    job_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> dict:
    """Return latest AudioMixVersion + QA result for a job."""
    from oki.audio.models import AudioMixVersion, AudioQaResult
    from sqlalchemy import select

    svc = _service(request)
    async with svc._uow_factory() as uow:
        mix = await uow.session.scalar(
            select(AudioMixVersion)
            .where(AudioMixVersion.job_id == job_id)
            .order_by(AudioMixVersion.version_number.desc())
            .limit(1)
        )
        if mix is None:
            return {"status": "not_started"}

        qa = await uow.session.scalar(
            select(AudioQaResult)
            .where(AudioQaResult.audio_mix_version_id == mix.id)
            .order_by(AudioQaResult.created_at.desc())
            .limit(1)
        )

    return {
        "mix_version_id": str(mix.id),
        "version_number": mix.version_number,
        "status": mix.status,
        "output_key": mix.output_asset_reference,
        "mix_plan": mix.mix_plan,
        "qa": {
            "passed": qa.passed,
            "clipping": qa.clipping_detected,
            "silence": qa.silence_detected,
            "loudness_lufs": (qa.loudness_lufs / 1000.0) if qa.loudness_lufs else None,
            "issues": qa.issues,
        } if qa else None,
    }


@router.post(
    "/jobs/{job_id}/dub/complete",
    status_code=status.HTTP_200_OK,
)
async def complete_dubbing(
    job_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> dict:
    """Advance job from DUBBING_RUNNING → AUDIO_REVIEW once segments are approved."""
    from oki.jobs.models import LocalizationJob
    from oki.jobs.enums import WorkflowState, WorkflowEvent
    from oki.jobs.state_machine import WorkflowStateMachine
    from oki.dubbing.models import DubSegment
    from sqlalchemy import select

    svc = _service(request)
    async with svc._uow_factory() as uow:
        job = await uow.session.get(LocalizationJob, job_id)
        if job is None:
            from oki.api.errors import ProblemException
            raise ProblemException(status_code=404, code="job_not_found", title="Job not found", detail="")

        if job.state != WorkflowState.DUBBING_RUNNING:
            from oki.api.errors import ProblemException
            raise ProblemException(
                status_code=409,
                code="invalid_workflow_state",
                title="Job is not in DUBBING_RUNNING state",
                detail=f"Current state: {job.state}",
            )

        pending = await uow.session.scalar(
            select(DubSegment)
            .where(DubSegment.job_id == job_id, DubSegment.status != "completed")
            .limit(1)
        )
        if pending:
            from oki.api.errors import ProblemException
            raise ProblemException(
                status_code=409,
                code="segments_not_complete",
                title="Not all segments are completed",
                detail="Generate and approve all segments before submitting for audio review.",
            )

        WorkflowStateMachine().transition(job, WorkflowEvent.REQUEST_AUDIO_REVIEW)
        await uow.session.flush()

    return {"job_id": str(job_id), "state": "AUDIO_REVIEW"}


@router.post(
    "/jobs/{job_id}/dub/cancel",
    response_model=DubCancelResponse,
)
async def cancel_dubbing(
    job_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> DubCancelResponse:
    return await _service(request).cancel(principal, job_id)


@router.delete(
    "/jobs/{job_id}/dub",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def reset_dubbing(
    job_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> None:
    """Delete all dub segments for a job and roll back to TRANSLATION_REVIEW."""
    from sqlalchemy import delete as sql_delete
    from oki.dubbing.models import DubSegment, DubAttempt
    from oki.jobs.models import LocalizationJob
    from oki.jobs.enums import WorkflowState

    svc = _service(request)
    async with svc._uow_factory() as uow:
        job = await uow.session.get(LocalizationJob, job_id)
        if job is None:
            from oki.api.errors import ProblemException
            raise ProblemException(status_code=404, code="job_not_found", title="Job not found", detail="")

        segment_ids = list(await uow.session.scalars(
            __import__("sqlalchemy").select(DubSegment.id).where(DubSegment.job_id == job_id)
        ))
        if segment_ids:
            await uow.session.execute(
                sql_delete(DubAttempt).where(DubAttempt.dub_segment_id.in_(segment_ids))
            )
            await uow.session.execute(
                sql_delete(DubSegment).where(DubSegment.job_id == job_id)
            )

        job.state = WorkflowState.TRANSLATION_REVIEW
        await uow.session.flush()


@router.get(
    "/dub-segments/{segment_id}/playback-url",
    response_model=DubPlaybackResponse,
)
async def dub_segment_playback(
    segment_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> DubPlaybackResponse:
    url = await _service(request).get_playback_url(principal, segment_id)
    return DubPlaybackResponse(
        segment_id=segment_id,
        playback_url=url,
    )
