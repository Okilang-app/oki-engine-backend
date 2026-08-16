import importlib
from collections.abc import AsyncIterator, Callable
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from oki.config import Settings
from oki.api.errors import ProblemException
from oki.db.uow import UnitOfWork
from oki.jobs.enums import TaskGroup, TaskRunStatus, WorkflowEvent, WorkflowState
from oki.jobs.hatchet import (
    TASK_REGISTRATIONS,
    HatchetOutboxDispatcher,
    _failure_handler,
)
from oki.jobs.models import (
    DeadLetter,
    LocalizationJob,
    OutboxEvent,
    Project,
    TaskRun,
    WorkflowTransition,
)
from oki.jobs.outbox import OutboxPublisher
from oki.jobs.state_machine import GuardRejected
from oki.jobs.tasks import GuardEvaluation, HatchetTaskInput, WorkflowTaskRunner


class StaticGuardEvaluator:
    def __init__(
        self,
        *,
        allowed: bool = True,
        actor_type: str = "system",
        actor_id: str | None = "oki.test.guard",
        details: dict[str, Any] | None = None,
    ) -> None:
        self.evaluation = GuardEvaluation(
            allowed=allowed,
            actor_type=actor_type,
            actor_id=actor_id,
            details=details or {},
        )
        self.called_in_transaction = False
        self.context: dict[str, Any] | None = None

    async def evaluate(
        self,
        uow: UnitOfWork,
        job: LocalizationJob,
        event: WorkflowEvent,
        context: dict[str, Any],
    ) -> GuardEvaluation:
        self.called_in_transaction = uow.session.in_transaction()
        self.context = context
        return self.evaluation


class SequenceGuardEvaluator:
    def __init__(self, *evaluations: GuardEvaluation) -> None:
        self._evaluations = iter(evaluations)

    async def evaluate(
        self,
        uow: UnitOfWork,
        job: LocalizationJob,
        event: WorkflowEvent,
        context: dict[str, Any],
    ) -> GuardEvaluation:
        assert uow.session.in_transaction()
        return next(self._evaluations)


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(Settings(environment="test").database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture
def uow_factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> Callable[[], UnitOfWork]:
    return lambda: UnitOfWork(session_factory)


def make_runner(
    uow_factory: Callable[[], UnitOfWork],
    evaluator: StaticGuardEvaluator | SequenceGuardEvaluator | None = None,
) -> WorkflowTaskRunner:
    return WorkflowTaskRunner(
        uow_factory,
        guard_evaluator=evaluator or StaticGuardEvaluator(),
    )


@pytest.fixture
async def job_id(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[UUID]:
    organization_id = uuid4()
    project_id = uuid4()
    job_id = uuid4()
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "insert into organizations (id, slug, name) "
                "values (:id, :slug, 'Task 3 workflow test')"
            ),
            {"id": organization_id, "slug": f"task-3-workflow-{organization_id}"},
        )
        session.add(
            Project(
                id=project_id,
                organization_id=organization_id,
                name="Task 3 project",
                state=WorkflowState.CREATOR_LEAD,
            )
        )
        await session.flush()
        session.add(
            LocalizationJob(
                id=job_id,
                organization_id=organization_id,
                project_id=project_id,
                state=WorkflowState.CREATOR_LEAD,
            )
        )
    try:
        yield job_id
    finally:
        async with session_factory.begin() as session:
            await session.execute(
                text(
                    "delete from task_checkpoints where task_run_id in "
                    "(select id from task_runs where job_id = :job_id)"
                ),
                {"job_id": job_id},
            )
            for table_name in (
                "provider_usage",
                "dead_letters",
                "workflow_transitions",
                "task_runs",
            ):
                await session.execute(
                    text(f"delete from {table_name} where job_id = :job_id"),
                    {"job_id": job_id},
                )
            await session.execute(
                text("delete from outbox_events where aggregate_id = :job_id"),
                {"job_id": job_id},
            )
            await session.execute(
                text("delete from localization_jobs where id = :job_id"),
                {"job_id": job_id},
            )
            await session.execute(
                text("delete from projects where id = :project_id"),
                {"project_id": project_id},
            )
            await session.execute(
                text("delete from organizations where id = :organization_id"),
                {"organization_id": organization_id},
            )


async def test_authoritative_guard_runs_inside_locked_oki_transaction(
    uow_factory: Callable[[], UnitOfWork],
    session_factory: async_sessionmaker[AsyncSession],
    job_id: UUID,
) -> None:
    evaluator = StaticGuardEvaluator(details={"rights_precheck": "passed"})
    correlation_id = uuid4()
    runner = make_runner(uow_factory, evaluator)

    decision = await runner.transition(
        job_id=job_id,
        event=WorkflowEvent.REQUEST_RIGHTS,
        guard_context={"rights_evaluation_id": str(uuid4())},
        reason="rights review requested",
        correlation_id=correlation_id,
        hatchet_workflow_run_id="hatchet-workflow-1",
        hatchet_task_run_id="hatchet-task-1",
        outbox_event_type="workflow.rights_pending",
        outbox_payload={"job_id": str(job_id)},
    )

    async with session_factory() as session:
        job = await session.get(LocalizationJob, job_id)
        transition = await session.scalar(
            select(WorkflowTransition).where(WorkflowTransition.job_id == job_id)
        )
        outbox = await session.scalar(
            select(OutboxEvent).where(OutboxEvent.aggregate_id == job_id)
        )

    assert evaluator.called_in_transaction is True
    assert evaluator.context is not None and "rights_evaluation_id" in evaluator.context
    assert decision.to_state is WorkflowState.RIGHTS_PENDING
    assert job is not None and job.state is WorkflowState.RIGHTS_PENDING
    assert transition is not None
    assert transition.from_state is WorkflowState.CREATOR_LEAD
    assert transition.to_state is WorkflowState.RIGHTS_PENDING
    assert transition.event is WorkflowEvent.REQUEST_RIGHTS
    assert transition.actor_type == "system"
    assert transition.actor_id == "oki.test.guard"
    assert transition.guard_result is True
    assert transition.guard_details == {"rights_precheck": "passed"}
    assert transition.reason == "rights review requested"
    assert transition.correlation_id == correlation_id
    assert transition.prior_resumable_state is None
    assert transition.hatchet_workflow_run_id == "hatchet-workflow-1"
    assert transition.hatchet_task_run_id == "hatchet-task-1"
    assert outbox is not None and outbox.event_type == "workflow.rights_pending"


def test_hatchet_payload_cannot_supply_guard_truth_or_human_actor() -> None:
    with pytest.raises(ValidationError):
        HatchetTaskInput(
            dispatch_id=uuid4(),
            job_id=uuid4(),
            event=WorkflowEvent.PUBLISH_APPROVED,
            guard_context={},
            actor_type="employee",
            actor_id="forged-employee",
            guard_result=True,
            guard_details={"forged": True},
            reason="forged",
            correlation_id=uuid4(),
            creator_key="creator-1",
            outbox_event_type="workflow.published",
        )


@pytest.mark.parametrize("actor_type", ["system", "employee", "creator"])
async def test_transition_rejects_missing_authoritative_actor_identity(
    uow_factory: Callable[[], UnitOfWork],
    job_id: UUID,
    actor_type: str,
) -> None:
    evaluator = StaticGuardEvaluator(actor_type=actor_type, actor_id=None)

    with pytest.raises(ValueError, match="actor identity"):
        await make_runner(uow_factory, evaluator).transition(
            job_id=job_id,
            event=WorkflowEvent.REQUEST_RIGHTS,
            guard_context={},
            reason="identity required",
            correlation_id=uuid4(),
            outbox_event_type="must.not.publish",
            outbox_payload={},
        )


async def test_outbox_serialization_failure_rolls_back_domain_transition(
    uow_factory: Callable[[], UnitOfWork],
    session_factory: async_sessionmaker[AsyncSession],
    job_id: UUID,
) -> None:
    with pytest.raises(StatementError):
        await make_runner(uow_factory).transition(
            job_id=job_id,
            event=WorkflowEvent.REQUEST_RIGHTS,
            guard_context={},
            reason="must roll back",
            correlation_id=uuid4(),
            outbox_event_type="workflow.rights_pending",
            outbox_payload={"not_json": object()},
        )

    async with session_factory() as session:
        job = await session.get(LocalizationJob, job_id)
        transition_count = len(
            list(
                await session.scalars(
                    select(WorkflowTransition).where(WorkflowTransition.job_id == job_id)
                )
            )
        )
        outbox_count = len(
            list(
                await session.scalars(
                    select(OutboxEvent).where(OutboxEvent.aggregate_id == job_id)
                )
            )
        )

    assert job is not None and job.state is WorkflowState.CREATOR_LEAD
    assert transition_count == 0
    assert outbox_count == 0


async def test_failed_guard_is_recorded_without_state_or_outbox_advance(
    uow_factory: Callable[[], UnitOfWork],
    session_factory: async_sessionmaker[AsyncSession],
    job_id: UUID,
) -> None:
    evaluator = StaticGuardEvaluator(
        allowed=False,
        details={"reason_code": "rights_missing"},
    )

    with pytest.raises(GuardRejected):
        await make_runner(uow_factory, evaluator).transition(
            job_id=job_id,
            event=WorkflowEvent.REQUEST_RIGHTS,
            guard_context={"rights_evaluation_id": str(uuid4())},
            reason="rights missing",
            correlation_id=uuid4(),
            hatchet_workflow_run_id="hatchet-workflow-denied",
            hatchet_task_run_id="hatchet-task-denied",
            outbox_event_type="must.not.publish",
            outbox_payload={},
        )

    async with session_factory() as session:
        job = await session.get(LocalizationJob, job_id)
        transition = await session.scalar(
            select(WorkflowTransition).where(WorkflowTransition.job_id == job_id)
        )
        outbox = await session.scalar(
            select(OutboxEvent).where(OutboxEvent.aggregate_id == job_id)
        )

    assert job is not None and job.state is WorkflowState.CREATOR_LEAD
    assert transition is not None and transition.guard_result is False
    assert transition.actor_id == "oki.test.guard"
    assert transition.guard_details == {"reason_code": "rights_missing"}
    assert outbox is None


async def test_hatchet_retry_reuses_authoritative_task_run(
    uow_factory: Callable[[], UnitOfWork],
    session_factory: async_sessionmaker[AsyncSession],
    job_id: UUID,
) -> None:
    evaluator = SequenceGuardEvaluator(
        GuardEvaluation(False, "system", "oki.test.guard", {}),
        GuardEvaluation(True, "system", "oki.test.guard", {}),
    )
    runner = make_runner(uow_factory, evaluator)
    arguments = {
        "job_id": job_id,
        "event": WorkflowEvent.REQUEST_RIGHTS,
        "guard_context": {},
        "reason": "worker-start rights guard",
        "correlation_id": uuid4(),
        "hatchet_workflow_run_id": "hatchet-workflow-retry",
        "hatchet_task_run_id": "hatchet-task-retry",
        "task_group": TaskGroup.ANALYSIS,
        "task_name": "oki-analysis",
        "creator_key": "creator-1",
        "provider_key": "internal",
        "outbox_event_type": "workflow.rights_pending",
        "outbox_payload": {"job_id": str(job_id)},
    }

    with pytest.raises(GuardRejected):
        await runner.transition(attempt=1, **arguments)
    await runner.transition(attempt=2, **arguments)
    duplicate = await runner.transition(attempt=2, **arguments)

    async with session_factory() as session:
        task_runs = list(
            await session.scalars(select(TaskRun).where(TaskRun.job_id == job_id))
        )
        transitions = list(
            await session.scalars(
                select(WorkflowTransition).where(WorkflowTransition.job_id == job_id)
            )
        )
        outbox_events = list(
            await session.scalars(
                select(OutboxEvent).where(OutboxEvent.aggregate_id == job_id)
            )
        )

    assert len(task_runs) == 1
    assert task_runs[0].attempt == 2
    assert task_runs[0].status is TaskRunStatus.SUCCEEDED
    assert task_runs[0].error is None
    assert duplicate.to_state is WorkflowState.RIGHTS_PENDING
    assert len(transitions) == 2
    assert len(outbox_events) == 1


async def test_failure_hook_resolves_authoritative_task_run_and_actual_attempt(
    uow_factory: Callable[[], UnitOfWork],
    session_factory: async_sessionmaker[AsyncSession],
    job_id: UUID,
) -> None:
    runner = make_runner(
        uow_factory,
        StaticGuardEvaluator(allowed=False, details={"reason_code": "blocked"}),
    )
    correlation_id = uuid4()
    with pytest.raises(GuardRejected):
        await runner.transition(
            job_id=job_id,
            event=WorkflowEvent.REQUEST_RIGHTS,
            guard_context={},
            reason="blocked",
            correlation_id=correlation_id,
            outbox_event_type="workflow.rights_pending",
            outbox_payload={"job_id": str(job_id)},
            task_group=TaskGroup.ANALYSIS,
            task_name="oki-analysis",
            creator_key="creator-1",
            provider_key="internal",
            attempt=1,
            hatchet_workflow_run_id="hatchet-workflow-dead",
            hatchet_task_run_id="hatchet-execution-task",
        )

    class FailureHookContext:
        workflow_run_id = "hatchet-workflow-dead"
        task_run_id = "hatchet-failure-hook"
        task_run_errors: dict[str, str] = {}

        def get_task_run_error(self, task: object) -> None:
            return None

    class EmptyTaskError:
        task_run_external_id = ""
        exc_type = ""

        def __str__(self) -> str:
            return ""

    class EmptyFailureHookContext(FailureHookContext):
        def get_task_run_error(self, task: object) -> EmptyTaskError:
            return EmptyTaskError()

    input = HatchetTaskInput(
        dispatch_id=uuid4(),
        job_id=job_id,
        event=WorkflowEvent.REQUEST_RIGHTS,
        guard_context={},
        reason="blocked",
        correlation_id=correlation_id,
        creator_key="creator-1",
        provider_key="internal",
        outbox_event_type="workflow.rights_pending",
    )
    handler = _failure_handler(TASK_REGISTRATIONS[0], runner, object())
    for context in (FailureHookContext(), EmptyFailureHookContext()):
        await handler(input, context)  # type: ignore[arg-type]

    async with session_factory() as session:
        task_runs = list(
            await session.scalars(select(TaskRun).where(TaskRun.job_id == job_id))
        )
        dead_letters = list(
            await session.scalars(select(DeadLetter).where(DeadLetter.job_id == job_id))
        )

    assert len(task_runs) == 1
    assert task_runs[0].status is TaskRunStatus.DEAD_LETTERED
    assert task_runs[0].hatchet_task_run_id == "hatchet-execution-task"
    assert len(dead_letters) == 1
    assert dead_letters[0].task_run_id == task_runs[0].id
    assert dead_letters[0].hatchet_task_run_id == "hatchet-execution-task"
    assert dead_letters[0].hatchet_task_run_id != "hatchet-failure-hook"
    assert dead_letters[0].attempts == 1


async def test_failure_hook_without_authoritative_task_run_fails_closed(
    uow_factory: Callable[[], UnitOfWork],
    session_factory: async_sessionmaker[AsyncSession],
    job_id: UUID,
) -> None:
    class FailureHookContext:
        workflow_run_id = "hatchet-workflow-missing"
        task_run_id = "hatchet-failure-hook"
        task_run_errors: dict[str, str] = {}

        def get_task_run_error(self, task: object) -> None:
            return None

    input = HatchetTaskInput(
        dispatch_id=uuid4(),
        job_id=job_id,
        event=WorkflowEvent.REQUEST_RIGHTS,
        reason="failed before authoritative execution",
        correlation_id=uuid4(),
        creator_key="creator-1",
        provider_key="internal",
        outbox_event_type="workflow.rights_pending",
    )
    handler = _failure_handler(
        TASK_REGISTRATIONS[0],
        make_runner(uow_factory),
        object(),
    )

    with pytest.raises(ProblemException) as exc_info:
        await handler(input, FailureHookContext())  # type: ignore[arg-type]

    assert exc_info.value.code == "hatchet_task_run_not_found"
    async with session_factory() as session:
        assert await session.scalar(
            select(TaskRun).where(TaskRun.job_id == job_id)
        ) is None
        assert await session.scalar(
            select(DeadLetter).where(DeadLetter.job_id == job_id)
        ) is None


async def test_history_foreign_key_prevents_parent_job_deletion(
    uow_factory: Callable[[], UnitOfWork],
    session_factory: async_sessionmaker[AsyncSession],
    job_id: UUID,
) -> None:
    await make_runner(uow_factory).transition(
        job_id=job_id,
        event=WorkflowEvent.REQUEST_RIGHTS,
        guard_context={},
        reason="retain history",
        correlation_id=uuid4(),
        outbox_event_type="workflow.rights_pending",
        outbox_payload={},
    )

    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                text("delete from localization_jobs where id = :job_id"),
                {"job_id": job_id},
            )
        await session.rollback()

    async with session_factory() as session:
        assert await session.get(LocalizationJob, job_id) is not None
        assert await session.scalar(
            select(WorkflowTransition.id).where(WorkflowTransition.job_id == job_id)
        ) is not None


@pytest.mark.parametrize("table_name", ["projects", "localization_jobs"])
@pytest.mark.parametrize(
    ("state", "resumable_state"),
    [
        ("BLOCKED", None),
        ("FAILED", "ARCHIVED"),
        ("RIGHTS_PENDING", "CREATOR_LEAD"),
    ],
)
async def test_database_enforces_resumable_state_invariant(
    session_factory: async_sessionmaker[AsyncSession],
    job_id: UUID,
    table_name: str,
    state: str,
    resumable_state: str | None,
) -> None:
    async with session_factory() as session:
        if table_name == "projects":
            record_id = await session.scalar(
                select(LocalizationJob.project_id).where(LocalizationJob.id == job_id)
            )
        else:
            record_id = job_id
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    f"update {table_name} set state = :state, resumable_state = :resumable "
                    "where id = :record_id"
                ),
                {"state": state, "resumable": resumable_state, "record_id": record_id},
            )
        await session.rollback()


async def test_outbox_publisher_claims_and_marks_matching_events(
    uow_factory: Callable[[], UnitOfWork],
    session_factory: async_sessionmaker[AsyncSession],
    job_id: UUID,
) -> None:
    await make_runner(uow_factory).transition(
        job_id=job_id,
        event=WorkflowEvent.REQUEST_RIGHTS,
        guard_context={},
        reason="publish me",
        correlation_id=uuid4(),
        outbox_event_type="workflow.rights_pending",
        outbox_payload={"job_id": str(job_id)},
    )
    published: list[tuple[str, dict[str, Any]]] = []

    async def publish(event: OutboxEvent) -> None:
        published.append((event.event_type, event.payload))

    result = await OutboxPublisher(
        uow_factory,
        publish,
        event_types={"workflow.rights_pending"},
    ).publish_batch(limit=10)

    async with session_factory() as session:
        event = await session.scalar(
            select(OutboxEvent).where(OutboxEvent.aggregate_id == job_id)
        )

    assert result.claimed == 1
    assert result.published == 1
    assert result.failed == 0
    assert published == [("workflow.rights_pending", {"job_id": str(job_id)})]
    assert event is not None and event.published_at is not None
    assert event.attempts == 1
    assert event.last_error is None


async def test_hatchet_dispatch_is_nonblocking_and_idempotent_by_outbox_id() -> None:
    class FakeWorkflow:
        def __init__(self) -> None:
            self.calls: list[tuple[HatchetTaskInput, Any]] = []

        async def aio_run_no_wait(self, input: HatchetTaskInput, options: Any) -> object:
            self.calls.append((input, options))
            return object()

    workflow = FakeWorkflow()
    dispatcher = HatchetOutboxDispatcher({TaskGroup.ANALYSIS: workflow})
    event_id = uuid4()
    event = OutboxEvent(
        id=event_id,
        organization_id=uuid4(),
        aggregate_type="localization_job",
        aggregate_id=uuid4(),
        event_type="hatchet.task.requested",
        payload={
            "job_id": str(uuid4()),
            "event": WorkflowEvent.START_ANALYSIS.value,
            "guard_context": {"rights_evaluation_id": str(uuid4())},
            "reason": "analysis requested",
            "correlation_id": str(uuid4()),
            "creator_key": "creator-1",
            "provider_key": "internal",
            "outbox_event_type": "workflow.analysis_running",
            "outbox_payload": {},
        },
        headers={"task_group": TaskGroup.ANALYSIS.value},
    )

    await dispatcher(event)

    assert len(workflow.calls) == 1
    task_input, options = workflow.calls[0]
    assert task_input.dispatch_id == event_id
    assert options.key == str(event_id)


def test_hatchet_registration_is_credential_free_and_covers_required_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HATCHET_CLIENT_TOKEN", raising=False)

    worker_module = importlib.import_module("oki.worker")

    assert callable(worker_module.main)
    assert callable(worker_module.run_outbox_dispatcher)
    assert {registration.group for registration in TASK_REGISTRATIONS} == set(TaskGroup)
    for registration in TASK_REGISTRATIONS:
        assert registration.concurrency_keys == ("group", "provider", "creator")
        assert registration.rate_limit_key == "provider"
