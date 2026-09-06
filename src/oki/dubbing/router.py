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
    "/jobs/{job_id}/dub/cancel",
    response_model=DubCancelResponse,
)
async def cancel_dubbing(
    job_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> DubCancelResponse:
    return await _service(request).cancel(principal, job_id)


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
