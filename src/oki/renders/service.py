from collections.abc import Callable
from typing import NoReturn
from uuid import UUID

from sqlalchemy import select

from oki.api.errors import ProblemException
from oki.db.uow import UnitOfWork
from oki.identity.authorization import Authorizer
from oki.identity.enums import Action
from oki.identity.schemas import Principal, ResourceScope
from oki.renders.manifest import RenderManifest as ManifestHasher
from oki.renders.enums import RenderStatus
from oki.renders.models import EditDecisionList, RenderAttempt, RenderJob, RenderManifest


class RenderService:
    def __init__(self, uow_factory: Callable[[], UnitOfWork], authorizer: Authorizer, store=None) -> None:
        self._uow_factory = uow_factory
        self._authorizer = authorizer
        self._store = store

    async def start(
        self,
        principal: Principal,
        edl_id: UUID,
        *,
        correlation_id: UUID,
    ) -> RenderAttempt:
        """Start a render from an EDL, preventing duplicates via manifest hash."""
        async with self._uow_factory() as uow:
            edl = await uow.session.get(EditDecisionList, edl_id)
            if edl is None:
                self._not_found("edl_not_found", "Edit decision list not found")

            self._authorizer.require(
                principal,
                Action.CREATOR_READ,
                ResourceScope(organization_id=edl.organization_id),
            )

            # Build canonical hash from EDL + job context
            inputs = {
                "edl_id": str(edl.id),
                "edl_data": edl.edl_data,
            }
            output_spec = {
                "format": "mp4",
                "resolution": "1920x1080",
            }
            canonical_hash = ManifestHasher.canonical_hash(
                job_id=edl.job_id,
                inputs=inputs,
                output_spec=output_spec,
            )

            # Duplicate prevention: check for existing manifest with same hash
            existing = await uow.session.scalar(
                select(RenderManifest)
                .where(RenderManifest.canonical_hash == canonical_hash)
                .limit(1)
            )
            if existing is not None:
                # Reuse existing manifest: create a new attempt linked to it
                attempt = RenderAttempt(
                    organization_id=edl.organization_id,
                    render_manifest_id=existing.id,
                    provider_key="internal",
                    status="pending",
                    metadata={"correlation_id": str(correlation_id), "reused_manifest": True},
                )
                uow.session.add(attempt)
                await uow.session.flush()
                return attempt

            # Create new manifest
            manifest = RenderManifest(
                organization_id=edl.organization_id,
                job_id=edl.job_id,
                canonical_hash=canonical_hash,
                inputs=inputs,
                output_spec=output_spec,
                status="pending",
            )
            uow.session.add(manifest)
            await uow.session.flush()

            # Link EDL to manifest
            edl.render_manifest_id = manifest.id

            attempt = RenderAttempt(
                organization_id=edl.organization_id,
                render_manifest_id=manifest.id,
                provider_key="internal",
                status="pending",
                metadata={"correlation_id": str(correlation_id)},
            )
            uow.session.add(attempt)
            await uow.session.flush()
            return attempt

    async def create_render_job(
        self,
        principal: Principal,
        project_id: UUID | None,
        job_id: UUID | None,
    ) -> RenderJob:
        """Create a new RenderJob with status QUEUED."""
        async with self._uow_factory() as uow:
            organization_id: UUID | None = None
            if project_id is not None:
                from oki.jobs.models import Project
                project = await uow.session.get(Project, project_id)
                if project is not None:
                    organization_id = project.organization_id
                else:
                    project_id = None
            if organization_id is None and job_id is not None:
                from oki.jobs.models import LocalizationJob
                job = await uow.session.get(LocalizationJob, job_id)
                if job is not None:
                    organization_id = job.organization_id
                else:
                    job_id = None
            if organization_id is None:
                organization_id = principal.memberships[0].organization_id

            self._authorizer.require(
                principal,
                Action.PROJECT_READ,
                self._scope(organization_id),
            )

            render_job = RenderJob(
                organization_id=organization_id,
                project_id=project_id,
                job_id=job_id,
                status=RenderStatus.QUEUED,
                progress_percent=0,
                created_by_user_id=principal.user_id,
            )
            uow.session.add(render_job)
            await uow.session.flush()
            return render_job

    async def execute_render_job(self, render_job_id: UUID) -> None:
        """Trigger the actual video rendering pipeline."""
        if self._store is None:
            raise RuntimeError("Store not available for rendering")
        from oki.renders.opencv_renderer import OpenCVRenderService
        renderer = OpenCVRenderService(self._uow_factory, self._authorizer, self._store)
        await renderer.execute_render(render_job_id)

    async def get_render_job(
        self,
        principal: Principal,
        render_id: UUID,
    ) -> RenderJob:
        """Get a single RenderJob by ID, requiring PROJECT_READ."""
        async with self._uow_factory() as uow:
            render_job = await uow.session.get(RenderJob, render_id)
            if render_job is None:
                self._not_found("render_job_not_found", "Render job not found")

            self._authorizer.require(
                principal,
                Action.PROJECT_READ,
                self._scope(render_job.organization_id),
            )
            return render_job

    async def list_render_jobs(
        self,
        principal: Principal,
    ) -> list[RenderJob]:
        """List render jobs filtered by the principal's org memberships."""
        async with self._uow_factory() as uow:
            org_ids = [
                m.organization_id for m in principal.memberships
                if Action.CREATOR_READ in m.actions
            ]
            if not org_ids:
                self._authorizer.require(
                    principal,
                    Action.CREATOR_READ,
                    ResourceScope(organization_id=UUID(int=0)),
                )
            result = await uow.session.scalars(
                select(RenderJob)
                .where(RenderJob.organization_id.in_(org_ids))
                .order_by(RenderJob.created_at.desc())
            )
            return list(result)

    async def update_render_status(
        self,
        principal: Principal,
        render_id: UUID,
        status: RenderStatus,
        progress_percent: int | None,
        output_storage_key: str | None,
    ) -> RenderJob:
        """Update the status and progress of a render job."""
        async with self._uow_factory() as uow:
            render_job = await uow.session.get(RenderJob, render_id)
            if render_job is None:
                self._not_found("render_job_not_found", "Render job not found")

            self._authorizer.require(
                principal,
                Action.PROJECT_READ,
                self._scope(render_job.organization_id),
            )

            render_job.status = status
            if progress_percent is not None:
                render_job.progress_percent = progress_percent
            if output_storage_key is not None:
                render_job.output_storage_key = output_storage_key

            await uow.session.flush()
            return render_job

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
