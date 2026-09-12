from uuid import UUID

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status
import jwt

from oki.api.errors import ProblemException, generate_correlation_id, parse_correlation_id
from oki.config import get_settings
from oki.identity.dependencies import current_principal
from oki.identity.schemas import Principal
from oki.reviews.enums import ReviewDecisionType
from oki.reviews.schemas import (
    CommentCreate,
    CommentResponse,
    DecisionRequest,
    ReviewDecisionResponse,
    ReviewPackageDetailResponse,
    ReviewPackageResponse,
    ReviewPackageVersionResponse,
    ReviewSegmentSummary,
)
from oki.reviews.service import ReviewService

router = APIRouter(prefix="/api", tags=["reviews"])


def _service(request: Request) -> ReviewService:
    service = getattr(request.app.state, "reviews_service", None)
    if not isinstance(service, ReviewService):
        raise ProblemException(
            status_code=503,
            code="reviews_service_unavailable",
            title="Reviews service unavailable",
            detail="Review management is not available.",
            retryable=True,
        )
    return service


def _correlation_id(request: Request) -> UUID:
    value = parse_correlation_id(str(getattr(request.state, "correlation_id", "")))
    return UUID(value or generate_correlation_id())


@router.get("/reviews/{job_id}", response_model=ReviewPackageResponse)
async def get_review_package(
    job_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> ReviewPackageResponse:
    details = await _service(request).get_package_by_job(job_id, principal)
    return ReviewPackageResponse.model_validate(details.package)


@router.post("/reviews/{job_id}/approve", response_model=ReviewDecisionResponse)
async def approve_review(
    job_id: UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    payload: DecisionRequest | None = None,
    principal: Principal = Depends(current_principal),
) -> ReviewDecisionResponse:
    data = payload or DecisionRequest()
    decision, render_job_id = await _service(request).approve_job(
        job_id,
        principal,
        reason=data.reason,
        correlation_id=_correlation_id(request),
    )
    if render_job_id:
        render_service = getattr(request.app.state, "render_service", None)
        if render_service is not None:
            background_tasks.add_task(render_service.execute_render_job, render_job_id)
    return ReviewDecisionResponse.model_validate(decision)


@router.post("/reviews/{job_id}/reject", response_model=ReviewDecisionResponse)
async def reject_review(
    job_id: UUID,
    request: Request,
    payload: DecisionRequest | None = None,
    principal: Principal = Depends(current_principal),
) -> ReviewDecisionResponse:
    data = payload or DecisionRequest()
    decision = await _service(request).reject_job(
        job_id,
        principal,
        reason=data.reason,
        correlation_id=_correlation_id(request),
    )
    return ReviewDecisionResponse.model_validate(decision)


@router.post("/reviews/{job_id}/create-package", response_model=ReviewPackageResponse)
async def create_review_package(
    job_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> ReviewPackageResponse:
    package = await _service(request).create_package(
        job_id,
        principal,
        _correlation_id(request),
    )
    return ReviewPackageResponse.model_validate(package)


@router.post("/reviews/{package_id}/comment", response_model=CommentResponse)
async def add_comment(
    package_id: UUID,
    request: Request,
    payload: CommentCreate,
    principal: Principal = Depends(current_principal),
) -> CommentResponse:
    comment = await _service(request).comment(
        package_id,
        text=payload.text,
        principal=principal,
        correlation_id=_correlation_id(request),
        line_reference=payload.line_reference,
    )
    return CommentResponse.model_validate(comment)


@router.get("/reviews/{job_id}/versions", response_model=list[ReviewPackageVersionResponse])
async def list_review_versions(
    job_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> list[ReviewPackageVersionResponse]:
    versions = await _service(request).get_versions_by_job(job_id, principal)
    return [ReviewPackageVersionResponse.model_validate(v) for v in versions]


@router.post("/reviews/{version_id}/invalidate", status_code=status.HTTP_204_NO_CONTENT)
async def invalidate_version(
    version_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> None:
    await _service(request).invalidate_for_change(
        version_id,
        principal,
        _correlation_id(request),
    )


@router.post("/reviews/{job_id}/request-changes", response_model=ReviewDecisionResponse)
async def request_changes(
    job_id: UUID,
    request: Request,
    payload: DecisionRequest | None = None,
    principal: Principal = Depends(current_principal),
) -> ReviewDecisionResponse:
    data = payload or DecisionRequest()
    decision = await _service(request).reject_job(
        job_id,
        principal,
        reason=data.reason,
        correlation_id=_correlation_id(request),
        decision=ReviewDecisionType.CHANGES_REQUESTED,
    )
    return ReviewDecisionResponse.model_validate(decision)

@router.post("/reviews/{job_id}/creator-link")
async def create_creator_link(
    job_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> dict:
    correlation_id = generate_correlation_id()
    package = await _service(request).create_package(
        job_id, principal, correlation_id
    )
    settings = get_settings()
    secret = settings.review_link_secret or "change-me"
    token = jwt.encode(
        {
            "sub": str(principal.user_id),
            "scope": "review",
            "pkg": str(package.id),
            "exp": datetime.now(timezone.utc) + timedelta(days=7),
        },
        secret,
        algorithm="HS256",
    )
    return {"token": token, "expires_in_days": 7}


@router.get("/reviews/{job_id}/detail", response_model=ReviewPackageDetailResponse)
async def get_review_detail(
    job_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> ReviewPackageDetailResponse:
    """Return full review package with segments, versions, and presigned preview URLs."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from oki.config import Settings
    from oki.db.uow import UnitOfWork
    from oki.assets.models import SourceAsset
    from oki.renders.models import RenderJob
    from oki.translations.models import TranslationSegments, Translations
    from oki.reviews.models import ReviewDecisions
    import boto3

    details = await _service(request).get_package_by_job(job_id, principal)
    versions = await _service(request).get_versions_by_job(job_id, principal)

    settings = Settings()
    s3 = boto3.client(
        "s3",
        endpoint_url=str(settings.s3_endpoint_url) if settings.s3_endpoint_url else None,
        aws_access_key_id=settings.s3_access_key or "",
        aws_secret_access_key=settings.s3_secret_key or "",
    )

    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    original_preview_url: str | None = None
    localized_preview_url: str | None = None
    segments_out: list[ReviewSegmentSummary] = []
    latest_decision: str | None = None

    try:
        async with UnitOfWork(session_factory) as uow:
            # Original source presigned URL
            asset = await uow.session.scalar(
                select(SourceAsset)
                .where(SourceAsset.localization_job_id == job_id, SourceAsset.status == "active")
                .limit(1)
            )
            if asset and asset.storage_key:
                try:
                    original_preview_url = s3.generate_presigned_url(
                        "get_object",
                        Params={"Bucket": settings.s3_bucket, "Key": asset.storage_key},
                        ExpiresIn=3600,
                    )
                except Exception:
                    pass

            # Localized output presigned URL (latest completed render)
            render = await uow.session.scalar(
                select(RenderJob)
                .where(RenderJob.job_id == job_id, RenderJob.output_storage_key.isnot(None))
                .order_by(RenderJob.created_at.desc())
                .limit(1)
            )
            if render and render.output_storage_key:
                try:
                    localized_preview_url = s3.generate_presigned_url(
                        "get_object",
                        Params={"Bucket": settings.s3_bucket, "Key": render.output_storage_key},
                        ExpiresIn=3600,
                    )
                except Exception:
                    pass

            # Fall back to AudioMixVersion if no render output
            if not localized_preview_url:
                from oki.audio.models import AudioMixVersion
                mix = await uow.session.scalar(
                    select(AudioMixVersion)
                    .where(AudioMixVersion.job_id == job_id, AudioMixVersion.status == "completed")
                    .order_by(AudioMixVersion.version_number.desc())
                    .limit(1)
                )
                if mix and mix.output_asset_reference:
                    try:
                        localized_preview_url = s3.generate_presigned_url(
                            "get_object",
                            Params={"Bucket": settings.s3_bucket, "Key": mix.output_asset_reference},
                            ExpiresIn=3600,
                        )
                    except Exception:
                        pass

            # Translation segments
            translation = await uow.session.scalar(
                select(Translations).where(Translations.job_id == job_id).limit(1)
            )
            if translation:
                segs = list(await uow.session.scalars(
                    select(TranslationSegments)
                    .where(TranslationSegments.translation_id == translation.id)
                    .order_by(TranslationSegments.sequence_number)
                ))
                for s in segs:
                    segments_out.append(ReviewSegmentSummary(
                        id=s.id,
                        start_time=float(s.start_time),
                        end_time=float(s.end_time),
                        source_text=s.source_text or "",
                        translated_text=s.translated_text,
                        back_translation=s.back_translation,
                        status=s.status.value if hasattr(s.status, "value") else str(s.status),
                    ))

            # Latest decision on the package
            if details.version:
                dec = await uow.session.scalar(
                    select(ReviewDecisions)
                    .where(ReviewDecisions.package_version_id == details.version.id)
                    .order_by(ReviewDecisions.decided_at.desc())
                    .limit(1)
                )
                if dec:
                    latest_decision = dec.decision.value if hasattr(dec.decision, "value") else str(dec.decision)
    finally:
        await engine.dispose()

    pkg_data = ReviewPackageDetailResponse.model_validate(details.package)
    pkg_data.original_preview_url = original_preview_url
    pkg_data.localized_preview_url = localized_preview_url
    pkg_data.segments = segments_out
    pkg_data.versions = [ReviewPackageVersionResponse.model_validate(v) for v in versions]
    pkg_data.latest_decision = latest_decision
    return pkg_data


@router.get("/reviews/creator/{token}")
async def get_creator_review(token: str) -> dict:
    settings = get_settings()
    secret = settings.review_link_secret or "change-me"
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise ProblemException(
            status_code=401,
            code="invalid_token",
            title="Invalid token",
            detail="The review link is invalid or expired.",
        )
    return {
        "package_id": payload.get("pkg"),
        "user_id": payload.get("sub"),
        "scope": payload.get("scope"),
    }
