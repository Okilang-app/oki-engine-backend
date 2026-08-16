from collections.abc import Callable
from dataclasses import dataclass
from typing import NoReturn
from uuid import UUID

from sqlalchemy import func, select

from oki.api.errors import ProblemException
from oki.db.uow import UnitOfWork
from oki.identity.authorization import Authorizer
from oki.identity.enums import Action
from oki.identity.schemas import Principal, ResourceScope
from oki.jobs.models import LocalizationJob
from oki.reviews.enums import ReviewDecisionType
from oki.reviews.models import (
    ReviewAssignments,
    ReviewComments,
    ReviewDecisions,
    ReviewPackageVersions,
    ReviewPackages,
)


@dataclass(frozen=True, slots=True)
class ReviewPackageDetails:
    package: ReviewPackages
    version: ReviewPackageVersions | None


class ReviewService:
    def __init__(self, uow_factory: Callable[[], UnitOfWork], authorizer: Authorizer) -> None:
        self._uow_factory = uow_factory
        self._authorizer = authorizer

    async def create_package(
        self,
        job_id: UUID,
        principal: Principal,
        correlation_id: UUID,
    ) -> ReviewPackages:
        async with self._uow_factory() as uow:
            job = await uow.session.get(LocalizationJob, job_id)
            if job is None:
                self._not_found("job_not_found", "Localization job not found")
            self._authorizer.require(
                principal,
                Action.CREATOR_REVIEW_SUBMIT,
                self._scope(job.organization_id),
            )
            package = ReviewPackages(
                organization_id=job.organization_id,
                job_id=job.id,
                created_by_user_id=principal.user_id,
                status="open",
                correlation_id=correlation_id,
            )
            uow.session.add(package)
            await uow.session.flush()
            return package

    async def comment(
        self,
        package_id: UUID,
        text: str,
        principal: Principal,
        correlation_id: UUID,
        line_reference: str | None = None,
    ) -> ReviewComments:
        async with self._uow_factory() as uow:
            package = await uow.session.get(ReviewPackages, package_id)
            if package is None:
                self._not_found("package_not_found", "Review package not found")
            self._authorizer.require(
                principal,
                Action.CREATOR_REVIEW_SUBMIT,
                self._scope(package.organization_id),
            )
            version = await self._latest_version(uow, package.id)
            comment = ReviewComments(
                organization_id=package.organization_id,
                package_version_id=version.id,
                author_user_id=principal.user_id,
                text=text,
                line_reference=line_reference,
            )
            uow.session.add(comment)
            await uow.session.flush()
            return comment

    async def decide(
        self,
        package_version_id: UUID,
        decision: ReviewDecisionType,
        principal: Principal,
        correlation_id: UUID,
        reason: str | None = None,
    ) -> ReviewDecisions:
        async with self._uow_factory() as uow:
            version = await uow.session.get(ReviewPackageVersions, package_version_id)
            if version is None:
                self._not_found("version_not_found", "Review package version not found")
            package = await uow.session.get(ReviewPackages, version.package_id)
            if package is None:
                self._not_found("package_not_found", "Review package not found")
            self._authorizer.require(
                principal,
                Action.CREATOR_REVIEW_SUBMIT,
                self._scope(package.organization_id),
            )
            record = ReviewDecisions(
                organization_id=package.organization_id,
                package_version_id=version.id,
                decision=decision,
                reason=reason,
                decided_by_user_id=principal.user_id,
                correlation_id=correlation_id,
            )
            uow.session.add(record)
            await uow.session.flush()
            return record

    async def invalidate_for_change(
        self,
        version_id: UUID,
        principal: Principal,
        correlation_id: UUID,
    ) -> None:
        async with self._uow_factory() as uow:
            version = await uow.session.get(ReviewPackageVersions, version_id)
            if version is None:
                self._not_found("version_not_found", "Review package version not found")
            package = await uow.session.get(ReviewPackages, version.package_id)
            if package is None:
                self._not_found("package_not_found", "Review package not found")
            self._authorizer.require(
                principal,
                Action.CREATOR_REVIEW_SUBMIT,
                self._scope(package.organization_id),
            )
            from datetime import datetime as _dt, timezone
            version.invalidated_at = _dt.now(timezone.utc)
            version.material_changed = True
            await uow.session.flush()

    # Router-facing helpers (indexed by job_id)

    async def get_package_by_job(
        self,
        job_id: UUID,
        principal: Principal,
    ) -> ReviewPackageDetails:
        async with self._uow_factory() as uow:
            package = await uow.session.scalar(
                select(ReviewPackages).where(ReviewPackages.job_id == job_id)
            )
            if package is None:
                self._not_found("package_not_found", "Review package not found")
            self._authorizer.require(
                principal,
                Action.CREATOR_REVIEW_SUBMIT,
                self._scope(package.organization_id),
            )
            version = await self._latest_version(uow, package.id, required=False)
            return ReviewPackageDetails(package=package, version=version)

    async def approve_job(
        self,
        job_id: UUID,
        principal: Principal,
        reason: str | None,
        correlation_id: UUID,
    ) -> ReviewDecisions:
        async with self._uow_factory() as uow:
            package = await uow.session.scalar(
                select(ReviewPackages).where(ReviewPackages.job_id == job_id)
            )
            if package is None:
                self._not_found("package_not_found", "Review package not found")
            self._authorizer.require(
                principal,
                Action.CREATOR_REVIEW_SUBMIT,
                self._scope(package.organization_id),
            )
            version = await self._latest_version(uow, package.id)
            record = ReviewDecisions(
                organization_id=package.organization_id,
                package_version_id=version.id,
                decision=ReviewDecisionType.APPROVED,
                reason=reason,
                decided_by_user_id=principal.user_id,
                correlation_id=correlation_id,
            )
            uow.session.add(record)
            await uow.session.flush()
            return record

    async def reject_job(
        self,
        job_id: UUID,
        principal: Principal,
        reason: str | None,
        correlation_id: UUID,
    ) -> ReviewDecisions:
        async with self._uow_factory() as uow:
            package = await uow.session.scalar(
                select(ReviewPackages).where(ReviewPackages.job_id == job_id)
            )
            if package is None:
                self._not_found("package_not_found", "Review package not found")
            self._authorizer.require(
                principal,
                Action.CREATOR_REVIEW_SUBMIT,
                self._scope(package.organization_id),
            )
            version = await self._latest_version(uow, package.id)
            record = ReviewDecisions(
                organization_id=package.organization_id,
                package_version_id=version.id,
                decision=ReviewDecisionType.REJECTED,
                reason=reason,
                decided_by_user_id=principal.user_id,
                correlation_id=correlation_id,
            )
            uow.session.add(record)
            await uow.session.flush()
            return record

    async def _latest_version(
        self,
        uow: UnitOfWork,
        package_id: UUID,
        *,
        required: bool = True,
    ) -> ReviewPackageVersions | None:
        version = await uow.session.scalar(
            select(ReviewPackageVersions)
            .where(ReviewPackageVersions.package_id == package_id)
            .order_by(ReviewPackageVersions.version_number.desc())
            .limit(1)
        )
        if version is None and required:
            self._not_found("version_not_found", "Review package version not found")
        return version

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
