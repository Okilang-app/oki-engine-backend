from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from oki.api.errors import ProblemException
from oki.identity.dependencies import current_principal
from oki.identity.schemas import Principal
from oki.translations.schemas import (
    TranslationResponse,
    TranslationSegmentResponse,
    TranslationSegmentReviseRequest,
    TranslationStartRequest,
)
from oki.translations.service import TranslationService

router = APIRouter(prefix="/api", tags=["translations"])


def _service(request: Request) -> TranslationService:
    service = getattr(request.app.state, "translation_service", None)
    if not isinstance(service, TranslationService):
        raise ProblemException(
            status_code=503,
            code="translation_service_unavailable",
            title="Translation service unavailable",
            detail="Translation management is not available.",
            retryable=True,
        )
    return service


@router.post("/jobs/translate", response_model=TranslationResponse, status_code=status.HTTP_201_CREATED)
async def start_translation(
    payload: TranslationStartRequest,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> TranslationResponse:
    translation = await _service(request).start(
        principal,
        job_id=payload.job_id,
        target_language=payload.target_language,
        source_language=payload.source_language,
    )
    return TranslationResponse.model_validate(translation)


@router.get("/jobs/{job_id}/translations/{language}", response_model=TranslationResponse)
async def get_translation(
    job_id: UUID,
    language: str,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> TranslationResponse:
    translation = await _service(request).get_translation(principal, job_id, language)
    return TranslationResponse.model_validate(translation)


@router.get("/translations/{translation_id}/segments", response_model=list[TranslationSegmentResponse])
async def list_translation_segments(
    translation_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> list[TranslationSegmentResponse]:
    segments = await _service(request).list_segments(principal, translation_id)
    return [TranslationSegmentResponse.model_validate(s) for s in segments]


@router.post("/translations/{translation_id}/approve", response_model=TranslationResponse)
async def approve_translation(
    translation_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> TranslationResponse:
    """Approve a translation — marks it reviewed and advances the job to TRANSLATION_REVIEW."""
    translation = await _service(request).submit_review(principal, translation_id)
    return TranslationResponse.model_validate(translation)


@router.post(
    "/translations/{translation_id}/segments/{segment_id}/revise",
    response_model=TranslationSegmentResponse,
)
async def revise_translation_segment(
    translation_id: UUID,
    segment_id: UUID,
    payload: TranslationSegmentReviseRequest,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> TranslationSegmentResponse:
    segment = await _service(request).revise_segment(
        principal,
        segment_id=segment_id,
        text=payload.new_text,
        reason=payload.reason,
    )
    return TranslationSegmentResponse.model_validate(segment)
