"""Unit tests for TranslationQaService GPT-based scoring."""
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4


from oki.translations.enums import QaDimension
from oki.translations.service import TranslationQaService


async def test_returns_fallback_when_no_client() -> None:
    qa = TranslationQaService()
    with patch("oki.providers.factory.create_openai_client", return_value=None):
        scores = await qa.evaluate(uuid4(), [{"source_text": "Hi", "translated_text": "Hola"}])
    assert set(scores) == set(QaDimension)
    assert all(s == 70 for s in scores.values())


async def test_returns_fallback_for_empty_segments() -> None:
    qa = TranslationQaService()
    scores = await qa.evaluate(uuid4(), [])
    assert all(s == 70 for s in scores.values())


async def test_returns_gpt_scores_when_client_available() -> None:
    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = (
        '{"accuracy": 88, "fluency": 92, "terminology": 80, '
        '"style": 75, "locale": 70, "format": 85, "safety": 95}'
    )
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

    qa = TranslationQaService()
    with patch("oki.providers.factory.create_openai_client", return_value=mock_client):
        scores = await qa.evaluate(
            uuid4(),
            [{"source_text": "Hello", "translated_text": "Hola"}],
        )

    assert scores[QaDimension.ACCURACY] == 88
    assert scores[QaDimension.FLUENCY] == 92
    assert scores[QaDimension.SAFETY] == 95
    assert all(0 <= v <= 100 for v in scores.values())


async def test_clamps_out_of_range_scores() -> None:
    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = (
        '{"accuracy": 150, "fluency": -5, "terminology": 80, '
        '"style": 75, "locale": 70, "format": 85, "safety": 95}'
    )
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

    qa = TranslationQaService()
    with patch("oki.providers.factory.create_openai_client", return_value=mock_client):
        scores = await qa.evaluate(
            uuid4(),
            [{"source_text": "Hi", "translated_text": "Hola"}],
        )

    assert scores[QaDimension.ACCURACY] == 100
    assert scores[QaDimension.FLUENCY] == 0


async def test_falls_back_when_gpt_raises() -> None:
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("API error"))

    qa = TranslationQaService()
    with patch("oki.providers.factory.create_openai_client", return_value=mock_client):
        scores = await qa.evaluate(
            uuid4(),
            [{"source_text": "Hi", "translated_text": "Hola"}],
        )

    assert all(s == 70 for s in scores.values())
