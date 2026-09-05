"""Unit tests for POST_DUBBING_PLAN implementations — no DB required."""

from __future__ import annotations

import base64
import hashlib
import os
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest


# ---------------------------------------------------------------------------
# 4.1 Config
# ---------------------------------------------------------------------------
def test_config_has_new_settings():
    from oki.config import get_settings

    s = get_settings()
    assert s.elevenlabs_monthly_limit_usd == 100.0
    assert s.openai_monthly_limit_usd == 200.0
    assert s.youtube_client_id is None  # default
    assert s.youtube_oauth_callback_url == "http://localhost:8000/api/youtube/callback"


# ---------------------------------------------------------------------------
# 4.2 YouTube OAuth — PKCE
# ---------------------------------------------------------------------------
def test_oauth_pkce_s256():
    """Verify PKCE produces a valid S256 challenge."""

    verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()

    assert len(verifier) >= 43
    assert len(challenge) >= 43
    assert challenge != verifier


def test_oauth_service_has_refresh():
    import inspect

    from oki.youtube.oauth import YoutubeOAuthService

    assert hasattr(YoutubeOAuthService, "get_valid_access_token")
    sig = inspect.signature(YoutubeOAuthService.get_valid_access_token)
    assert "connection_id" in sig.parameters


# ---------------------------------------------------------------------------
# 4.3 YouTube Client
# ---------------------------------------------------------------------------
def test_youtube_client_methods():
    from oki.youtube.client import YoutubeClient

    methods = {m for m in dir(YoutubeClient) if not m.startswith("_")}
    assert methods == {"publish_video", "update_metadata", "upload_caption",
                       "upload_video", "poll_processing_status"}


# ---------------------------------------------------------------------------
# 4.5 Platform Checks
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_platform_checks_disclosure_rejects_empty():
    """validate_disclosure raises when title and description are both empty."""
    from oki.api.errors import ProblemException
    from oki.publications.checks import PlatformCheckService

    mock_pub = MagicMock()
    mock_pub.title = None
    mock_pub.description = None
    mock_pub.job_id = uuid4()
    mock_session = MagicMock()
    mock_session.get = AsyncMock(return_value=mock_pub)
    mock_uow = MagicMock()
    mock_uow.session = mock_session
    # uow_factory is an async context manager
    factory = AsyncMock()
    factory.__aenter__ = AsyncMock(return_value=mock_uow)
    factory.__aexit__ = AsyncMock(return_value=False)

    svc = PlatformCheckService(lambda: factory)

    with pytest.raises(ProblemException) as exc:
        await svc.validate_disclosure(uuid4())
    assert exc.value.status_code == 400
    assert "disclosure" in exc.value.code.lower()


@pytest.mark.asyncio
async def test_platform_checks_metadata_rejects_short_title():
    from oki.api.errors import ProblemException
    from oki.publications.checks import PlatformCheckService

    mock_uow = AsyncMock()
    mock_session = MagicMock()
    mock_pub = MagicMock()
    mock_pub.title = "Hi"
    mock_pub.description = "Valid description here."
    mock_session.get = AsyncMock(return_value=mock_pub)
    mock_uow.session = mock_session

    svc = PlatformCheckService(lambda: mock_uow)

    with pytest.raises(ProblemException) as exc:
        await svc.validate_metadata(uuid4())
    assert exc.value.status_code == 400
    assert "title" in exc.value.code.lower()


# ---------------------------------------------------------------------------
# 5.1 Shorts Scoring
# ---------------------------------------------------------------------------
def test_short_scorer_ideal_duration():
    from oki.shorts.scoring import ShortScorer

    scorer = ShortScorer(ffprobe_path="ffprobe")

    class Candidate:
        start_time = 10.0
        end_time = 45.0
        source_video_path = ""  # no file → motion falls back
        transcript_segments = [
            {"text": "This is amazing and unbelievable secret tip", "start": 10, "end": 20}
        ]

    result = scorer.score(Candidate())
    assert result["duration_score"] == 1.0  # 35s is ideal
    assert result["viral_potential"] == 1.0  # 4 viral keywords
    assert result["total"] > 0.5


def test_short_scorer_too_short():
    from oki.shorts.scoring import ShortScorer

    scorer = ShortScorer()

    class Candidate:
        start_time = 0.0
        end_time = 5.0
        source_video_path = ""
        transcript_segments = []

    result = scorer.score(Candidate())
    assert result["duration_score"] == 5.0 / 15  # < 15s scales linearly
    assert result["total"] < 0.5


# ---------------------------------------------------------------------------
# 5.4 Shorts Crop
# ---------------------------------------------------------------------------
def test_crop_tracker_fallback():
    from oki.shorts.crop import CropTracker

    ct = CropTracker()
    crop = ct.track("/nonexistent/file.mp4", [10.0, 20.0])
    assert crop["width"] == 608
    assert crop["height"] == 1080
    assert crop["x"] == 656
    assert crop["y"] == 0


# ---------------------------------------------------------------------------
# 4.4 Campaigns router has CRUD
# ---------------------------------------------------------------------------
def test_campaigns_router_has_crud():
    from oki.campaigns.router import router

    methods = {}
    for r in router.routes:
        for m in getattr(r, "methods", set()):
            methods[m] = methods.get(m, 0) + 1
    assert methods.get("POST", 0) >= 2
    assert methods.get("PUT", 0) >= 2
    assert methods.get("DELETE", 0) >= 1


# ---------------------------------------------------------------------------
# 4.7 Reviews router expanded
# ---------------------------------------------------------------------------
def test_reviews_router_has_new_endpoints():
    from oki.reviews.router import router

    paths = [str(r.path) for r in router.routes]
    assert any("create-package" in p for p in paths)
    assert any("comment" in p for p in paths)
    assert any("versions" in p for p in paths)
    assert any("invalidate" in p for p in paths)
    assert any("creator" in p for p in paths)


# ---------------------------------------------------------------------------
# 5.5 Analytics YouTube
# ---------------------------------------------------------------------------
def test_youtube_analytics_ingestor_methods():
    from oki.analytics.youtube import YoutubeAnalyticsIngestor

    ingestor = YoutubeAnalyticsIngestor()
    assert hasattr(ingestor, "ingest")
    assert hasattr(ingestor, "ingest_video_metrics")


# ---------------------------------------------------------------------------
# 6.1 Notifications
# ---------------------------------------------------------------------------
def test_notification_enums():
    from oki.notifications.models import NotificationChannel, NotificationStatus

    assert NotificationChannel.EMAIL == "email"
    assert NotificationChannel.IN_APP == "in_app"
    assert NotificationChannel.TELEGRAM == "telegram"
    assert NotificationStatus.PENDING == "pending"
    assert NotificationStatus.SENT == "sent"
    assert NotificationStatus.FAILED == "failed"


@pytest.mark.asyncio
async def test_notification_service_in_app_marks_sent():
    from oki.notifications.models import NotificationChannel
    from oki.notifications.schemas import NotificationCreateRequest
    from oki.notifications.service import NotificationService

    mock_uow = AsyncMock()
    mock_session = MagicMock()
    mock_uow.session = mock_session
    mock_authorizer = MagicMock()
    svc = NotificationService(lambda: mock_uow, mock_authorizer)

    payload = NotificationCreateRequest(
        organization_id=uuid4(),
        user_id=uuid4(),
        channel=NotificationChannel.IN_APP,
        subject="Test",
        body="Hello",
    )
    principal = MagicMock()
    result = await svc.send(payload, principal)
    assert result.status == "sent"


# ---------------------------------------------------------------------------
# 6.3 Cost Guard
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_cost_guard_blocks_over_limit():
    from oki.api.errors import ProblemException
    from oki.providers.cost_guard import check_cost, initialize_guard

    initialize_guard("test_guard", 10.0)

    # within budget — no raise
    await check_cost("test_guard", 5.0)

    # over budget — raises 429
    with pytest.raises(ProblemException) as exc:
        await check_cost("test_guard", 20.0)
    assert exc.value.status_code == 429


# ---------------------------------------------------------------------------
# Cross-cutting: No stubs remaining
# ---------------------------------------------------------------------------
def test_no_NotImplementedError_in_implemented_files():
    """Verify key files don't contain remaining stubs."""
    import inspect

    from oki.analytics.oki_events import OkiEventIngestor
    from oki.analytics.youtube import YoutubeAnalyticsIngestor
    from oki.publications.checks import PlatformCheckService
    from oki.youtube.client import YoutubeClient

    modules = [
        ("YoutubeClient", YoutubeClient),
        ("PlatformCheckService", PlatformCheckService),
        ("YoutubeAnalyticsIngestor", YoutubeAnalyticsIngestor),
        ("OkiEventIngestor", OkiEventIngestor),
    ]
    for name, mod in modules:
        src = inspect.getsource(mod)
        assert "NotImplementedError" not in src, f"{name} still has stubs"
