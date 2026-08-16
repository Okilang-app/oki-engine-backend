import asyncio
from collections.abc import Sequence
import sys
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from oki.config import Settings
from oki.db.uow import UnitOfWork
from oki.jobs.enums import WorkflowEvent
from oki.jobs.hatchet import (
    HATCHET_OUTBOX_EVENT_TYPE,
    HatchetOutboxDispatcher,
    create_hatchet_client,
    register_hatchet_tasks,
    workflows_by_group,
)
from oki.jobs.models import LocalizationJob
from oki.jobs.outbox import OutboxPublisher
from oki.jobs.tasks import GuardEvaluation, WorkflowTaskRunner


class FailClosedGuardEvaluator:
    """Stage 0 worker guard until the rights module supplies its evaluator."""

    async def evaluate(
        self,
        uow: UnitOfWork,
        job: LocalizationJob,
        event: WorkflowEvent,
        context: dict[str, Any],
    ) -> GuardEvaluation:
        return GuardEvaluation(
            allowed=False,
            actor_type="system",
            actor_id="oki.worker.guard",
            details={"reason_code": "authoritative_guard_not_configured"},
        )


def _runtime() -> tuple[AsyncEngine, WorkflowTaskRunner, Any, tuple[Any, ...]]:
    settings = Settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    runner = WorkflowTaskRunner(
        lambda: UnitOfWork(session_factory),
        guard_evaluator=FailClosedGuardEvaluator(),
    )
    hatchet = create_hatchet_client()
    workflows = register_hatchet_tasks(hatchet, runner)
    return engine, runner, hatchet, workflows


async def run_outbox_dispatcher(
    publisher: OutboxPublisher,
    *,
    poll_interval_seconds: float = 0.5,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Continuously schedule pending Hatchet outbox rows without waiting for runs."""

    if poll_interval_seconds <= 0:
        raise ValueError("poll_interval_seconds must be positive")
    while stop_event is None or not stop_event.is_set():
        result = await publisher.publish_batch()
        if result.claimed != 0:
            continue
        if stop_event is None:
            await asyncio.sleep(poll_interval_seconds)
            continue
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_interval_seconds)
        except TimeoutError:
            pass


async def _run_outbox_process() -> None:
    engine, runner, hatchet, workflows = _runtime()
    del runner, hatchet
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    dispatcher = HatchetOutboxDispatcher(workflows_by_group(workflows))
    publisher = OutboxPublisher(
        lambda: UnitOfWork(session_factory),
        dispatcher,
        event_types={HATCHET_OUTBOX_EVENT_TYPE},
    )
    try:
        await run_outbox_dispatcher(publisher)
    finally:
        await engine.dispose()


def _run_worker_process() -> None:
    engine, runner, hatchet, workflows = _runtime()
    del runner
    worker = hatchet.worker("oki-worker", slots=16, workflows=list(workflows))
    try:
        worker.start()
    finally:
        asyncio.run(engine.dispose())


def main(arguments: Sequence[str] | None = None) -> None:
    """Run the Hatchet worker or the transactional outbox dispatcher."""

    argv = list(arguments) if arguments is not None else sys.argv[1:]
    process = argv[0] if argv else "worker"
    if process == "worker":
        _run_worker_process()
        return
    if process == "outbox":
        asyncio.run(_run_outbox_process())
        return
    raise SystemExit("usage: python -m oki.worker [worker|outbox]")


if __name__ == "__main__":
    main()
