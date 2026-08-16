"""FFmpeg render service — delegates to OpenCVRenderService (the canonical renderer).

This module exists for backward compatibility. The real implementation lives in
opencv_renderer.py which handles both cutting and ad insertion.
"""

from collections.abc import Callable
from uuid import UUID

from oki.db.uow import UnitOfWork
from oki.identity.authorization import Authorizer
from oki.renders.opencv_renderer import OpenCVRenderService
from oki.storage.s3 import S3ObjectStore


class FFmpegRenderService:
    """Thin wrapper that delegates to OpenCVRenderService."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        authorizer: Authorizer,
        store: S3ObjectStore,
    ) -> None:
        self._delegate = OpenCVRenderService(uow_factory, authorizer, store)

    async def execute_render(self, render_job_id: UUID) -> None:
        await self._delegate.execute_render(render_job_id)
