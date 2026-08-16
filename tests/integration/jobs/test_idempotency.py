import asyncio
from collections.abc import AsyncIterator, Callable
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from oki.config import Settings
from oki.db.uow import UnitOfWork
from oki.jobs.idempotency import IdempotencyConflict, IdempotencyService


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(Settings(environment="test").database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture
async def organization_id(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[UUID]:
    organization_id = uuid4()
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "insert into organizations (id, slug, name) "
                "values (:id, :slug, 'Task 3 idempotency test')"
            ),
            {"id": organization_id, "slug": f"task-3-idempotency-{organization_id}"},
        )
    try:
        yield organization_id
    finally:
        async with session_factory.begin() as session:
            await session.execute(
                text("delete from organizations where id = :id"),
                {"id": organization_id},
            )


@pytest.fixture
def uow_factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> Callable[[], UnitOfWork]:
    return lambda: UnitOfWork(session_factory)


async def test_same_idempotency_key_returns_original_result(
    uow_factory: Callable[[], UnitOfWork],
    organization_id: UUID,
) -> None:
    service = IdempotencyService(uow_factory)
    calls = 0

    async def command(_uow: UnitOfWork) -> dict[str, str]:
        nonlocal calls
        calls += 1
        return {"job_id": "01900000-0000-7000-8000-000000000001"}

    first = await service.execute(
        organization_id,
        "POST:/api/jobs/analyze",
        "same",
        command,
    )
    second = await service.execute(
        organization_id,
        "POST:/api/jobs/analyze",
        "same",
        command,
    )

    assert first == second == {"job_id": "01900000-0000-7000-8000-000000000001"}
    assert calls == 1


async def test_idempotency_result_survives_service_instances(
    uow_factory: Callable[[], UnitOfWork],
    organization_id: UUID,
) -> None:
    calls = 0

    async def command(_uow: UnitOfWork) -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"attempt": calls}

    first = await IdempotencyService(uow_factory).execute(
        organization_id,
        "POST:/api/jobs",
        "persistent",
        command,
    )
    second = await IdempotencyService(uow_factory).execute(
        organization_id,
        "POST:/api/jobs",
        "persistent",
        command,
    )

    assert first == second == {"attempt": 1}
    assert calls == 1


async def test_concurrent_duplicate_executes_command_once(
    uow_factory: Callable[[], UnitOfWork],
    organization_id: UUID,
) -> None:
    service = IdempotencyService(uow_factory)
    calls = 0

    async def command(_uow: UnitOfWork) -> dict[str, int]:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return {"calls": calls}

    first, second = await asyncio.gather(
        service.execute(organization_id, "POST:/api/jobs", "concurrent", command),
        service.execute(organization_id, "POST:/api/jobs", "concurrent", command),
    )

    assert first == second == {"calls": 1}
    assert calls == 1


async def test_reusing_key_with_different_request_is_rejected(
    uow_factory: Callable[[], UnitOfWork],
    organization_id: UUID,
) -> None:
    service = IdempotencyService(uow_factory)

    async def command(_uow: UnitOfWork) -> dict[str, bool]:
        return {"ok": True}

    await service.execute(
        organization_id,
        "POST:/api/jobs",
        "request-conflict",
        command,
        request_body={"language": "es"},
    )

    with pytest.raises(IdempotencyConflict):
        await service.execute(
            organization_id,
            "POST:/api/jobs",
            "request-conflict",
            command,
            request_body={"language": "fr"},
        )


async def test_command_mutation_and_completed_record_commit_together(
    uow_factory: Callable[[], UnitOfWork],
    session_factory: async_sessionmaker[AsyncSession],
    organization_id: UUID,
) -> None:
    async def command(uow: UnitOfWork) -> dict[str, str]:
        await uow.session.execute(
            text("update organizations set name = 'atomic commit' where id = :id"),
            {"id": organization_id},
        )
        return {"name": "atomic commit"}

    result = await IdempotencyService(uow_factory).execute(
        organization_id,
        "PATCH:/api/organizations",
        "atomic-commit",
        command,
    )

    async with session_factory() as session:
        name = await session.scalar(
            text("select name from organizations where id = :id"),
            {"id": organization_id},
        )
        completed = await session.scalar(
            text(
                "select status from idempotency_records "
                "where organization_id = :id and idempotency_key = 'atomic-commit'"
            ),
            {"id": organization_id},
        )

    assert result == {"name": "atomic commit"}
    assert name == "atomic commit"
    assert completed == "completed"


async def test_command_mutation_and_idempotency_record_roll_back_together(
    uow_factory: Callable[[], UnitOfWork],
    session_factory: async_sessionmaker[AsyncSession],
    organization_id: UUID,
) -> None:
    async def command(uow: UnitOfWork) -> dict[str, str]:
        await uow.session.execute(
            text("update organizations set name = 'must roll back' where id = :id"),
            {"id": organization_id},
        )
        raise RuntimeError("command failed")

    with pytest.raises(RuntimeError, match="command failed"):
        await IdempotencyService(uow_factory).execute(
            organization_id,
            "PATCH:/api/organizations",
            "atomic-rollback",
            command,
        )

    async with session_factory() as session:
        name = await session.scalar(
            text("select name from organizations where id = :id"),
            {"id": organization_id},
        )
        record_count = await session.scalar(
            text(
                "select count(*) from idempotency_records "
                "where organization_id = :id and idempotency_key = 'atomic-rollback'"
            ),
            {"id": organization_id},
        )

    assert name == "Task 3 idempotency test"
    assert record_count == 0
