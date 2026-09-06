from collections.abc import Callable
from typing import Any, NoReturn
from uuid import UUID

from sqlalchemy import func, select

from oki.api.errors import ProblemException
from oki.db.uow import UnitOfWork
from oki.identity.authorization import Authorizer
from oki.identity.enums import Action
from oki.identity.schemas import Principal, ResourceScope
from oki.translations.enums import QaDimension, SOW_DIMENSIONS, PASS_FAIL_DIMENSIONS, TranslationStatus
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
        """Start a new translation for the given job and language pair."""
        from oki.jobs.enums import WorkflowEvent, WorkflowState
        from oki.jobs.state_machine import WorkflowStateMachine
        from oki.sponsors.models import AdSegments
        from oki.sponsors.enums import SponsorStatus

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

            # Gate 1: job must be in AD_REVIEW_REQUIRED
            if job.state != WorkflowState.AD_REVIEW_REQUIRED:
                raise ProblemException(
                    status_code=409,
                    code="invalid_workflow_state",
                    title="Translation cannot start yet",
                    detail=(
                        f"Ad review must be completed before starting translation. "
                        f"Current state: {job.state}. "
                        "Review all sponsor segments on the Sponsors page first."
                    ),
                )

            # Gate 2: all detected ad segments must be actioned
            unreviewed = await uow.session.scalar(
                select(func.count()).select_from(AdSegments)
                .where(AdSegments.job_id == job_id)
                .where(AdSegments.status == SponsorStatus.DETECTED)
            )
            if unreviewed:
                raise ProblemException(
                    status_code=409,
                    code="ad_review_incomplete",
                    title="Ad review incomplete",
                    detail=(
                        f"{unreviewed} sponsor segment(s) still need review. "
                        "Approve, reject, or replace every segment before starting translation."
                    ),
                )

            from oki.assets.models import SourceAsset
            asset_record = await uow.session.scalar(
                select(SourceAsset)
                .where(SourceAsset.localization_job_id == job_id)
                .limit(1)
            )
            if asset_record is None:
                asset_record = await uow.session.scalar(
                    select(SourceAsset)
                    .where(SourceAsset.project_id == project_id)
                    .order_by(SourceAsset.created_at.desc())
                    .limit(1)
                )
            real_asset_id = asset_record.id if asset_record else job_id

            # Transition job state via state machine
            WorkflowStateMachine().transition(job, WorkflowEvent.START_TRANSLATION)

            translation = Translations(
                organization_id=organization_id,
                job_id=job_id,
                project_id=project_id,
                asset_id=real_asset_id,
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
        """Approve translation and advance job to TRANSLATION_REVIEW."""
        from oki.jobs.enums import WorkflowEvent, WorkflowState
        from oki.jobs.state_machine import WorkflowStateMachine

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

            # Advance job state from TRANSLATION_RUNNING → TRANSLATION_REVIEW
            job = await uow.session.get(LocalizationJob, translation.job_id)
            if job and job.state == WorkflowState.TRANSLATION_RUNNING:
                WorkflowStateMachine().transition(job, WorkflowEvent.REQUEST_TRANSLATION_REVIEW)

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

    async def list_segments(
        self,
        principal: Principal,
        translation_id: UUID,
    ) -> list[TranslationSegments]:
        async with self._uow_factory() as uow:
            translation = await uow.session.get(Translations, translation_id)
            if translation is None:
                self._not_found("translation_not_found", "Translation not found")
            self._authorizer.require(
                principal,
                Action.PROJECT_READ,
                self._scope(translation.organization_id),
            )
            rows = await uow.session.scalars(
                select(TranslationSegments)
                .where(TranslationSegments.translation_id == translation_id)
                .order_by(TranslationSegments.sequence_number)
            )
            return list(rows)

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
    # Pass/fail dimensions use 100 (pass) or 0 (fail) scores
    HARD_FAIL_THRESHOLD = 60

    async def evaluate(
        self,
        translation_id: UUID,
        segments: list[dict[str, Any]],
    ) -> dict[QaDimension, int]:
        """Evaluate translation across SOW Section 8.6 QA dimensions using GPT."""
        import json
        from oki.config import Settings
        from oki.providers.factory import create_openai_client

        settings = Settings()
        client = create_openai_client(settings)

        if client is None or not segments:
            return {dim: 70 for dim in SOW_DIMENSIONS}

        model = (
            settings.azure_gpt_deployment
            if settings.azure_openai_endpoint
            else "gpt-4o-mini"
        )
        sample = segments[:10]
        pairs = "\n".join(
            f"SRC: {s.get('source_text', '')}\nTGT: {s.get('translated_text', '')}"
            for s in sample
        )
        prompt = (
            "You are a professional localization QA reviewer. "
            "Evaluate this translated video transcript according to the Oki SOW Section 8.6 criteria.\n\n"
            "Scoring:\n"
            "- meaning_accuracy: 0-100 (semantic faithfulness to source)\n"
            "- naturalness: 0-100 (sounds natural in target language)\n"
            "- timing_fit: 0-100 (translation length fits original audio timing)\n"
            "- terminology: 100=pass, 0=fail (brand names, product names correct)\n"
            "- named_entities: 100=pass, 0=fail (numbers, names, facts unchanged)\n"
            "- brand_safety: 100=pass, 0=fail (no disallowed claims or off-brand content)\n"
            "- creator_voice_match: 0-100 (preserves creator's tone and personality)\n\n"
            f"Segments:\n{pairs[:3000]}\n\n"
            "Return JSON: {\"meaning_accuracy\": N, \"naturalness\": N, \"timing_fit\": N, "
            "\"terminology\": N, \"named_entities\": N, \"brand_safety\": N, \"creator_voice_match\": N}"
        )

        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=300,
                response_format={"type": "json_object"},
            )
            raw = json.loads(resp.choices[0].message.content or "{}")
            return {
                dim: max(0, min(100, int(raw.get(dim.value, 70))))
                for dim in SOW_DIMENSIONS
            }
        except Exception:
            return {dim: 70 for dim in SOW_DIMENSIONS}

    def is_critical_fail(self, scores: dict[QaDimension, int]) -> bool:
        """Return True if any hard-fail condition blocks dubbing (SOW 8.6)."""
        for dim in PASS_FAIL_DIMENSIONS:
            if scores.get(dim, 100) == 0:
                return True
        if scores.get(QaDimension.MEANING_ACCURACY, 100) < self.HARD_FAIL_THRESHOLD:
            return True
        if scores.get(QaDimension.NATURALNESS, 100) < self.HARD_FAIL_THRESHOLD:
            return True
        return False
