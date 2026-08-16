from collections.abc import Callable
from typing import Any, NoReturn
from uuid import UUID

from sqlalchemy import select

from oki.api.errors import ProblemException
from oki.db.uow import UnitOfWork
from oki.identity.authorization import Authorizer
from oki.identity.enums import Action
from oki.identity.schemas import Principal, ResourceScope
from oki.translations.enums import QaDimension, TranslationStatus
from oki.jobs.models import LocalizationJob
from oki.translations.models import (
    TranslationComments,
    TranslationQaReviews,
    TranslationRevisions,
    Translations,
    TranslationSegments,
)


class TranslationService:
    def __init__(self, uow_factory: Callable[[], UnitOfWork], authorizer: Authorizer) -> None:
        self._uow_factory = uow_factory
        self._authorizer = authorizer

    async def start(
        self,
        principal: Principal,
        job_id: UUID,
        target_language: str,
        source_language: str = "en",
    ) -> Translations:
        """Start a new translation for the given job and language pair.

        TODO: integrate real asset lookup and source segment seeding.
        """
        async with self._uow_factory() as uow:
            job = await uow.session.scalar(
                select(LocalizationJob)
                .where(LocalizationJob.id == job_id)
            )
            if job is None:
                self._not_found("job_not_found", "Localization job not found")
            organization_id = job.organization_id
            project_id = job.project_id
            self._authorizer.require(
                principal,
                Action.PROJECT_READ,
                self._scope(organization_id),
            )
            # Stub: create translation record without real asset_id
            translation = Translations(
                organization_id=organization_id,
                job_id=job_id,
                project_id=project_id,
                asset_id=job_id,  # TODO: replace with real asset lookup
                source_language=source_language.lower(),
                target_language=target_language.lower(),
                status=TranslationStatus.PENDING,
                created_by_user_id=principal.user_id,
            )
            uow.session.add(translation)
            await uow.session.flush()
            return translation

    async def revise_segment(
        self,
        principal: Principal,
        segment_id: UUID,
        text: str,
        reason: str | None = None,
    ) -> TranslationSegments:
        """Revise a translation segment text and record history."""
        async with self._uow_factory() as uow:
            segment = await uow.session.scalar(
                select(TranslationSegments)
                .where(TranslationSegments.id == segment_id)
                .with_for_update()
            )
            if segment is None:
                self._not_found("segment_not_found", "Translation segment not found")
            self._authorizer.require(
                principal,
                Action.PROJECT_READ,
                self._scope(segment.organization_id),
            )
            previous_text = segment.translated_text or ""
            segment.translated_text = text
            segment.status = TranslationStatus.REVIEW_PENDING
            revision = TranslationRevisions(
                organization_id=segment.organization_id,
                translation_id=segment.translation_id,
                segment_id=segment.id,
                previous_text=previous_text,
                new_text=text,
                created_by_user_id=principal.user_id,
            )
            uow.session.add(revision)
            await uow.session.flush()
            return segment

    async def submit_review(
        self,
        principal: Principal,
        translation_id: UUID,
    ) -> Translations:
        """Submit a translation for review."""
        async with self._uow_factory() as uow:
            translation = await uow.session.get(Translations, translation_id)
            if translation is None:
                self._not_found("translation_not_found", "Translation not found")
            self._authorizer.require(
                principal,
                Action.PROJECT_READ,
                self._scope(translation.organization_id),
            )
            translation.status = TranslationStatus.REVIEW_PENDING
            await uow.session.flush()
            return translation

    async def get_translation(
        self,
        principal: Principal,
        job_id: UUID,
        language: str,
    ) -> Translations:
        """Get the translation for a job and target language."""
        async with self._uow_factory() as uow:
            translation = await uow.session.scalar(
                select(Translations)
                .where(
                    Translations.job_id == job_id,
                    Translations.target_language == language.lower(),
                )
            )
            if translation is None:
                self._not_found("translation_not_found", "Translation not found")
            self._authorizer.require(
                principal,
                Action.PROJECT_READ,
                self._scope(translation.organization_id),
            )
            return translation

    async def approve(
        self,
        principal: Principal,
        translation_id: UUID,
    ) -> Translations:
        """Approve a translation after review."""
        async with self._uow_factory() as uow:
            translation = await uow.session.get(Translations, translation_id)
            if translation is None:
                self._not_found("translation_not_found", "Translation not found")
            self._authorizer.require(
                principal,
                Action.CREATOR_REVIEW_SUBMIT,
                self._scope(translation.organization_id),
            )
            translation.status = TranslationStatus.APPROVED
            await uow.session.flush()
            return translation

    @staticmethod
    def _not_found(code: str, title: str) -> NoReturn:
        raise ProblemException(
            status_code=404,
            code=code,
            title=title,
            detail=f"The requested {title.lower()} does not exist.",
        )

    @staticmethod
    def _scope(organization_id: UUID) -> ResourceScope:
        return ResourceScope(organization_id=organization_id)


class TranslationQaService:
    """Stub QA evaluation service for translations."""

    async def evaluate(
        self,
        translation_id: UUID,
        segments: list[dict[str, Any]],
    ) -> dict[QaDimension, int]:
        """Evaluate translation across 7 QA dimensions and return scores.

        TODO: Replace with real model-based or heuristic QA evaluation.
        """
        scores: dict[QaDimension, int] = {}
        for dimension in QaDimension:
            # Stub: random-ish deterministic score based on dimension name length
            scores[dimension] = max(1, min(10, 7 + (len(dimension.value) % 3)))
        return scores
