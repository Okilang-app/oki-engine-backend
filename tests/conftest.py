from collections.abc import Iterator

import pytest

from oki.config import Settings, get_settings


@pytest.fixture(autouse=True)
def reset_settings_cache() -> Iterator[None]:
    """Keep environment-backed settings isolated between tests."""

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()

@pytest.fixture
def settings():
    return Settings(environment="test", database_url="postgresql+asyncpg://oki@localhost:5432/oki_test")
