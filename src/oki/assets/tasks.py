"""Hatchet background task stubs for asset validation.

TODO: Replace with real Hatchet workflow tasks once hatchet-sdk is wired.
"""

import logging
from typing import Any
from uuid import UUID

from oki.assets.enums import ValidationStatus
from oki.assets.models import AssetValidationResult
from oki.assets.validation import AssetValidationService
from oki.jobs.enums import WorkflowEvent, WorkflowState
from oki.jobs.models import WorkflowTransition

logger = logging.getLogger(__name__)


class AssetTaskRunner:
    """Manual runner for asset validation background work.

    In production this should be invoked by Hatchet; during MVP it can be
    called directly or through a Celery/ RQ wrapper.
    """

    def __init__(
        self,
        validation_service: AssetValidationService | None = None,
        clamav_host: str = "127.0.0.1",
        clamav_port: int = 3310,
    ) -> None:
        self._validation = validation_service or AssetValidationService(
            clamav_host=clamav_host, clamav_port=clamav_port
        )

    async def validate_source_asset(
        self,
        uow: Any,
        asset_id: UUID,
        file_path: str,
        *,
        expected_sha256: str | None = None,
        correlation_id: UUID | None = None,
    ) -> AssetValidationResult:
        """Run validation, record result, and transition workflow state.

        TODO: Integrate with Hatchet workflow engine for retries and checkpointing.
        """
        from pathlib import Path

        logger.info("validate_source_asset started: asset=%s", asset_id)

        # Transition workflow state if asset is linked to a job
        job_id = await self._job_id_for_asset(uow, asset_id)
        if job_id is not None:
            uow.session.add(
                WorkflowTransition(
                    organization_id=await self._org_id_for_asset(uow, asset_id),
                    job_id=job_id,
                    from_state=WorkflowState.SOURCE_UPLOADED,
                    to_state=WorkflowState.SOURCE_VALIDATED,
                    event=WorkflowEvent.VALIDATE_SOURCE,
                    actor_type="system",
                    actor_id=str(correlation_id) if correlation_id else "system",
                    guard_result=True,
                    guard_details={},
                    reason="Validation started by asset task runner",
                    correlation_id=correlation_id or UUID(int=0),
                )
            )

        result = await self._validation.validate(
            Path(file_path),
            expected_sha256=expected_sha256,
        )

        record = AssetValidationResult(
            source_asset_id=asset_id,
            organization_id=await self._org_id_for_asset(uow, asset_id),
            status=result["status"],
            sha256_computed=result.get("sha256_computed"),
            error_codes=result["error_codes"],
            details=result["details"],
            created_by_user_id=await self._user_id_for_asset(uow, asset_id),
        )
        uow.session.add(record)
        await uow.session.flush()

        logger.info(
            "validate_source_asset completed: asset=%s status=%s",
            asset_id,
            result["status"].value,
        )
        return record

    @staticmethod
    async def _org_id_for_asset(uow: Any, asset_id: UUID) -> UUID:
        from oki.assets.models import SourceAsset

        asset = await uow.session.get(SourceAsset, asset_id)
        if asset is None:
            raise RuntimeError(f"Asset {asset_id} not found")
        return asset.organization_id

    @staticmethod
    async def _job_id_for_asset(uow: Any, asset_id: UUID) -> UUID | None:
        from oki.assets.models import SourceAsset

        asset = await uow.session.get(SourceAsset, asset_id)
        if asset is None:
            return None
        return asset.localization_job_id

    @staticmethod
    async def _user_id_for_asset(uow: Any, asset_id: UUID) -> UUID:
        from oki.assets.models import SourceAsset

        asset = await uow.session.get(SourceAsset, asset_id)
        if asset is None:
            raise RuntimeError(f"Asset {asset_id} not found")
        return asset.created_by_user_id
