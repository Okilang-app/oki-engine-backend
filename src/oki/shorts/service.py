from collections.abc import Callable
from typing import NoReturn
from uuid import UUID

from sqlalchemy import select

from oki.api.errors import ProblemException
from oki.db.uow import UnitOfWork
from oki.identity.authorization import Authorizer
from oki.identity.enums import Action
from oki.identity.schemas import Principal, ResourceScope
from oki.jobs.models import LocalizationJob
from oki.shorts.enums import ShortStatus
from oki.shorts.models import ShortApprovals, ShortCandidates, ShortVersions


class ShortService:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        authorizer: Authorizer,
    ) -> None:
        self._uow_factory = uow_factory
        self._authorizer = authorizer

    async def generate(
        self,
        job_id: UUID,
        principal: Principal,
        correlation_id: UUID,
    ) -> ShortCandidates:
        """Create a short candidate for a localization job."""
        async with self._uow_factory() as uow:
            job = await uow.session.get(LocalizationJob, job_id)
            if job is None:
                self._not_found(
                    "localization_job_not_found",
                    "Localization job not found",
                )

            self._authorizer.require(
                principal,
                Action.PROJECT_READ,
                self._scope(job.organization_id),
            )

            candidate = ShortCandidates(
                organization_id=job.organization_id,
                job_id=job_id,
                status=ShortStatus.CANDIDATE,
                source_timestamps=[],
                detected_hooks={},
                raw_score=None,
                created_by_user_id=principal.user_id,
            )
            uow.session.add(candidate)
            await uow.session.flush()
            return candidate

    async def revise(
        self,
        candidate_id: UUID,
        principal: Principal,
        correlation_id: UUID,
    ) -> ShortVersions:
        """Create a new revision version for a short candidate."""
        async with self._uow_factory() as uow:
            candidate = await uow.session.get(ShortCandidates, candidate_id)
            if candidate is None:
                self._not_found(
                    "short_candidate_not_found",
                    "Short candidate not found",
                )

            self._authorizer.require(
                principal,
                Action.CREATOR_READ,
                self._scope(candidate.organization_id),
            )

            result = await uow.session.scalars(
                select(ShortVersions)
                .where(ShortVersions.candidate_id == candidate_id)
                .order_by(ShortVersions.version_number.desc())
            )
            latest = result.first()
            version_number = 1 if latest is None else latest.version_number + 1

            version = ShortVersions(
                organization_id=candidate.organization_id,
                candidate_id=candidate_id,
                version_number=version_number,
                crop_params={},
                refinement_prompt=None,
                revised_media_url=None,
            )
            uow.session.add(version)

            candidate.status = ShortStatus.REVISING
            await uow.session.flush()
            return version

    async def approve(
        self,
        short_id: UUID,
        principal: Principal,
        correlation_id: UUID,
    ) -> ShortApprovals:
        """Approve a short candidate for publication."""
        async with self._uow_factory() as uow:
            candidate = await uow.session.get(ShortCandidates, short_id)
            if candidate is None:
                self._not_found(
                    "short_candidate_not_found",
                    "Short candidate not found",
                )

            self._authorizer.require(
                principal,
                Action.CREATOR_REVIEW_SUBMIT,
                self._scope(candidate.organization_id),
            )

            approval = ShortApprovals(
                organization_id=candidate.organization_id,
                short_id=short_id,
                approved_by_user_id=principal.user_id,
            )
            uow.session.add(approval)

            candidate.status = ShortStatus.APPROVED
            await uow.session.flush()
            return approval

    @staticmethod
    def _scope(organization_id: UUID) -> ResourceScope:
        return ResourceScope(organization_id=organization_id)

    @staticmethod
    def _not_found(code: str, title: str) -> NoReturn:
        raise ProblemException(
            status_code=404,
            code=code,
            title=title,
            detail=f"{title}.",
        )
