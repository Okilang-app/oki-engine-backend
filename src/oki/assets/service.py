"""Asset service: uploads, deduplication, rights validation, stem registration."""

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, NoReturn
from uuid import UUID

from sqlalchemy import select

from oki.api.errors import ProblemException
from oki.assets.enums import AssetStatus, UploadStatus
from oki.assets.models import (
    AssetStem,
    AssetUpload,
    AssetValidationResult,
    MediaArtifact,
    SourceAsset,
    UploadPart,
)
from oki.assets.schemas import (
    AssetCreate,
    CompleteUploadRequest,
    FinalizeUploadRequest,
    SimpleUploadRequest,
    SimpleUploadResponse,
    UploadUrlRequest,
    UploadUrlResponse,
)
from oki.assets.validation import AssetValidationService
from oki.db.uow import UnitOfWork
from oki.identity.authorization import Authorizer
from oki.identity.enums import Action
from oki.identity.schemas import Principal, ResourceScope
from oki.rights.enums import ContentFormat, Platform
from oki.rights.gate import RightsGate
from oki.rights.policy import RightsRequest
from oki.storage.protocol import ObjectStore

logger = logging.getLogger(__name__)

DEFAULT_PART_SIZE = 50 * 1024 * 1024  # 50 MB


@dataclass(frozen=True, slots=True)
class AssetDetails:
    asset: SourceAsset
    upload: AssetUpload | None


class AssetService:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        authorizer: Authorizer,
        store: ObjectStore,
    ) -> None:
        self._uow_factory = uow_factory
        self._authorizer = authorizer
        self._store = store
        self._gate = RightsGate(uow_factory)
        self._validation = AssetValidationService()

    async def create_upload(
        self,
        principal: Principal,
        payload: UploadUrlRequest,
        *,
        correlation_id: UUID,
    ) -> UploadUrlResponse:
        """Create an asset record, initiate multipart upload, and return presigned part URLs."""
        async with self._uow_factory() as uow:
            # Resolve implicit asset creation if needed
            asset = await uow.session.get(SourceAsset, payload.asset_id)
            if asset is None:
                raise self._not_found("asset_not_found", "Asset not found")

            self._authorizer.require(
                principal,
                Action.ASSET_CREATE,
                self._scope(asset.organization_id),
            )

            # Ensure rights are in place before accepting uploads
            await self._require_rights(uow, asset)

            total_parts = math.ceil(payload.total_size / payload.part_size)
            storage_key = f"uploads/{asset.organization_id}/{asset.id}/{payload.file_name}"

            upload_id = await self._store.initiate_multipart_upload(
                key=storage_key,
                content_type=payload.content_type,
            )

            upload_record = AssetUpload(
                source_asset_id=asset.id,
                organization_id=asset.organization_id,
                status=UploadStatus.IN_PROGRESS,
                upload_id=upload_id,
                storage_key=storage_key,
                part_size=payload.part_size,
                total_parts=total_parts,
                created_by_user_id=principal.user_id,
            )
            uow.session.add(upload_record)
            await uow.session.flush()

            parts = []
            for part_number in range(1, total_parts + 1):
                presigned = await self._store.presign_upload_part(
                    key=storage_key,
                    upload_id=upload_id,
                    part_number=part_number,
                )
                parts.append({"part_number": part_number, "presigned_url": presigned})

            return UploadUrlResponse(
                upload_id=upload_record.id,
                storage_key=storage_key,
                parts=parts,  # type: ignore[arg-type]
            )

    async def create_simple_upload(
        self,
        principal: Principal,
        payload: SimpleUploadRequest,
    ) -> SimpleUploadResponse:
        """Create a SourceAsset and return a single presigned PUT URL."""
        async with self._uow_factory() as uow:
            from oki.creators.models import Creator

            if not principal.memberships:
                self._authorizer.require(
                    principal,
                    Action.ASSET_CREATE,
                    ResourceScope(organization_id=UUID(int=0)),
                )

            organization_id = principal.memberships[0].organization_id
            self._authorizer.require(
                principal,
                Action.ASSET_CREATE,
                self._scope(organization_id),
            )

            creator = await uow.session.scalar(
                select(Creator)
                .where(Creator.organization_id == organization_id)
                .limit(1)
            )
            creator_id = creator.id if creator else UUID(int=0)

            asset = SourceAsset(
                organization_id=organization_id,
                creator_id=creator_id,
                title=payload.title,
                status=AssetStatus.ACTIVE,
                size_bytes=payload.size_bytes,
                created_by_user_id=principal.user_id,
            )
            uow.session.add(asset)
            await uow.session.flush()

            storage_key = f"uploads/{asset.id}/{payload.file_name}"
            presigned_url = await self._store.presign_put(
                key=storage_key,
                content_type=payload.content_type,
            )
            asset.storage_key = storage_key
            await uow.session.flush()

            return SimpleUploadResponse(
                asset_id=asset.id,
                presigned_url=presigned_url,
                storage_key=storage_key,
            )

    async def finalize_upload(
        self,
        principal: Principal,
        asset_id: UUID,
        payload: FinalizeUploadRequest,
    ) -> AssetDetails:
        """Finalize an asset after direct upload by setting SHA-256 and status."""
        async with self._uow_factory() as uow:
            asset = await uow.session.get(SourceAsset, asset_id)
            if asset is None:
                self._not_found("asset_not_found", "Asset not found")

            self._authorizer.require(
                principal,
                Action.ASSET_CREATE,
                self._scope(asset.organization_id),
            )

            asset.sha256 = payload.sha256.lower()
            asset.status = AssetStatus.ACTIVE
            await uow.session.flush()
            return AssetDetails(asset=asset, upload=None)

    async def complete_upload(
        self,
        principal: Principal,
        payload: CompleteUploadRequest,
        *,
        correlation_id: UUID,
    ) -> AssetDetails:
        """Complete multipart upload, apply SHA-256 deduplication, and finalize asset."""
        async with self._uow_factory() as uow:
            upload = await uow.session.get(AssetUpload, payload.upload_id)
            if upload is None:
                self._not_found("upload_not_found", "Upload not found")

            asset = await uow.session.get(SourceAsset, upload.source_asset_id)
            if asset is None:
                self._not_found("asset_not_found", "Asset not found")

            self._authorizer.require(
                principal,
                Action.ASSET_CREATE,
                self._scope(asset.organization_id),
            )

            # Complete the S3 multipart upload
            parts = [{"PartNumber": p.part_number, "ETag": p.etag} for p in payload.parts]
            await self._store.complete_multipart(
                key=upload.storage_key,
                upload_id=upload.upload_id,
                parts=parts,
            )

            # SHA-256 deduplication: reuse existing asset storage key if hash already known
            dedup_asset = await uow.session.scalar(
                select(SourceAsset.id)
                .where(
                    SourceAsset.sha256 == payload.sha256.lower(),
                    SourceAsset.id != asset.id,
                    SourceAsset.status != AssetStatus.DELETED,
                )
                .limit(1)
            )

            if dedup_asset is not None:
                # Deduplicate: delete the new object, point to existing storage key
                existing = await uow.session.get(SourceAsset, dedup_asset)
                if existing and existing.storage_key:
                    await self._store.delete_object(upload.storage_key)
                    upload.storage_key = existing.storage_key
                    asset.storage_key = existing.storage_key
                    asset.storage_bucket = existing.storage_bucket

            upload.status = UploadStatus.COMPLETED
            upload.sha256 = payload.sha256.lower()
            asset.sha256 = payload.sha256.lower()
            asset.status = AssetStatus.ACTIVE
            if asset.storage_key is None:
                asset.storage_key = upload.storage_key

            await uow.session.flush()
            return AssetDetails(asset=asset, upload=upload)

    async def validate_rights(
        self,
        principal: Principal,
        asset_id: UUID,
        *,
        correlation_id: UUID,
    ) -> dict[str, Any]:
        """Run RightsGate evaluation for the asset's creator and return decision."""
        async with self._uow_factory() as uow:
            asset = await uow.session.get(SourceAsset, asset_id)
            if asset is None:
                self._not_found("asset_not_found", "Asset not found")

            self._authorizer.require(
                principal,
                Action.ASSET_VALIDATE,
                self._scope(asset.organization_id),
            )

            request = RightsRequest(
                organization_id=asset.organization_id,
                creator_id=asset.creator_id,
                language_code="en",
                territory_code="US",
                platform=Platform.YOUTUBE,
                content_format=ContentFormat.FULL,
                operation="asset_upload",
                project_id=asset.project_id,
                asset_reference=str(asset.id),
            )
            decision = await self._gate.evaluate(request)
            return {
                "approved": decision.approved,
                "reason_code": decision.reason_code,
                "reason_details": decision.reason_details,
                "agreement_version_id": decision.agreement_version_id,
                "evaluation_id": decision.evaluation_id,
            }

    async def register_stem(
        self,
        principal: Principal,
        asset_id: UUID,
        stem_type: str,
        storage_key: str,
        *,
        duration_seconds: int | None = None,
        sample_rate: int | None = None,
        channel_count: int | None = None,
        correlation_id: UUID | None = None,
    ) -> AssetStem:
        """Register an isolated audio stem for an asset."""
        async with self._uow_factory() as uow:
            asset = await uow.session.get(SourceAsset, asset_id)
            if asset is None:
                self._not_found("asset_not_found", "Asset not found")

            self._authorizer.require(
                principal,
                Action.STEM_REGISTER,
                self._scope(asset.organization_id),
            )

            stem = AssetStem(
                source_asset_id=asset.id,
                organization_id=asset.organization_id,
                stem_type=stem_type,
                storage_key=storage_key,
                duration_seconds=duration_seconds,
                sample_rate=sample_rate,
                channel_count=channel_count,
            )
            uow.session.add(stem)
            await uow.session.flush()
            return stem

    async def get_details(
        self,
        principal: Principal,
        asset_id: UUID,
    ) -> AssetDetails:
        """Return asset details with latest upload."""
        async with self._uow_factory() as uow:
            asset = await uow.session.get(SourceAsset, asset_id)
            if asset is None:
                self._not_found("asset_not_found", "Asset not found")

            self._authorizer.require(
                principal,
                Action.ASSET_READ,
                self._scope(asset.organization_id),
            )

            upload = await uow.session.scalar(
                select(AssetUpload)
                .where(AssetUpload.source_asset_id == asset.id)
                .order_by(AssetUpload.created_at.desc())
                .limit(1)
            )
            return AssetDetails(asset=asset, upload=upload)

    async def get_playback_url(
        self,
        principal: Principal,
        asset_id: UUID,
        *,
        expires_in: int = 3600,
    ) -> str:
        """Return a presigned GET URL for video playback."""
        async with self._uow_factory() as uow:
            asset = await uow.session.get(SourceAsset, asset_id)
            if asset is None:
                self._not_found("asset_not_found", "Asset not found")
            self._authorizer.require(
                principal,
                Action.PROJECT_READ,
                self._scope(asset.organization_id),
            )
            if not asset.storage_key:
                self._not_found("asset_not_uploaded", "Asset has not been uploaded yet")
            return await self._store.presign_get(key=asset.storage_key, expires_in=expires_in)

    async def create_asset(
        self,
        principal: Principal,
        payload: AssetCreate,
        *,
        correlation_id: UUID,
    ) -> SourceAsset:
        """Create a bare SourceAsset record (no upload yet)."""
        async with self._uow_factory() as uow:
            from oki.creators.models import Creator

            creator = await uow.session.get(Creator, payload.creator_id)
            if creator is None:
                self._not_found("creator_not_found", "Creator not found")

            resource = self._scope(creator.organization_id)
            self._authorizer.require(principal, Action.ASSET_CREATE, resource)

            asset = SourceAsset(
                organization_id=creator.organization_id,
                creator_id=creator.id,
                rights_agreement_id=payload.rights_agreement_id,
                project_id=payload.project_id,
                localization_job_id=payload.localization_job_id,
                title=payload.title,
                description=payload.description,
                status=AssetStatus.DRAFT,
                created_by_user_id=principal.user_id,
            )
            uow.session.add(asset)
            await uow.session.flush()
            return asset

    async def _require_rights(self, uow: UnitOfWork, asset: SourceAsset) -> None:
        """Best-effort rights check before upload; not fatal if no agreement exists."""
        # During MVP we only enforce rights for assets that declare an agreement.
        if asset.rights_agreement_id is None:
            return
        request = RightsRequest(
            organization_id=asset.organization_id,
            creator_id=asset.creator_id,
            language_code="en",
            territory_code="US",
            platform=Platform.YOUTUBE,
            content_format=ContentFormat.FULL,
            operation="asset_upload",
            project_id=asset.project_id,
            asset_reference=str(asset.id),
        )
        decision = await self._gate.evaluate(request)
        if not decision.approved:
            raise ProblemException(
                status_code=403,
                code="rights_not_approved",
                title="Rights not approved",
                detail=f"Rights evaluation failed: {decision.reason_code}",
            )

    async def list_assets(
        self,
        principal: Principal,
    ) -> list[SourceAsset]:
        async with self._uow_factory() as uow:
            org_ids = [
                m.organization_id for m in principal.memberships
                if Action.CREATOR_READ in m.actions
            ]
            if not org_ids:
                self._authorizer.require(
                    principal, Action.CREATOR_READ, ResourceScope(organization_id=UUID(int=0))
                )
            result = await uow.session.scalars(
                select(SourceAsset)
                .where(SourceAsset.organization_id.in_(org_ids))
                .order_by(SourceAsset.created_at.desc())
            )
            return list(result)

    @staticmethod
    def _scope(organization_id: UUID) -> ResourceScope:
        return ResourceScope(
            organization_id=organization_id,
            creator_organization_id=organization_id,
        )

    @staticmethod
    def _not_found(code: str, title: str) -> NoReturn:
        raise ProblemException(
            status_code=404,
            code=code,
            title=title,
            detail=f"The requested {title.lower()} does not exist.",
        )
