"""Asset API router."""

from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import FileResponse, Response, StreamingResponse

from oki.api.errors import ProblemException, generate_correlation_id, parse_correlation_id
from pydantic import BaseModel, Field

from oki.assets.schemas import (
    AssetCreate,
    AssetResponse,
    CompleteUploadRequest,
    FinalizeUploadRequest,
    SimpleUploadRequest,
    SimpleUploadResponse,
    UploadUrlRequest,
    UploadUrlResponse,
    ValidationResultResponse,
)
from oki.assets.service import AssetDetails, AssetService
from oki.identity.dependencies import current_principal
from oki.identity.schemas import Principal


class ImportUrlRequest(BaseModel):
    url: str = Field(..., max_length=2048)
    title: str | None = Field(default=None, max_length=255)

router = APIRouter(prefix="/api", tags=["assets"])


def _service(request: Request) -> AssetService:
    service = getattr(request.app.state, "asset_service", None)
    if not isinstance(service, AssetService):
        raise ProblemException(
            status_code=503,
            code="asset_service_unavailable",
            title="Asset service unavailable",
            detail="Asset management is not available.",
            retryable=True,
        )
    return service


def _correlation_id(request: Request) -> UUID:
    value = parse_correlation_id(str(getattr(request.state, "correlation_id", "")))
    return UUID(value or generate_correlation_id())


def _response(details: AssetDetails) -> AssetResponse:
    asset = details.asset
    return AssetResponse(
        id=asset.id,
        organization_id=asset.organization_id,
        creator_id=asset.creator_id,
        rights_agreement_id=asset.rights_agreement_id,
        project_id=asset.project_id,
        localization_job_id=asset.localization_job_id,
        title=asset.title,
        description=asset.description,
        status=asset.status,
        storage_key=asset.storage_key,
        storage_bucket=asset.storage_bucket,
        sha256=asset.sha256,
        size_bytes=asset.size_bytes,
        duration_seconds=asset.duration_seconds,
        container_format=asset.container_format,
        created_by_user_id=asset.created_by_user_id,
        created_at=asset.created_at,
        updated_at=asset.updated_at,
        version=asset.version,
    )


@router.post("/assets", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
async def create_asset(
    payload: AssetCreate,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> AssetResponse:
    service = _service(request)
    asset = await service.create_asset(
        principal,
        payload,
        correlation_id=_correlation_id(request),
    )
    return _response(AssetDetails(asset=asset, upload=None))


@router.post("/assets/upload-url", response_model=UploadUrlResponse)
async def get_upload_url(
    payload: UploadUrlRequest,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> UploadUrlResponse:
    return await _service(request).create_upload(
        principal,
        payload,
        correlation_id=_correlation_id(request),
    )


@router.post("/assets/complete-upload", response_model=AssetResponse)
async def complete_upload(
    payload: CompleteUploadRequest,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> AssetResponse:
    details = await _service(request).complete_upload(
        principal,
        payload,
        correlation_id=_correlation_id(request),
    )
    return _response(details)


@router.post("/assets/simple-upload", response_model=SimpleUploadResponse)
async def simple_upload(
    payload: SimpleUploadRequest,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> SimpleUploadResponse:
    return await _service(request).create_simple_upload(principal, payload)


@router.post("/assets/import-url", response_model=AssetResponse)
async def import_from_url(
    payload: ImportUrlRequest,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> AssetResponse:
    """Download a video from a YouTube URL via yt-dlp and create an asset."""
    from oki.assets.ytdlp import YtDlpImporter
    from oki.assets.enums import AssetStatus
    from oki.assets.models import SourceAsset
    from oki.creators.models import Creator
    from oki.config import Settings
    from sqlalchemy import select

    service = _service(request)
    settings = Settings()

    async with service._uow_factory() as uow:
        if not principal.memberships:
            raise ProblemException(
                status_code=403,
                code="no_membership",
                title="No organization membership",
                detail="You must belong to an organization to import videos.",
            )
        organization_id = principal.memberships[0].organization_id

        creator = await uow.session.scalar(
            select(Creator)
            .where(Creator.organization_id == organization_id)
            .limit(1)
        )
        creator_id = creator.id if creator else UUID(int=0)

        asset = SourceAsset(
            organization_id=organization_id,
            creator_id=creator_id,
            title=payload.title or "Importing...",
            status=AssetStatus.DRAFT,
            created_by_user_id=principal.user_id,
        )
        uow.session.add(asset)
        await uow.session.flush()
        asset_id = asset.id

    importer = YtDlpImporter(settings)
    try:
        result = await importer.download_and_upload(payload.url, asset_id, organization_id)
    except Exception as e:
        raise ProblemException(
            status_code=400,
            code="import_failed",
            title="Video import failed",
            detail=str(e),
        )

    async with service._uow_factory() as uow:
        asset = await uow.session.get(SourceAsset, asset_id)
        asset.storage_key = result["storage_key"]
        asset.sha256 = result["sha256"]
        asset.size_bytes = result["file_size"]
        asset.duration_seconds = result.get("duration")
        asset.status = AssetStatus.ACTIVE
        if not payload.title:
            asset.title = result.get("title", "Imported video")
        await uow.session.flush()
        return _response(AssetDetails(asset=asset, upload=None))


@router.post("/assets/{asset_id}/finalize", response_model=AssetResponse)
async def finalize_asset_upload(
    asset_id: UUID,
    payload: FinalizeUploadRequest,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> AssetResponse:
    details = await _service(request).finalize_upload(principal, asset_id, payload)
    return _response(details)


@router.post("/assets/{asset_id}/validate-rights")
async def validate_asset_rights(
    asset_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> dict:
    return await _service(request).validate_rights(
        principal,
        asset_id,
        correlation_id=_correlation_id(request),
    )


@router.get("/assets/{asset_id}/playback-url")
async def get_playback_url(
    asset_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> dict:
    url = await _service(request).get_playback_url(principal, asset_id)
    return {"playback_url": url, "asset_id": str(asset_id)}


@router.get("/assets", response_model=list[AssetResponse])
async def list_assets(
    request: Request,
    principal: Principal = Depends(current_principal),
) -> list[AssetResponse]:
    assets = await _service(request).list_assets(principal)
    return [AssetResponse.model_validate(a) for a in assets]


@router.get("/assets/{asset_id}", response_model=AssetResponse)
async def get_asset(
    asset_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> AssetResponse:
    return _response(await _service(request).get_details(principal, asset_id))


def _parse_range(
    range_header: str | None,
    total_size: int,
) -> tuple[int, int] | str | None:
    """Parse a single-range HTTP Range header against a known object size.

    Returns the inclusive ``(start, end)`` pair, the string ``"unsatisfiable"``
    when the range falls outside the object (RFC 9110 wants a 416 there), or
    ``None`` when the caller did not ask for a range.
    """
    if not range_header or not total_size:
        return None
    unit, _, spec = range_header.partition("=")
    if unit.strip().lower() != "bytes" or "," in spec:
        return None
    start_str, sep, end_str = spec.strip().partition("-")
    if not sep:
        return None
    try:
        if not start_str:
            # Suffix form ("bytes=-500") means the trailing N bytes.
            suffix = int(end_str)
            if suffix <= 0:
                return "unsatisfiable"
            start = max(0, total_size - suffix)
            end = total_size - 1
        else:
            start = int(start_str)
            end = int(end_str) if end_str else total_size - 1
    except ValueError:
        return None
    if start >= total_size or start < 0:
        return "unsatisfiable"
    # Clamp rather than reject: browsers routinely ask past the end.
    end = min(end, total_size - 1)
    if end < start:
        return "unsatisfiable"
    return start, end


@router.get("/assets/{asset_id}/stream")
async def stream_asset(
    asset_id: UUID,
    request: Request,
):
    """Stream video asset. No auth required — asset UUID is unguessable."""
    from pathlib import Path
    from oki.storage.s3 import S3ObjectStore

    # Look up asset by ID directly (no auth — UUIDv7 is the secret)
    from oki.assets.models import SourceAsset
    from sqlalchemy import select

    # Need a session to query — peek into the service's internals
    service = _service(request)
    async with service._uow_factory() as uow:
        asset = await uow.session.scalar(
            select(SourceAsset).where(SourceAsset.id == asset_id)
        )
    if asset is None:
        raise ProblemException(
            status_code=404, code="asset_not_found",
            title="Asset not found", detail="The requested asset does not exist.", retryable=False,
        )
    if not asset.storage_key:
        raise ProblemException(
            status_code=404, code="asset_not_uploaded",
            title="Asset not uploaded", detail="This asset has no video file yet.", retryable=False,
        )

    # Serve local files directly (uploads stored on disk, not S3)
    local_path = Path(asset.storage_key)
    if not local_path.is_absolute():
        local_path = Path.cwd() / local_path
    if local_path.exists():
        return FileResponse(
            local_path,
            media_type="video/mp4",
            filename=local_path.name,
            content_disposition_type="inline",
        )

    # Fallback: proxy from S3/SeaweedFS
    store: S3ObjectStore = getattr(request.app.state, "s3_store", None)
    if store is None:
        raise ProblemException(
            status_code=503, code="storage_unavailable",
            title="Storage unavailable", detail="S3 store not initialized.", retryable=True,
        )

    head = await store.head_object(asset.storage_key)
    content_type = head.get("content_type") or "video/mp4"
    total_size = head.get("content_length") or 0

    byte_range = _parse_range(request.headers.get("range"), total_size)
    if byte_range == "unsatisfiable":
        return Response(
            status_code=416,
            headers={"Content-Range": f"bytes */{total_size}", "Accept-Ranges": "bytes"},
        )
    if byte_range is not None:
        start, end = byte_range
        return StreamingResponse(
            store.iter_object(asset.storage_key, range_bytes=(start, end)),
            status_code=206,
            media_type=content_type,
            headers={
                "Content-Range": f"bytes {start}-{end}/{total_size}",
                "Content-Length": str(end - start + 1),
                "Accept-Ranges": "bytes",
            },
        )

    return StreamingResponse(
        store.iter_object(asset.storage_key),
        media_type=content_type,
        headers={"Accept-Ranges": "bytes", "Content-Length": str(total_size)},
    )


@router.head("/assets/{asset_id}/stream")
async def head_stream_asset(
    asset_id: UUID,
    request: Request,
):
    """Return headers for video stream (used by browsers for range negotiation)."""
    from pathlib import Path
    from oki.assets.models import SourceAsset
    from sqlalchemy import select

    service = _service(request)
    async with service._uow_factory() as uow:
        asset = await uow.session.scalar(
            select(SourceAsset).where(SourceAsset.id == asset_id)
        )
    if asset is None or not asset.storage_key:
        raise ProblemException(
            status_code=404, code="asset_not_found",
            title="Asset not found", detail="Asset not found or not uploaded.", retryable=False,
        )

    local_path = Path(asset.storage_key)
    if not local_path.is_absolute():
        local_path = Path.cwd() / local_path
    if local_path.exists():
        stat = local_path.stat()
        return StreamingResponse(
            iter([]),
            headers={
                "Content-Type": "video/mp4",
                "Content-Length": str(stat.st_size),
                "Accept-Ranges": "bytes",
                "Content-Disposition": f'inline; filename="{local_path.name}"',
            },
        )

    from oki.storage.s3 import S3ObjectStore
    store: S3ObjectStore = getattr(request.app.state, "s3_store", None)
    if store is None:
        raise ProblemException(
            status_code=503, code="storage_unavailable",
            title="Storage unavailable", detail="S3 store not initialized.", retryable=True,
        )
    head = await store.head_object(asset.storage_key)
    return StreamingResponse(
        iter([]),
        headers={
            "Content-Type": head.get("content_type") or "video/mp4",
            "Content-Length": str(head.get("content_length") or 0),
            "Accept-Ranges": "bytes",
        },
    )
