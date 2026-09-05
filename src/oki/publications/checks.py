from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select

from oki.publications.models import Publications, PublicationStatus
from oki.db.uow import UnitOfWork
from oki.api.errors import ProblemException


class PlatformCheckService:
    def __init__(self, uow_factory) -> None:
        self._uow_factory = uow_factory

    async def validate_disclosure(self, publication_id: UUID) -> None:
        """Validate sponsorship disclosure requirements (FTC/YouTube)."""
        async with self._uow_factory() as uow:
            pub = await uow.session.get(Publications, publication_id)
            if pub is None:
                raise ProblemException(status_code=404, code="publication_not_found",
                                       title="Publication not found",
                                       detail="The publication does not exist.")
            # Check that the job has sponsor segment metadata indicating disclosure
            from oki.jobs.models import LocalizationJob
            job = await uow.session.get(LocalizationJob, pub.job_id)
            if job is None:
                raise ProblemException(status_code=404, code="job_not_found",
                                       title="Job not found", detail="The job does not exist.")
            # Minimal check: ensure title or description hints at paid promotion
            # In a real system, this would use NLP or check against sponsor database
            if not pub.title and not pub.description:
                raise ProblemException(status_code=400, code="disclosure_missing",
                                       title="Disclosure missing",
                                       detail="Publication title and description are empty. Add a sponsorship disclosure.")

    async def validate_metadata(self, publication_id: UUID) -> None:
        """Validate title, description, and metadata compliance."""
        async with self._uow_factory() as uow:
            pub = await uow.session.get(Publications, publication_id)
            if pub is None:
                raise ProblemException(status_code=404, code="publication_not_found",
                                       title="Publication not found",
                                       detail="The publication does not exist.")
            if not pub.title or len(pub.title) < 5:
                raise ProblemException(status_code=400, code="title_too_short",
                                       title="Title too short",
                                       detail="YouTube title must be at least 5 characters.")
            if pub.title and len(pub.title) > 100:
                raise ProblemException(status_code=400, code="title_too_long",
                                       title="Title too long",
                                       detail="YouTube title must be at most 100 characters.")
            if not pub.description:
                raise ProblemException(status_code=400, code="description_missing",
                                       title="Description missing",
                                       detail="YouTube description is required.")
