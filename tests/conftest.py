from collections.abc import Iterator

import pytest

from oki.config import get_settings


@pytest.fixture(autouse=True)
def reset_settings_cache() -> Iterator[None]:
    """Keep environment-backed settings isolated between tests."""

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
