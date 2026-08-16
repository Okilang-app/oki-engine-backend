from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from hatchet_sdk import (
    ConcurrencyExpression,
    ConcurrencyLimitStrategy,
    Context,
    Hatchet,
    IdempotencyCollisionError,
    NonRetryableException,
    TTLBasedIdempotencyConfig,
)
from hatchet_sdk.rate_limit import RateLimit
from hatchet_sdk.types.trigger import TriggerWorkflowOptions

from oki.api.errors import ProblemException
from oki.jobs.enums import TaskGroup
from oki.jobs.models import OutboxEvent
from oki.jobs.tasks import HatchetTaskInput, WorkflowTaskRunner

HATCHET_OUTBOX_EVENT_TYPE = "hatchet.task.requested"


@dataclass(frozen=True, slots=True)
class TaskRegistration:
    name: str
    group: TaskGroup
    max_group_runs: int
    retries: int = 3
    concurrency_keys: tuple[str, ...] = ("group", "provider", "creator")
    rate_limit_key: str = "provider"


TASK_REGISTRATIONS = (
    TaskRegistration("oki-analysis", TaskGroup.ANALYSIS, 4),
    TaskRegistration("oki-translation", TaskGroup.TRANSLATION, 8),
    TaskRegistration("oki-dubbing", TaskGroup.DUBBING, 2),
    TaskRegistration("oki-audio", TaskGroup.AUDIO, 4),
    TaskRegistration("oki-render", TaskGroup.RENDER, 2),
    TaskRegistration("oki-shorts", TaskGroup.SHORTS, 4),
    TaskRegistration("oki-publishing", TaskGroup.PUBLISHING, 2),
    TaskRegistration("oki-analytics", TaskGroup.ANALYTICS, 8),
    TaskRegistration("oki-notifications", TaskGroup.NOTIFICATIONS, 16),
)


class HatchetOutboxDispatcher:
    """Trigger Hatchet without waiting, using the Oki outbox ID as the run key."""

    def __init__(self, workflows: Mapping[TaskGroup, Any]) -> None:
        self._workflows = workflows

    async def __call__(self, event: OutboxEvent) -> None:
        if event.event_type != HATCHET_OUTBOX_EVENT_TYPE:
            raise ValueError(f"unsupported Hatchet outbox event type: {event.event_type}")
        try:
            group = TaskGroup(str(event.headers["task_group"]))
        except (KeyError, ValueError) as exception:
            raise ValueError("Hatchet outbox event requires a valid task_group header") from exception
        workflow = self._workflows.get(group)
        if workflow is None:
            raise ValueError(f"no Hatchet workflow registered for task group {group.value}")

        payload = dict(event.payload)
        payload["dispatch_id"] = event.id
        task_input = HatchetTaskInput.model_validate(payload)
        try:
            await workflow.aio_run_no_wait(
                input=task_input,
                options=TriggerWorkflowOptions(key=str(event.id)),
            )
        except IdempotencyCollisionError:
            return


def create_hatchet_client() -> Hatchet:
    """Construct the official client only when a configured process starts."""

    return Hatchet()


def register_hatchet_tasks(
    hatchet: Hatchet,
    runner: WorkflowTaskRunner,
) -> tuple[Any, ...]:
    """Register guarded workflows and terminal failure handlers for every group."""

    workflows: list[Any] = []
    for registration in TASK_REGISTRATIONS:
        workflow = hatchet.workflow(
            name=registration.name,
            input_validator=HatchetTaskInput,
            concurrency=[
                ConcurrencyExpression(
                    expression=f'"group:{registration.group.value}"',
                    max_runs=registration.max_group_runs,
                    limit_strategy=ConcurrencyLimitStrategy.GROUP_ROUND_ROBIN,
                ),
                ConcurrencyExpression(
                    expression='"provider:"+input.provider_key',
                    max_runs=registration.max_group_runs,
                    limit_strategy=ConcurrencyLimitStrategy.GROUP_ROUND_ROBIN,
                ),
                ConcurrencyExpression(
                    expression='"creator:"+input.creator_key',
                    max_runs=1,
                    limit_strategy=ConcurrencyLimitStrategy.GROUP_ROUND_ROBIN,
                ),
            ],
            idempotency=TTLBasedIdempotencyConfig(
                key_expression="input.dispatch_id",
                ttl=timedelta(days=7),
            ),
        )
        execution_task = workflow.task(
            name=f"{registration.name}-execute",
            rate_limits=[
                RateLimit(
                    dynamic_key='"provider:"+input.provider_key',
                    units="input.provider_units",
                    limit="input.provider_limit",
                )
            ],
            retries=registration.retries,
        )(_task_handler(registration, runner))
        workflow.on_failure_task(name=f"{registration.name}-dead-letter")(
            _failure_handler(registration, runner, execution_task)
        )
        workflows.append(workflow)
    return tuple(workflows)


def workflows_by_group(workflows: tuple[Any, ...]) -> dict[TaskGroup, Any]:
    if len(workflows) != len(TASK_REGISTRATIONS):
        raise ValueError("Hatchet workflow registration count does not match task groups")
    return {
        registration.group: workflow
        for registration, workflow in zip(TASK_REGISTRATIONS, workflows, strict=True)
    }


def _task_handler(
    registration: TaskRegistration,
    runner: WorkflowTaskRunner,
) -> Callable[[HatchetTaskInput, Context], Any]:
    async def execute(input: HatchetTaskInput, context: Context) -> dict[str, str]:
        try:
            decision = await runner.transition(
                job_id=input.job_id,
                event=input.event,
                guard_context=input.guard_context,
                reason=input.reason,
                correlation_id=input.correlation_id,
                outbox_event_type=input.outbox_event_type,
                outbox_payload=input.outbox_payload,
                outbox_headers=input.outbox_headers,
                hatchet_workflow_run_id=context.workflow_run_id,
                hatchet_task_run_id=context.task_run_id,
                task_group=registration.group,
                task_name=registration.name,
                creator_key=input.creator_key,
                provider_key=input.provider_key,
                attempt=context.attempt_number,
            )
        except ProblemException as exception:
            raise NonRetryableException(exception.detail) from exception
        return {
            "job_id": str(input.job_id),
            "state": decision.to_state.value,
            "transition": decision.event.value,
        }

    execute.__name__ = f"{registration.name.replace('-', '_')}_execute"
    return execute


def _failure_handler(
    registration: TaskRegistration,
    runner: WorkflowTaskRunner,
    execution_task: Any,
) -> Callable[[HatchetTaskInput, Context], Any]:
    async def dead_letter(input: HatchetTaskInput, context: Context) -> dict[str, str]:
        task_error = context.get_task_run_error(execution_task)
        errors = context.task_run_errors
        error_message = (
            str(task_error)
            if task_error is not None
            else "; ".join(
                f"{task_name}: {message}" for task_name, message in sorted(errors.items())
            )
        ) or "Hatchet workflow failed without task error details"
        failed_task_run_id = (
            (task_error.task_run_external_id or None)
            if task_error is not None
            else None
        )
        await runner.dead_letter(
            job_id=input.job_id,
            task_name=registration.name,
            task_group=registration.group,
            hatchet_workflow_run_id=context.workflow_run_id,
            hatchet_task_run_id=failed_task_run_id,
            payload=input.model_dump(mode="json"),
            error_type=task_error.exc_type if task_error is not None else "HatchetTaskFailure",
            error_message=error_message,
            correlation_id=input.correlation_id,
        )
        return {"job_id": str(input.job_id), "status": "dead_lettered"}

    dead_letter.__name__ = f"{registration.name.replace('-', '_')}_dead_letter"
    return dead_letter
