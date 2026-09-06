"""Unit tests for translation_execution_task — mocked at the provider level."""
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4


from oki.translations.tasks import translation_execution_task


def _make_engine_mock():
    engine = MagicMock()
    engine.dispose = AsyncMock()
    return engine


async def test_returns_not_found_when_translation_missing() -> None:
    class _FakeSession:
        async def get(self, *a, **kw):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

    class _FakeUOW:
        session = _FakeSession()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

    with (
        patch("oki.translations.tasks.create_async_engine", return_value=_make_engine_mock()),
        patch("oki.translations.tasks.async_sessionmaker"),
        patch("oki.translations.tasks.UnitOfWork", return_value=_FakeUOW()),
    ):
        result = await translation_execution_task(
            translation_id=uuid4(),
            job_id=uuid4(),
            asset_id=uuid4(),
            source_language="en",
            target_language="es",
        )

    assert result["status"] == "not_found"


async def test_falls_back_gracefully_without_openai() -> None:
    """When OpenAI is not configured the task uses bracket placeholder text."""
    org_id = uuid4()
    job_id = uuid4()
    translation_id = uuid4()

    fake_seg = MagicMock()
    fake_seg.id = uuid4()
    fake_seg.text = "Hello world"
    fake_seg.start_time = Decimal("0.0")
    fake_seg.end_time = Decimal("3.0")
    fake_seg.organization_id = org_id

    fake_translation = MagicMock()
    fake_translation.id = translation_id

    class _FakeScalars:
        def __iter__(self):
            return iter([fake_seg])

        def __aiter__(self):
            return iter([fake_seg])

    class _FakeSession:
        async def get(self, model, pk):
            return fake_translation

        async def scalars(self, *a, **kw):
            return _FakeScalars()

        async def execute(self, *a, **kw):
            pass

        async def flush(self):
            pass

        def add(self, *a):
            pass

    class _FakeUOW:
        session = _FakeSession()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

    with (
        patch("oki.translations.tasks.create_async_engine", return_value=_make_engine_mock()),
        patch("oki.translations.tasks.async_sessionmaker"),
        patch("oki.translations.tasks.UnitOfWork", return_value=_FakeUOW()),
        patch("oki.translations.tasks.Settings") as mock_settings,
        patch("oki.providers.openai_translation.create_openai_client", return_value=None),
    ):
        mock_settings.return_value.openai_api_key = None
        mock_settings.return_value.azure_openai_endpoint = None
        mock_settings.return_value.database_url = "postgresql+asyncpg://fake/fake"

        result = await translation_execution_task(
            translation_id=translation_id,
            job_id=job_id,
            asset_id=uuid4(),
            source_language="en",
            target_language="es",
        )

    assert result["task"] == "translation_execution"
