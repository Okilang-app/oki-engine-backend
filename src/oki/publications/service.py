from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import NoReturn
from uuid import UUID

from sqlalchemy import func, select

from oki.api.errors import ProblemException
from oki.db.uow import UnitOfWork
from oki.identity.authorization import Authorizer
from oki.identity.enums import Action
from oki.identity.schemas import Principal, ResourceScope
from oki.jobs.models import LocalizationJob
from oki.publications.enums import PublicationStatus
from oki.publications.models import (
    PublicationAttempts,
    Publications,
    PublishApprovals,
)


@dataclass(frozen=True, slots=True)
class PublicationDetails:
    publication: Publications


class PublicationService:
    def __init__(self, uow_factory: Callable[[], UnitOfWork], authorizer: Authorizer) -> None:
        self._uow_factory = uow_factory
        self._authorizer = authorizer

    async def list_publications(
        self,
        principal: Principal,
    ) -> list[Publications]:
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
                select(Publications)
                .where(Publications.organization_id.in_(org_ids))
                .order_by(Publications.created_at.desc())
            )
            return list(result)

    async def create(
        self,
        job_id: UUID,
        principal: Principal,
        correlation_id: UUID,
    ) -> Publications:
        async with self._uow_factory() as uow:
            job = await uow.session.get(LocalizationJob, job_id)
            if job is None:
                self._not_found("job_not_found", "Localization job not found")

            self._authorizer.require(
                principal,
                Action.PUBLICATION_UPLOAD_PRIVATE,
                self._scope(job.organization_id),
            )

            publication = Publications(
                organization_id=job.organization_id,
                job_id=job_id,
                status=PublicationStatus.DRAFT,
                created_by_user_id=principal.user_id,
            )
            uow.session.add(publication)
            await uow.session.flush()
            return publication

    async def upload_private(
        self,
        publication_id: UUID,
        principal: Principal,
        correlation_id: UUID,
    ) -> Publications:
        async with self._uow_factory() as uow:
            publication = await uow.session.get(Publications, publication_id)
            if publication is None:
                self._not_found("publication_not_found", "Publication not found")

            self._authorizer.require(
                principal,
                Action.PUBLICATION_UPLOAD_PRIVATE,
                self._scope(publication.organization_id),
            )

            attempt_count = await uow.session.scalar(
                select(func.count(PublicationAttempts.id)).where(
                    PublicationAttempts.publication_id == publication_id
                )
            )

            attempt = PublicationAttempts(
                organization_id=publication.organization_id,
                publication_id=publication_id,
                attempt_number=int(attempt_count or 0) + 1,
                action="upload_private",
            )
            uow.session.add(attempt)

            publication.status = PublicationStatus.PRIVATE_UPLOADED
            await uow.session.flush()
            return publication

    async def approve_release(
        self,
        publication_id: UUID,
        principal: Principal,
        correlation_id: UUID,
    ) -> PublishApprovals:
        async with self._uow_factory() as uow:
            publication = await uow.session.get(Publications, publication_id)
            if publication is None:
                self._not_found("publication_not_found", "Publication not found")

            self._authorizer.require(
                principal,
                Action.PUBLICATION_RELEASE_PUBLIC,
                self._scope(publication.organization_id),
            )

            approval = PublishApprovals(
                organization_id=publication.organization_id,
                publication_id=publication_id,
                approved_by_user_id=principal.user_id,
                approved_at=datetime.now(UTC),
            )
            uow.session.add(approval)
            await uow.session.flush()
            return approval

    async def publish(
        self,
        publication_id: UUID,
        principal: Principal,
        correlation_id: UUID,
    ) -> Publications:
        async with self._uow_factory() as uow:
            publication = await uow.session.get(Publications, publication_id)
            if publication is None:
                self._not_found("publication_not_found", "Publication not found")

            self._authorizer.require(
                principal,
                Action.PUBLICATION_RELEASE_PUBLIC,
                self._scope(publication.organization_id),
            )

            if publication.status != PublicationStatus.PRIVATE_UPLOADED:
                raise ProblemException(
                    status_code=409,
                    code="publication_not_ready",
                    title="Publication not ready",
                    detail="Publication must be in PRIVATE_UPLOADED state before publishing.",
                )

            approval = await uow.session.scalar(
                select(PublishApprovals)
                .where(PublishApprovals.publication_id == publication_id)
                .where(
                    (PublishApprovals.expires_at.is_(None))
                    | (PublishApprovals.expires_at > datetime.now(UTC))
                )
                .order_by(PublishApprovals.approved_at.desc())
                .limit(1)
            )
            if approval is None:
                raise ProblemException(
                    status_code=409,
                    code="publication_not_approved",
                    title="Publication not approved",
                    detail="A valid publish approval is required before publishing.",
                )

            attempt_count = await uow.session.scalar(
                select(func.count(PublicationAttempts.id)).where(
                    PublicationAttempts.publication_id == publication_id
                )
            )
            attempt = PublicationAttempts(
                organization_id=publication.organization_id,
                publication_id=publication_id,
                attempt_number=int(attempt_count or 0) + 1,
                action="publish",
            )
            uow.session.add(attempt)

            publication.status = PublicationStatus.PUBLISHED
            publication.published_at = datetime.now(UTC)
            await uow.session.flush()
            return publication

    async def unpublish(
        self,
        publication_id: UUID,
        principal: Principal,
        correlation_id: UUID,
    ) -> Publications:
        async with self._uow_factory() as uow:
            publication = await uow.session.get(Publications, publication_id)
            if publication is None:
                self._not_found("publication_not_found", "Publication not found")

            self._authorizer.require(
                principal,
                Action.PUBLICATION_UNPUBLISH,
                self._scope(publication.organization_id),
            )

            attempt_count = await uow.session.scalar(
                select(func.count(PublicationAttempts.id)).where(
                    PublicationAttempts.publication_id == publication_id
                )
            )
            attempt = PublicationAttempts(
                organization_id=publication.organization_id,
                publication_id=publication_id,
                attempt_number=int(attempt_count or 0) + 1,
                action="unpublish",
            )
            uow.session.add(attempt)

            publication.status = PublicationStatus.UNPUBLISHED
            await uow.session.flush()
            return publication

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
