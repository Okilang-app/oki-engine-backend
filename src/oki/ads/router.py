"""Ad API router."""

from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from oki.ads.schemas import AdCreate, AdResponse
from oki.ads.service import AdService
from oki.identity.dependencies import current_principal
from oki.identity.schemas import Principal

router = APIRouter(prefix="/api", tags=["ads"])


def _service(request: Request) -> AdService:
    service = getattr(request.app.state, "ad_service", None)
    if service is None:
        raise RuntimeError("AdService not available")
    return service


@router.get("/ads", response_model=list[AdResponse])
async def list_ads(
    request: Request,
    principal: Principal = Depends(current_principal),
) -> list[AdResponse]:
    ads = await _service(request).list_ads(principal)
    return [AdResponse.model_validate(a) for a in ads]


@router.post("/ads", response_model=AdResponse, status_code=status.HTTP_201_CREATED)
async def create_ad(
    request: Request,
    payload: AdCreate,
    principal: Principal = Depends(current_principal),
) -> AdResponse:
    ad = await _service(request).create_ad(principal, payload)
    return AdResponse.model_validate(ad)


@router.get("/ads/{ad_id}/playback-url")
async def get_ad_playback_url(
    ad_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> dict:
    """Return a presigned URL to preview the replacement ad video."""
    ad = await _service(request).get_ad(principal, ad_id)
    if not ad.storage_key:
        raise RuntimeError("Ad has no storage key")
    store = getattr(request.app.state, "s3_store", None)
    if store is None:
        raise RuntimeError("S3 store not available")
    url = await store.presign_get(key=ad.storage_key, expires_in=3600)
    return {"playback_url": url, "ad_id": str(ad_id)}


@router.delete("/ads/{ad_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ad(
    request: Request,
    ad_id: UUID,
    principal: Principal = Depends(current_principal),
) -> None:
    await _service(request).delete_ad(principal, ad_id)
