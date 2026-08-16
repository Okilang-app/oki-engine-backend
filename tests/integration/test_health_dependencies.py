from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from oki.config import Settings
from oki.health import database_is_ready, seaweedfs_s3_is_ready, valkey_is_ready


@pytest.fixture
async def database_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(Settings(environment="test").database_url)
    try:
        yield engine
    finally:
        await engine.dispose()


async def test_database_readiness_reports_available_database(
    database_engine: AsyncEngine,
) -> None:
    assert await database_is_ready(database_engine) is True


async def test_database_readiness_reports_connection_failure() -> None:
    unavailable_engine = create_async_engine(
        "postgresql+asyncpg://oki:oki@127.0.0.1:1/oki",
        connect_args={"timeout": 0.1},
    )
    try:
        assert await database_is_ready(unavailable_engine) is False
    finally:
        await unavailable_engine.dispose()


async def test_valkey_readiness_reports_available_service() -> None:
    assert await valkey_is_ready(Settings(environment="test").valkey_url) is True


async def test_valkey_readiness_reports_connection_failure() -> None:
    assert await valkey_is_ready("valkey://127.0.0.1:1/0", timeout=0.1) is False


async def test_seaweedfs_s3_readiness_reports_available_service() -> None:
    assert (
        await seaweedfs_s3_is_ready(
            Settings(environment="test").s3_endpoint_url,
        )
        is True
    )


async def test_seaweedfs_s3_readiness_reports_connection_failure() -> None:
    assert await seaweedfs_s3_is_ready("http://127.0.0.1:1", timeout=0.1) is False
