"""Unit tests for analysis pipeline tasks — _make_uow_factory patched."""
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4


from oki.analysis.tasks import diarization_task


def _make_fake_runtime(segments):
    """Return a (uow_factory, engine, settings) triple where uow yields *segments*."""

    class _FakeSession:
        def __init__(self):
            self._segs = segments

        async def scalars(self, *a, **kw):
            segs = self._segs

            class _R:
                def __iter__(self):
                    return iter(segs)

                def __aiter__(self):
                    return iter(segs)

            return _R()

        async def flush(self):
            pass

        def add(self, obj):
            if not hasattr(obj, "id") or obj.id is None:
                obj.id = uuid4()

    class _FakeUOW:
        session = _FakeSession()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

    class _FakeEngine:
        async def dispose(self):
            pass

    settings = MagicMock()
    settings.database_url = "postgresql+asyncpg://fake/fake"

    uow_factory = lambda: _FakeUOW()
    return uow_factory, _FakeEngine(), settings


async def test_diarization_assigns_two_speakers_on_large_gap() -> None:
    org_id = uuid4()

    def _seg(start, end):
        s = MagicMock()
        s.id = uuid4()
        s.start_time = Decimal(str(start))
        s.end_time = Decimal(str(end))
        s.organization_id = org_id
        s.speaker_id = None
        return s

    seg1 = _seg(0.0, 2.0)
    seg2 = _seg(3.0, 5.0)   # gap = 1.0 s  → new speaker
    seg3 = _seg(5.1, 7.0)   # gap = 0.1 s  → same speaker as seg2

    with patch(
        "oki.analysis.tasks._make_uow_factory",
        return_value=_make_fake_runtime([seg1, seg2, seg3]),
    ):
        result = await diarization_task(job_id=uuid4(), asset_id=uuid4())

    assert result["task"] == "diarization"
    assert seg1.speaker_id != seg2.speaker_id
    assert seg2.speaker_id == seg3.speaker_id


async def test_diarization_skips_when_no_segments() -> None:
    with patch(
        "oki.analysis.tasks._make_uow_factory",
        return_value=_make_fake_runtime([]),
    ):
        result = await diarization_task(job_id=uuid4(), asset_id=uuid4())

    assert result["status"] == "skipped"
    assert result["reason"] == "no_segments"


async def test_diarization_idempotent_when_speaker_already_set() -> None:
    seg = MagicMock()
    seg.speaker_id = uuid4()
    seg.start_time = Decimal("0.0")
    seg.end_time = Decimal("2.0")
    seg.organization_id = uuid4()

    with patch(
        "oki.analysis.tasks._make_uow_factory",
        return_value=_make_fake_runtime([seg]),
    ):
        result = await diarization_task(job_id=uuid4(), asset_id=uuid4())

    assert result["status"] == "already_done"
