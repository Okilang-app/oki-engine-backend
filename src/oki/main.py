from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

import httpx
from fastapi import APIRouter, FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from oki.api.errors import register_problem_handlers
from oki.api.middleware import install_middleware
from oki.config import Settings, get_settings
from oki.creators.router import router as creator_router
from oki.creators.service import CreatorService
from oki.identity.authorization import Authorizer
from oki.identity.keycloak import LocalMembershipResolver, TokenVerifier
from oki.identity.router import router as identity_router
from oki.rights.router import router as rights_router
from oki.assets.router import router as assets_router
from oki.assets.service import AssetService
from oki.ads.router import router as ads_router
from oki.ads.service import AdService
from oki.analysis.router import router as analysis_router
from oki.analysis.service import AnalysisService
from oki.sponsors.router import router as sponsors_router
from oki.sponsors.service import SponsorDetectionService, SponsorReviewService
from oki.translations.router import router as translations_router
from oki.translations.service import TranslationService
from oki.voices.router import router as voices_router
from oki.voices.service import VoiceService
from oki.dubbing.router import router as dubbing_router
from oki.dubbing.service import DubbingService
from oki.campaigns.router import router as campaigns_router
from oki.campaigns.service import CampaignService
from oki.renders.router import router as renders_router
from oki.renders.service import RenderService
from oki.reviews.router import router as reviews_router
from oki.reviews.service import ReviewService
from oki.youtube.router import router as youtube_router
from oki.publications.router import router as publications_router
from oki.publications.service import PublicationService
from oki.shorts.router import router as shorts_router
from oki.shorts.service import ShortService
from oki.analytics.router import router as analytics_router
from oki.analytics.service import AnalyticsService
from oki.finance.router import router as finance_router
from oki.finance.service import FinanceService
from oki.jobs.router import router as jobs_router
from oki.jobs.service import JobService
from oki.storage.s3 import S3ObjectStore

health_router = APIRouter()


@health_router.get("/health", tags=["system"])
async def health() -> dict[str, Literal["ok"]]:
    """Report API process availability without requiring authentication."""

    return {"status": "ok"}


@asynccontextmanager
async def _identity_lifespan(app: FastAPI) -> AsyncIterator[None]:
    if getattr(app.state, "token_verifier", None) is not None:
        yield
        return

    settings: Settings = app.state.settings
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    from oki.db.uow import UnitOfWork

    uow_factory = lambda: UnitOfWork(session_factory)
    authorizer = Authorizer()
    store = S3ObjectStore(settings)
    app.state.s3_store = store
    app.state.creator_service = CreatorService(uow_factory, authorizer)
    app.state.asset_service = AssetService(uow_factory, authorizer, store)
    app.state.ad_service = AdService(uow_factory, authorizer)
    app.state.analysis_service = AnalysisService(uow_factory, authorizer)
    app.state.translation_service = TranslationService(uow_factory, authorizer)
    app.state.dubbing_service = DubbingService(uow_factory, authorizer, store)
    app.state.render_service = RenderService(uow_factory, authorizer, store)
    app.state.campaign_service = CampaignService(uow_factory, authorizer)
    app.state.publication_service = PublicationService(uow_factory, authorizer)
    app.state.reviews_service = ReviewService(uow_factory, authorizer)
    app.state.finance_service = FinanceService(uow_factory, authorizer)
    app.state.voice_service = VoiceService(uow_factory, authorizer)
    app.state.sponsor_detection_service = SponsorDetectionService(uow_factory, authorizer)
    app.state.sponsor_review_service = SponsorReviewService(uow_factory, authorizer)
    app.state.shorts_service = ShortService(uow_factory, authorizer)
    app.state.analytics_service = AnalyticsService(uow_factory, authorizer)
    app.state.jobs_service = JobService(uow_factory, authorizer)
    async with httpx.AsyncClient() as client:
        app.state.token_verifier = TokenVerifier(
            issuer=settings.keycloak_issuer,
            audience=settings.keycloak_audience,
            authorized_party=settings.keycloak_authorized_party,
            jwks_uri=(
                settings.keycloak_jwks_uri
                or f"{settings.keycloak_issuer.rstrip('/')}/protocol/openid-connect/certs"
            ),
            membership_resolver=LocalMembershipResolver(session_factory),
            http_client=client,
            jwks_cache_seconds=settings.keycloak_jwks_cache_seconds,
            jwks_timeout_seconds=settings.keycloak_jwks_timeout_seconds,
        )
        try:
            yield
        finally:
            app.state.token_verifier = None
            await engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the Oki API application."""

    resolved = settings or get_settings()
    app = FastAPI(
        title="Oki Creator Localization Engine",
        version="1.0.0",
        lifespan=_identity_lifespan,
    )
    app.state.settings = resolved
    install_middleware(app)
    register_problem_handlers(app)
    app.include_router(health_router)
    app.include_router(identity_router)
    app.include_router(creator_router)
    app.include_router(rights_router)
    app.include_router(assets_router)
    app.include_router(ads_router)
    app.include_router(analysis_router)
    app.include_router(sponsors_router)
    app.include_router(translations_router)
    app.include_router(voices_router)
    app.include_router(dubbing_router)
    app.include_router(campaigns_router)
    app.include_router(renders_router)
    app.include_router(reviews_router)
    app.include_router(youtube_router)
    app.include_router(publications_router)
    app.include_router(shorts_router)
    app.include_router(analytics_router)
    app.include_router(finance_router)
    app.include_router(jobs_router)
    return app
