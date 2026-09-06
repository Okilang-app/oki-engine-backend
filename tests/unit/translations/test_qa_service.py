"""Unit tests for TranslationQaService GPT-based scoring (SOW Section 8.6)."""
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4


from oki.translations.enums import QaDimension, SOW_DIMENSIONS
from oki.translations.service import TranslationQaService


async def test_returns_fallback_when_no_client() -> None:
    qa = TranslationQaService()
    with patch("oki.providers.factory.create_openai_client", return_value=None):
        scores = await qa.evaluate(uuid4(), [{"source_text": "Hi", "translated_text": "Hola"}])
    assert set(scores) == set(SOW_DIMENSIONS)
    assert all(s == 70 for s in scores.values())


async def test_returns_fallback_for_empty_segments() -> None:
    qa = TranslationQaService()
    scores = await qa.evaluate(uuid4(), [])
    assert all(s == 70 for s in scores.values())


async def test_returns_gpt_scores_when_client_available() -> None:
    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = (
        '{"meaning_accuracy": 88, "naturalness": 92, "timing_fit": 80, '
        '"terminology": 100, "named_entities": 100, "brand_safety": 100, "creator_voice_match": 75}'
    )
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

    qa = TranslationQaService()
    with patch("oki.providers.factory.create_openai_client", return_value=mock_client):
        scores = await qa.evaluate(
            uuid4(),
            [{"source_text": "Hello", "translated_text": "Hola"}],
        )

    assert scores[QaDimension.MEANING_ACCURACY] == 88
    assert scores[QaDimension.NATURALNESS] == 92
    assert scores[QaDimension.BRAND_SAFETY] == 100
    assert all(0 <= v <= 100 for v in scores.values())


async def test_clamps_out_of_range_scores() -> None:
    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = (
        '{"meaning_accuracy": 150, "naturalness": -5, "timing_fit": 80, '
        '"terminology": 100, "named_entities": 100, "brand_safety": 100, "creator_voice_match": 75}'
    )
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

    qa = TranslationQaService()
    with patch("oki.providers.factory.create_openai_client", return_value=mock_client):
        scores = await qa.evaluate(
            uuid4(),
            [{"source_text": "Hi", "translated_text": "Hola"}],
        )

    assert scores[QaDimension.MEANING_ACCURACY] == 100
    assert scores[QaDimension.NATURALNESS] == 0


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


async def test_is_critical_fail_on_pass_fail_dimension_zero() -> None:
    qa = TranslationQaService()
    scores = {
        QaDimension.MEANING_ACCURACY: 85,
        QaDimension.NATURALNESS: 80,
        QaDimension.TIMING_FIT: 75,
        QaDimension.TERMINOLOGY: 0,      # fail
        QaDimension.NAMED_ENTITIES: 100,
        QaDimension.BRAND_SAFETY: 100,
        QaDimension.CREATOR_VOICE_MATCH: 70,
    }
    assert qa.is_critical_fail(scores) is True


async def test_is_critical_fail_false_when_all_pass() -> None:
    qa = TranslationQaService()
    scores = {
        QaDimension.MEANING_ACCURACY: 85,
        QaDimension.NATURALNESS: 80,
        QaDimension.TIMING_FIT: 75,
        QaDimension.TERMINOLOGY: 100,
        QaDimension.NAMED_ENTITIES: 100,
        QaDimension.BRAND_SAFETY: 100,
        QaDimension.CREATOR_VOICE_MATCH: 70,
    }
    assert qa.is_critical_fail(scores) is False


async def test_is_critical_fail_on_low_meaning_accuracy() -> None:
    qa = TranslationQaService()
    scores = {
        QaDimension.MEANING_ACCURACY: 55,   # below threshold
        QaDimension.NATURALNESS: 80,
        QaDimension.TIMING_FIT: 75,
        QaDimension.TERMINOLOGY: 100,
        QaDimension.NAMED_ENTITIES: 100,
        QaDimension.BRAND_SAFETY: 100,
        QaDimension.CREATOR_VOICE_MATCH: 70,
    }
    assert qa.is_critical_fail(scores) is True
