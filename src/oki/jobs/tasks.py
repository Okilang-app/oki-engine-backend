from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from oki.api.errors import ProblemException
from oki.db.uow import UnitOfWork
from oki.jobs.enums import TaskGroup, TaskRunStatus, WorkflowEvent
from oki.jobs.models import DeadLetter, LocalizationJob, OutboxEvent, TaskRun, WorkflowTransition
from oki.jobs.state_machine import (
    GuardRejected,
    TransitionDecision,
    WorkflowStateMachine,
)

UnitOfWorkFactory = Callable[[], UnitOfWork]

@dataclass(frozen=True, slots=True)
class GuardEvaluation:
    allowed: bool
    actor_type: str
    actor_id: str | None
    details: dict[str, Any]


class GuardEvaluator(Protocol):
    async def evaluate(
        self,
        uow: UnitOfWork,
        job: LocalizationJob,
        event: WorkflowEvent,
        context: dict[str, Any],
    ) -> GuardEvaluation: ...


class HatchetTaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dispatch_id: UUID
    job_id: UUID
    event: WorkflowEvent
    guard_context: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(min_length=1)
    correlation_id: UUID
    creator_key: str = Field(min_length=1, max_length=150)
    provider_key: str = Field(default="internal", min_length=1, max_length=150)
    provider_units: int = Field(default=1, ge=1)
    provider_limit: int = Field(default=100, ge=1)
    outbox_event_type: str = Field(min_length=1, max_length=150)
    outbox_payload: dict[str, Any] = Field(default_factory=dict)
    outbox_headers: dict[str, Any] = Field(default_factory=dict)


class WorkflowTaskRunner:
    """Advance Oki state only inside its guarded PostgreSQL transaction."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        guard_evaluator: GuardEvaluator,
        state_machine: WorkflowStateMachine | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._guard_evaluator = guard_evaluator
        self._state_machine = state_machine or WorkflowStateMachine()
        self._clock = clock or (lambda: datetime.now(UTC))

    async def transition(
        self,
        *,
        job_id: UUID,
        event: WorkflowEvent,
        guard_context: dict[str, Any],
        reason: str,
        correlation_id: UUID,
        outbox_event_type: str,
        outbox_payload: dict[str, Any],
        outbox_headers: dict[str, Any] | None = None,
        hatchet_workflow_run_id: str | None = None,
        hatchet_task_run_id: str | None = None,
        task_group: TaskGroup | None = None,
        task_name: str | None = None,
        creator_key: str | None = None,
        provider_key: str | None = None,
        attempt: int = 1,
    ) -> TransitionDecision:
        if self._guard_evaluator is None:
            raise ValueError("an authoritative guard evaluator is required")
        if not reason:
            raise ValueError("reason must not be empty")
        if attempt < 1:
            raise ValueError("attempt must be positive")

        rejected: GuardRejected | None = None
        decision: TransitionDecision | None = None
        async with self._uow_factory() as uow:
            job = await uow.session.scalar(
                select(LocalizationJob)
                .where(LocalizationJob.id == job_id)
                .with_for_update()
            )
            if job is None:
                raise ProblemException(
                    status_code=404,
                    code="localization_job_not_found",
                    title="Localization job not found",
                    detail="The localization job does not exist.",
                )

            task_run, cached_decision = await self._task_run(
                session=uow.session,
                job=job,
                task_group=task_group,
                task_name=task_name,
                creator_key=creator_key,
                provider_key=provider_key,
                attempt=attempt,
                hatchet_workflow_run_id=hatchet_workflow_run_id,
                hatchet_task_run_id=hatchet_task_run_id,
            )
            if cached_decision is not None:
                return cached_decision
            if task_run is not None:
                uow.session.add(task_run)

            evaluation = await self._guard_evaluator.evaluate(
                uow,
                job,
                event,
                guard_context,
            )
            if evaluation.actor_type not in {"system", "employee", "creator"}:
                raise ValueError("authoritative guard returned an invalid actor type")
            actor_id = evaluation.actor_id.strip() if evaluation.actor_id is not None else ""
            if not actor_id:
                raise ValueError("authoritative guard must return an explicit actor identity")
            actor_type = evaluation.actor_type
            guard_result = evaluation.allowed
            guard_details = evaluation.details

            source = job.state
            prior_resumable_state = job.resumable_state
            try:
                decision = self._state_machine.transition(
                    job,
                    event,
                    guard_result=guard_result,
                    actor_type=actor_type,
                )
            except GuardRejected as exception:
                rejected = exception
                uow.session.add(
                    WorkflowTransition(
                        organization_id=job.organization_id,
                        job_id=job.id,
                        from_state=source,
                        to_state=source,
                        event=event,
                        actor_type=actor_type,
                        actor_id=actor_id,
                        guard_result=False,
                        guard_details=guard_details,
                        reason=reason,
                        correlation_id=correlation_id,
                        prior_resumable_state=prior_resumable_state,
                        hatchet_workflow_run_id=hatchet_workflow_run_id,
                        hatchet_task_run_id=hatchet_task_run_id,
                    )
                )
                if task_run is not None:
                    task_run.status = TaskRunStatus.FAILED
                    task_run.completed_at = self._clock()
                    task_run.error = exception.detail
            else:
                uow.session.add(
                    WorkflowTransition(
                        organization_id=job.organization_id,
                        job_id=job.id,
                        from_state=decision.from_state,
                        to_state=decision.to_state,
                        event=decision.event,
                        actor_type=actor_type,
                        actor_id=actor_id,
                        guard_result=decision.guard_result,
                        guard_details=guard_details,
                        reason=reason,
                        correlation_id=correlation_id,
                        prior_resumable_state=decision.prior_resumable_state,
                        hatchet_workflow_run_id=hatchet_workflow_run_id,
                        hatchet_task_run_id=hatchet_task_run_id,
                    )
                )
                headers = dict(outbox_headers or {})
                headers.setdefault("correlation_id", str(correlation_id))
                if hatchet_workflow_run_id is not None:
                    headers.setdefault("hatchet_workflow_run_id", hatchet_workflow_run_id)
                if hatchet_task_run_id is not None:
                    headers.setdefault("hatchet_task_run_id", hatchet_task_run_id)
                uow.session.add(
                    OutboxEvent(
                        organization_id=job.organization_id,
                        aggregate_type="localization_job",
                        aggregate_id=job.id,
                        event_type=outbox_event_type,
                        payload=outbox_payload,
                        headers=headers,
                    )
                )
                if task_run is not None:
                    task_run.status = TaskRunStatus.SUCCEEDED
                    task_run.completed_at = self._clock()

        if rejected is not None:
            raise rejected
        if decision is None:
            raise RuntimeError("workflow transition produced no decision")
        return decision

    async def dead_letter(
        self,
        *,
        job_id: UUID,
        task_name: str,
        task_group: TaskGroup,
        hatchet_workflow_run_id: str,
        hatchet_task_run_id: str | None,
        payload: dict[str, Any],
        error_type: str,
        error_message: str,
        correlation_id: UUID,
    ) -> DeadLetter:
        async with self._uow_factory() as uow:
            job = await uow.session.scalar(
                select(LocalizationJob)
                .where(LocalizationJob.id == job_id)
                .with_for_update()
            )
            if job is None:
                raise ProblemException(
                    status_code=404,
                    code="localization_job_not_found",
                    title="Localization job not found",
                    detail="The localization job does not exist.",
                )

            conditions = [
                TaskRun.job_id == job_id,
                TaskRun.task_name == task_name,
                TaskRun.task_group == task_group,
                TaskRun.hatchet_workflow_run_id == hatchet_workflow_run_id,
            ]
            if hatchet_task_run_id is not None:
                conditions.append(TaskRun.hatchet_task_run_id == hatchet_task_run_id)
            task_runs = list(
                await uow.session.scalars(
                    select(TaskRun)
                    .where(*conditions)
                    .order_by(TaskRun.created_at)
                    .limit(2)
                    .with_for_update()
                )
            )
            if len(task_runs) != 1:
                raise ProblemException(
                    status_code=409 if task_runs else 404,
                    code=(
                        "hatchet_task_run_ambiguous"
                        if task_runs
                        else "hatchet_task_run_not_found"
                    ),
                    title=(
                        "Hatchet task run is ambiguous"
                        if task_runs
                        else "Hatchet task run not found"
                    ),
                    detail=(
                        "The failed execution cannot be associated with exactly one "
                        "authoritative Oki task run."
                    ),
                )
            task_run = task_runs[0]
            bounded_error_type = error_type[:255] or "HatchetTaskFailure"
            bounded_error_message = error_message[:2_000]
            task_run.status = TaskRunStatus.DEAD_LETTERED
            task_run.completed_at = self._clock()
            task_run.error = bounded_error_message

            existing = await uow.session.scalar(
                select(DeadLetter)
                .where(DeadLetter.task_run_id == task_run.id)
                .with_for_update()
            )
            if existing is not None:
                return existing
            dead_letter = DeadLetter(
                organization_id=job.organization_id,
                job_id=job_id,
                task_run_id=task_run.id,
                task_name=task_name,
                payload=payload,
                error_type=bounded_error_type,
                error_message=bounded_error_message,
                attempts=task_run.attempt,
                correlation_id=correlation_id,
                hatchet_workflow_run_id=hatchet_workflow_run_id,
                hatchet_task_run_id=task_run.hatchet_task_run_id,
            )
            uow.session.add(dead_letter)
            return dead_letter

    async def _task_run(
        self,
        *,
        session: AsyncSession,
        job: LocalizationJob,
        task_group: TaskGroup | None,
        task_name: str | None,
        creator_key: str | None,
        provider_key: str | None,
        attempt: int,
        hatchet_workflow_run_id: str | None,
        hatchet_task_run_id: str | None,
    ) -> tuple[TaskRun | None, TransitionDecision | None]:
        registration_metadata = (task_group, task_name, creator_key)
        if all(value is None for value in registration_metadata):
            return None, None
        if any(value is None for value in registration_metadata):
            raise ValueError("Hatchet task registration metadata must be supplied together")
        if hatchet_workflow_run_id is None or hatchet_task_run_id is None:
            raise ValueError("Hatchet execution identifiers are required for task runs")

        existing = await session.scalar(
            select(TaskRun)
            .where(TaskRun.hatchet_task_run_id == hatchet_task_run_id)
            .with_for_update()
        )
        if existing is not None:
            if (
                existing.job_id != job.id
                or existing.task_group is not task_group
                or existing.task_name != task_name
                or existing.creator_key != creator_key
                or existing.hatchet_workflow_run_id != hatchet_workflow_run_id
            ):
                raise ProblemException(
                    status_code=409,
                    code="hatchet_task_run_conflict",
                    title="Hatchet task run conflict",
                    detail="The Hatchet task run identifier is bound to different Oki task metadata.",
                )
            if existing.status is TaskRunStatus.SUCCEEDED:
                transition = await session.scalar(
                    select(WorkflowTransition)
                    .where(
                        WorkflowTransition.hatchet_task_run_id == hatchet_task_run_id,
                        WorkflowTransition.guard_result.is_(True),
                    )
                    .order_by(WorkflowTransition.created_at.desc())
                    .limit(1)
                )
                if transition is None:
                    raise RuntimeError("succeeded task run has no authoritative transition")
                return existing, TransitionDecision(
                    from_state=transition.from_state,
                    to_state=transition.to_state,
                    event=transition.event,
                    guard_result=True,
                    prior_resumable_state=transition.prior_resumable_state,
                )
            existing.provider_key = provider_key
            existing.status = TaskRunStatus.RUNNING
            existing.attempt = max(attempt, existing.attempt)
            existing.started_at = self._clock()
            existing.completed_at = None
            existing.error = None
            return existing, None

        return TaskRun(
            organization_id=job.organization_id,
            job_id=job.id,
            task_name=task_name,
            task_group=task_group,
            provider_key=provider_key,
            creator_key=creator_key,
            status=TaskRunStatus.RUNNING,
            attempt=attempt,
            hatchet_workflow_run_id=hatchet_workflow_run_id,
            hatchet_task_run_id=hatchet_task_run_id,
            started_at=self._clock(),
        ), None
