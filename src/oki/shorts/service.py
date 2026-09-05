from collections.abc import Callable
from dataclasses import dataclass
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
from oki.shorts.models import (
    ShortApprovals,
    ShortCandidates,
    ShortPublications,
    ShortScores,
    ShortVersions,
)
from oki.shorts.scoring import ShortScorer
from oki.shorts.crop import CropTracker


@dataclass(frozen=True, slots=True)
class ShortCandidateDetails:
    candidate: ShortCandidates
    versions: tuple[ShortVersions, ...]
    scores: tuple[ShortScores, ...]


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
                status=ShortStatus.SCORING,
                source_timestamps=[],
                detected_hooks={},
                raw_score=None,
                created_by_user_id=principal.user_id,
            )
            uow.session.add(candidate)
            await uow.session.flush()

            # Score candidate using heuristics
            await self._score_candidate(uow, candidate, job)

            # Compute crop params for vertical 9:16 output
            await self._compute_crop(uow, candidate, job)

            candidate.status = ShortStatus.CANDIDATE
            await uow.session.flush()
            return candidate

    async def _score_candidate(
        self,
        uow: UnitOfWork,
        candidate: ShortCandidates,
        job: LocalizationJob,
    ) -> None:
        """Run ShortScorer and persist results."""
        from oki.assets.models import SourceAsset
        from oki.analysis.models import TranscriptSegments

        # Attach transient attributes for scoring
        asset = await uow.session.scalar(
            select(SourceAsset).where(SourceAsset.localization_job_id == job.id)
        )
        if asset is not None:
            candidate.source_video_path = str(asset.storage_key) if asset.storage_key else None

        transcript_segments = []
        result = await uow.session.scalars(
            select(TranscriptSegments)
            .where(TranscriptSegments.job_id == job.id)
            .order_by(TranscriptSegments.start_time)
        )
        for seg in result:
            transcript_segments.append({
                "start": float(seg.start_time),
                "end": float(seg.end_time),
                "text": seg.text,
            })
        if transcript_segments:
            candidate.transcript_segments = transcript_segments
            candidate.start_time = transcript_segments[0]["start"]
            candidate.end_time = transcript_segments[-1]["end"]
        else:
            candidate.start_time = 0.0
            candidate.end_time = 0.0

        scores = ShortScorer().score(candidate)
        total = scores.pop("total", 0.0)
        candidate.raw_score = total

        score_record = ShortScores(
            organization_id=candidate.organization_id,
            candidate_id=candidate.id,
            version_id=None,
            factor_scores=scores,
            total_score=total,
        )
        uow.session.add(score_record)
        await uow.session.flush()

    async def _compute_crop(
        self,
        uow: UnitOfWork,
        candidate: ShortCandidates,
        job: LocalizationJob,
    ) -> None:
        """Compute vertical crop parameters for the candidate."""
        from oki.assets.models import SourceAsset

        asset = await uow.session.scalar(
            select(SourceAsset).where(SourceAsset.localization_job_id == job.id)
        )
        if asset is None or not asset.storage_key:
            return

        tracker = CropTracker()
        timestamps = [candidate.start_time, candidate.end_time]
        crop_params = tracker.track(str(asset.storage_key), timestamps)
        candidate.detected_hooks = {"crop_params": crop_params}
        await uow.session.flush()

    async def list_shorts(
        self,
        principal: Principal,
        job_id: UUID | None = None,
        status: ShortStatus | None = None,
    ) -> list[ShortCandidates]:
        """List short candidates with optional filters."""
        async with self._uow_factory() as uow:
            org_ids = [
                m.organization_id for m in principal.memberships
                if Action.CREATOR_READ in m.actions
            ]
            if not org_ids:
                self._authorizer.require(
                    principal, Action.CREATOR_READ, ResourceScope(organization_id=UUID(int=0))
                )

            stmt = select(ShortCandidates).where(
                ShortCandidates.organization_id.in_(org_ids)
            )
            if job_id is not None:
                stmt = stmt.where(ShortCandidates.job_id == job_id)
            if status is not None:
                stmt = stmt.where(ShortCandidates.status == status)
            stmt = stmt.order_by(ShortCandidates.created_at.desc())

            result = await uow.session.scalars(stmt)
            return list(result)

    async def get_short(
        self,
        principal: Principal,
        candidate_id: UUID,
    ) -> ShortCandidateDetails:
        """Get a single candidate with versions and scores."""
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

            versions_result = await uow.session.scalars(
                select(ShortVersions)
                .where(ShortVersions.candidate_id == candidate_id)
                .order_by(ShortVersions.version_number.asc())
            )
            versions = tuple(versions_result)

            scores_result = await uow.session.scalars(
                select(ShortScores)
                .where(ShortScores.candidate_id == candidate_id)
                .order_by(ShortScores.scored_at.asc())
            )
            scores = tuple(scores_result)

            return ShortCandidateDetails(
                candidate=candidate,
                versions=versions,
                scores=scores,
            )

    async def revise(
        self,
        candidate_id: UUID,
        principal: Principal,
        correlation_id: UUID,
        revision_notes: str | None = None,
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
                refinement_prompt=revision_notes,
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

    async def publish_short(
        self,
        short_id: UUID,
        principal: Principal,
        correlation_id: UUID,
    ) -> ShortCandidates:
        """Publish a short candidate (stub — updates status and creates publication record)."""
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

            if candidate.status != ShortStatus.APPROVED:
                raise ProblemException(
                    status_code=409,
                    code="short_not_approved",
                    title="Short not approved",
                    detail="Only approved shorts can be published.",
                )

            publication = ShortPublications(
                organization_id=candidate.organization_id,
                short_id=short_id,
                platform="youtube",
            )
            uow.session.add(publication)

            candidate.status = ShortStatus.PUBLISHED
            await uow.session.flush()
            return candidate

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
