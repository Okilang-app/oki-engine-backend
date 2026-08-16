import os
import subprocess
import sys
from collections.abc import AsyncIterator, Callable
from datetime import timezone
from uuid import uuid4

import pytest
from sqlalchemy import String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.orm.exc import StaleDataError

from oki.config import Settings
from oki.db.mixins import TimestampMixin, VersionMixin
from oki.db.uow import UnitOfWork

FOUNDATION_TABLES = {
    "users",
    "organizations",
    "memberships",
    "roles",
    "permissions",
    "role_permissions",
    "idempotency_records",
    "outbox_events",
    "audit_events",
    "security_events",
}


class IntegrationBase(DeclarativeBase):
    pass


class VersionedRecord(TimestampMixin, VersionMixin, IntegrationBase):
    __tablename__ = "integration_versioned_records"

    id: Mapped[object] = mapped_column(UUID(as_uuid=True), primary_key=True)
    value: Mapped[str] = mapped_column(String(100), nullable=False)


def run_alembic(*arguments: str, database_url: str | None = None) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    if database_url is not None:
        environment["OKI_DATABASE_URL"] = database_url
    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        check=False,
        capture_output=True,
        cwd=os.getcwd(),
        env=environment,
        text=True,
    )


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(Settings(environment="test").database_url)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def session_factory(
    engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    async with engine.begin() as connection:
        await connection.run_sync(IntegrationBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(IntegrationBase.metadata.drop_all)


@pytest.fixture
def uow_factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> Callable[[], UnitOfWork]:
    return lambda: UnitOfWork(session_factory)


async def test_postgresql_18_is_the_test_database(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        version_number = int(await connection.scalar(text("show server_version_num")))

    assert version_number // 10_000 == 18


async def test_foundation_migration_creates_required_tables(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        table_names = set(
            await connection.scalars(
                text("select tablename from pg_tables where schemaname = 'public'")
            )
        )

    assert FOUNDATION_TABLES <= table_names


async def test_foundation_ids_default_to_uuid7(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        generated_id = await connection.scalar(
            text(
                """
                insert into organizations (slug, name)
                values ('uuid7-default-check', 'UUIDv7 default check')
                returning id
                """
            )
        )
        await connection.execute(
            text("delete from organizations where id = :organization_id"),
            {"organization_id": generated_id},
        )

    assert generated_id is not None
    assert generated_id.version == 7


@pytest.mark.parametrize("table_name", ["audit_events", "security_events"])
async def test_application_role_cannot_mutate_append_only_events(
    engine: AsyncEngine,
    table_name: str,
) -> None:
    async with engine.connect() as connection:
        privileges = {
            privilege: bool(
                await connection.scalar(
                    text("select has_table_privilege('oki_app', :table_name, :privilege)"),
                    {"table_name": f"public.{table_name}", "privilege": privilege},
                )
            )
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE")
        }

    assert privileges == {
        "SELECT": True,
        "INSERT": True,
        "UPDATE": False,
        "DELETE": False,
    }


async def test_unit_of_work_commits_on_success(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    record_id = uuid4()
    async with uow_factory() as uow:
        uow.session.add(VersionedRecord(id=record_id, value="committed"))

    async with uow_factory() as uow:
        record = await uow.session.get(VersionedRecord, record_id)

    assert record is not None
    assert record.value == "committed"


async def test_unit_of_work_rolls_back_on_error(
    uow_factory: Callable[[], UnitOfWork],
) -> None:
    with pytest.raises(RuntimeError, match="stop"):
        async with uow_factory() as uow:
            await uow.session.execute(text("create temporary table should_rollback(id int)"))
            raise RuntimeError("stop")

    async with uow_factory() as uow:
        exists = await uow.session.scalar(
            text("select to_regclass('pg_temp.should_rollback')")
        )

    assert exists is None


async def test_mixins_manage_utc_timestamps_and_optimistic_versions(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    record_id = uuid4()
    async with session_factory() as session:
        record = VersionedRecord(id=record_id, value="initial")
        session.add(record)
        await session.commit()

        assert record.created_at.tzinfo is not None
        assert record.created_at.astimezone(timezone.utc) == record.created_at
        assert record.updated_at.tzinfo is not None
        assert record.version == 1

    async with session_factory() as first_session, session_factory() as second_session:
        first = await first_session.get(VersionedRecord, record_id)
        stale = await second_session.get(VersionedRecord, record_id)
        assert first is not None
        assert stale is not None

        first.value = "first update"
        await first_session.commit()
        assert first.version == 2
        assert first.updated_at >= first.created_at

        stale.value = "stale update"
        with pytest.raises(StaleDataError):
            await second_session.commit()


async def test_alembic_accepts_percent_encoded_database_url(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text("create role oki_percent_test login password 'pass@word'")
        )
        await connection.execute(text("grant connect on database oki to oki_percent_test"))
        await connection.execute(text("grant usage on schema public to oki_percent_test"))
        await connection.execute(
            text("grant select on table alembic_version to oki_percent_test")
        )

    database_url = make_url(Settings(environment="test").database_url).set(
        username="oki_percent_test",
        password="pass@word",
    )
    encoded_url = database_url.render_as_string(hide_password=False)
    assert "%40" in encoded_url

    try:
        result = run_alembic("current", database_url=encoded_url)
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text("revoke all privileges on table alembic_version from oki_percent_test")
            )
            await connection.execute(
                text("revoke all privileges on schema public from oki_percent_test")
            )
            await connection.execute(
                text("revoke all privileges on database oki from oki_percent_test")
            )
            await connection.execute(text("drop role oki_percent_test"))


async def test_migration_reverses_owned_role_state_without_destroying_preexisting_role(
    engine: AsyncEngine,
) -> None:
    database_url = Settings(environment="test").database_url

    async def role_exists() -> bool:
        async with engine.connect() as connection:
            return bool(
                await connection.scalar(
                    text("select exists(select 1 from pg_roles where rolname = 'oki_app')")
                )
            )

    async def schema_privileges() -> tuple[bool, bool]:
        async with engine.connect() as connection:
            usage = bool(
                await connection.scalar(
                    text("select has_schema_privilege('oki_app', 'public', 'USAGE')")
                )
            )
            create = bool(
                await connection.scalar(
                    text("select has_schema_privilege('oki_app', 'public', 'CREATE')")
                )
            )
        return usage, create

    try:
        downgrade = run_alembic("downgrade", "base", database_url=database_url)
        assert downgrade.returncode == 0, downgrade.stdout + downgrade.stderr

        async with engine.begin() as connection:
            await connection.execute(text("revoke all privileges on schema public from oki_app"))
            await connection.execute(text("drop role oki_app"))

        upgrade_without_role = run_alembic("upgrade", "head", database_url=database_url)
        assert upgrade_without_role.returncode == 0, (
            upgrade_without_role.stdout + upgrade_without_role.stderr
        )
        downgrade_without_role = run_alembic("downgrade", "base", database_url=database_url)
        assert downgrade_without_role.returncode == 0, (
            downgrade_without_role.stdout + downgrade_without_role.stderr
        )
        assert await role_exists() is False

        async with engine.begin() as connection:
            await connection.execute(text("create role oki_app nologin"))
            await connection.execute(text("grant usage on schema public to oki_app"))
        privileges_before = await schema_privileges()

        upgrade_with_role = run_alembic("upgrade", "head", database_url=database_url)
        assert upgrade_with_role.returncode == 0, (
            upgrade_with_role.stdout + upgrade_with_role.stderr
        )
        downgrade_with_role = run_alembic("downgrade", "base", database_url=database_url)
        assert downgrade_with_role.returncode == 0, (
            downgrade_with_role.stdout + downgrade_with_role.stderr
        )

        assert await role_exists() is True
        assert await schema_privileges() == privileges_before
    finally:
        if not await role_exists():
            async with engine.begin() as connection:
                await connection.execute(text("create role oki_app nologin"))
                await connection.execute(text("grant usage on schema public to oki_app"))
        restore = run_alembic("upgrade", "head", database_url=database_url)
        assert restore.returncode == 0, restore.stdout + restore.stderr
