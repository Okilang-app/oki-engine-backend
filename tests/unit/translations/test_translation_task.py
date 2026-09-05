"""Unit tests for translation_execution_task — mocked at the provider level."""
from unittest.mock import AsyncMock, patch
from uuid import uuid4


from oki.translations.tasks import translation_execution_task


async def test_returns_not_found_when_translation_missing(monkeypatch) -> None:
    async def _fake_uow(*_a, **_kw):
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
        return _FakeUOW()

    with (
        patch("oki.translations.tasks.create_async_engine"),
        patch("oki.translations.tasks.async_sessionmaker"),
        patch("oki.translations.tasks.UnitOfWork", side_effect=_fake_uow),
    ):
        result = await translation_execution_task(
            translation_id=uuid4(),
            job_id=uuid4(),
            asset_id=uuid4(),
            source_language="en",
            target_language="es",
        )

    assert result["status"] == "not_found"


async def test_falls_back_gracefully_without_openai(monkeypatch) -> None:
    """When OpenAI is not configured the task uses bracket placeholder text."""
    from unittest.mock import MagicMock
    from decimal import Decimal
    from uuid import uuid4 as _uuid4

    org_id = _uuid4()
    job_id = _uuid4()
    translation_id = _uuid4()

    fake_seg = MagicMock()
    fake_seg.id = _uuid4()
    fake_seg.text = "Hello world"
    fake_seg.start_time = Decimal("0.0")
    fake_seg.end_time = Decimal("3.0")
    fake_seg.organization_id = org_id

    fake_translation = MagicMock()
    fake_translation.id = translation_id

    call_count = 0

    class _FakeScalars:
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
        patch("oki.translations.tasks.create_async_engine"),
        patch("oki.translations.tasks.async_sessionmaker"),
        patch("oki.translations.tasks.UnitOfWork", return_value=_FakeUOW()),
        patch("oki.translations.tasks.Settings") as mock_settings,
    ):
        mock_settings.return_value.openai_api_key = None
        mock_settings.return_value.azure_openai_endpoint = None
        mock_settings.return_value.database_url = "postgresql+asyncpg://fake/fake"

        result = await translation_execution_task(
            translation_id=translation_id,
            job_id=job_id,
            asset_id=_uuid4(),
            source_language="en",
            target_language="es",
        )

    assert result["task"] == "translation_execution"
