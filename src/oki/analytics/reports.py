"""Report builders for daily production and weekly management reports."""

from collections.abc import Callable
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from oki.analytics.models import CostLedgerEntries, OkiConversionEvents
from oki.creators.models import Creator
from oki.db.uow import UnitOfWork
from oki.jobs.enums import WorkflowState
from oki.jobs.models import DeadLetter, LocalizationJob, WorkflowTransition
from oki.renders.enums import RenderStatus
from oki.renders.models import RenderJob
from oki.shorts.models import ShortCandidates


class DailyProductionReport:
    """Build a daily production status report."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def build(
        self, organization_id: UUID, report_date: date
    ) -> dict[str, Any]:
        """Return a daily production report structure.

        Args:
            organization_id: The organization scope.
            report_date: The calendar date for the report.

        Returns:
            A dict with sections: jobs_completed, shorts_generated, costs, issues.
        """
        day_start = datetime.combine(report_date, datetime.min.time())
        day_end = day_start + timedelta(days=1)

        async with self._uow_factory() as uow:
            # Jobs completed (terminal states updated on the report date)
            completed_states = (
                WorkflowState.PUBLISHED,
                WorkflowState.ARCHIVED,
            )
            jobs_stmt = (
                select(func.count(LocalizationJob.id))
                .where(LocalizationJob.organization_id == organization_id)
                .where(LocalizationJob.updated_at >= day_start)
                .where(LocalizationJob.updated_at < day_end)
                .where(LocalizationJob.state.in_(completed_states))
            )
            jobs_completed = (await uow.session.scalar(jobs_stmt)) or 0

            # Shorts generated
            shorts_stmt = (
                select(func.count(ShortCandidates.id))
                .where(ShortCandidates.organization_id == organization_id)
                .where(ShortCandidates.created_at >= day_start)
                .where(ShortCandidates.created_at < day_end)
            )
            shorts_count = (await uow.session.scalar(shorts_stmt)) or 0

            # Costs
            costs_stmt = (
                select(
                    func.coalesce(func.sum(CostLedgerEntries.amount), Decimal("0.00")),
                    func.count(CostLedgerEntries.id),
                )
                .where(CostLedgerEntries.organization_id == organization_id)
                .where(CostLedgerEntries.incurred_at >= day_start)
                .where(CostLedgerEntries.incurred_at < day_end)
            )
            costs_result = await uow.session.execute(costs_stmt)
            total_cost, cost_entries = costs_result.one()

            # Issues (failed jobs or dead letters on the date)
            failed_jobs_stmt = (
                select(func.count(LocalizationJob.id))
                .where(LocalizationJob.organization_id == organization_id)
                .where(LocalizationJob.updated_at >= day_start)
                .where(LocalizationJob.updated_at < day_end)
                .where(LocalizationJob.state == WorkflowState.FAILED)
            )
            failed_jobs = (await uow.session.scalar(failed_jobs_stmt)) or 0

            dead_letters_stmt = (
                select(func.count(DeadLetter.id))
                .where(DeadLetter.organization_id == organization_id)
                .where(DeadLetter.created_at >= day_start)
                .where(DeadLetter.created_at < day_end)
            )
            dead_letters = (await uow.session.scalar(dead_letters_stmt)) or 0

            render_failures_stmt = (
                select(func.count(RenderJob.id))
                .where(RenderJob.organization_id == organization_id)
                .where(RenderJob.updated_at >= day_start)
                .where(RenderJob.updated_at < day_end)
                .where(RenderJob.status == RenderStatus.FAILED)
            )
            render_failures = (await uow.session.scalar(render_failures_stmt)) or 0

            issues_count = failed_jobs + dead_letters + render_failures

            return {
                "report_type": "daily_production",
                "date": report_date.isoformat(),
                "jobs_completed": {
                    "count": jobs_completed,
                    "items": [],
                },
                "shorts_generated": {
                    "count": shorts_count,
                    "items": [],
                },
                "costs": {
                    "total": total_cost,
                    "currency": "USD",
                    "breakdown": [],
                    "entries": cost_entries,
                },
                "issues": {
                    "count": issues_count,
                    "items": [],
                },
            }


class WeeklyManagementReport:
    """Build a weekly management summary report."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def build(
        self, organization_id: UUID, week_starting: date
    ) -> dict[str, Any]:
        """Return a weekly management report structure.

        Args:
            organization_id: The organization scope.
            week_starting: The Monday (or start-of-week) date for the report.

        Returns:
            A dict with sections: revenue, creator_acquisitions, pipeline_status, action_items.
        """
        week_end = week_starting + timedelta(days=7)
        week_start_dt = datetime.combine(week_starting, datetime.min.time())
        week_end_dt = datetime.combine(week_end, datetime.min.time())

        async with self._uow_factory() as uow:
            # Revenue from conversions
            revenue_stmt = (
                select(func.coalesce(func.sum(OkiConversionEvents.value), 0.0))
                .where(OkiConversionEvents.organization_id == organization_id)
                .where(OkiConversionEvents.occurred_at >= week_start_dt)
                .where(OkiConversionEvents.occurred_at < week_end_dt)
            )
            total_revenue = (await uow.session.scalar(revenue_stmt)) or 0.0

            # Creator acquisitions
            new_creators_stmt = (
                select(func.count(Creator.id))
                .where(Creator.organization_id == organization_id)
                .where(Creator.created_at >= week_start_dt)
                .where(Creator.created_at < week_end_dt)
            )
            new_creators = (await uow.session.scalar(new_creators_stmt)) or 0

            # Pipeline status
            pipeline_stmt = (
                select(LocalizationJob.state, func.count(LocalizationJob.id))
                .where(LocalizationJob.organization_id == organization_id)
                .group_by(LocalizationJob.state)
            )
            pipeline_result = await uow.session.execute(pipeline_stmt)
            pipeline_counts = {row.state: row.count for row in pipeline_result.all()}

            # Action items: pending publications, awaiting review, blocked jobs
            blocked_stmt = (
                select(func.count(LocalizationJob.id))
                .where(LocalizationJob.organization_id == organization_id)
                .where(LocalizationJob.state == WorkflowState.BLOCKED)
            )
            blocked_count = (await uow.session.scalar(blocked_stmt)) or 0

            review_stmt = (
                select(func.count(LocalizationJob.id))
                .where(LocalizationJob.organization_id == organization_id)
                .where(
                    LocalizationJob.state.in_(
                        (
                            WorkflowState.CREATOR_REVIEW,
                            WorkflowState.TRANSLATION_REVIEW,
                            WorkflowState.AUDIO_REVIEW,
                        )
                    )
                )
            )
            review_count = (await uow.session.scalar(review_stmt)) or 0

            action_items = blocked_count + review_count

            return {
                "report_type": "weekly_management",
                "week_starting": week_starting.isoformat(),
                "week_ending": (week_starting + timedelta(days=6)).isoformat(),
                "revenue": {
                    "total": total_revenue,
                    "currency": "USD",
                    "by_creator": [],
                },
                "creator_acquisitions": {
                    "new_creators": new_creators,
                    "pending_agreements": 0,
                    "signed_agreements": 0,
                },
                "pipeline_status": {
                    "in_translation": pipeline_counts.get(
                        WorkflowState.TRANSLATION_RUNNING, 0
                    ),
                    "in_dubbing": pipeline_counts.get(
                        WorkflowState.DUBBING_RUNNING, 0
                    ),
                    "in_render": pipeline_counts.get(
                        WorkflowState.RENDER_RUNNING, 0
                    ),
                    "awaiting_review": review_count,
                },
                "action_items": {
                    "count": action_items,
                    "items": [],
                },
            }
