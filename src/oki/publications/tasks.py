import os
import tempfile
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select

from oki.api.errors import ProblemException
from oki.config import get_settings
from oki.db.uow import UnitOfWork
from oki.publications.checks import PlatformCheckService
from oki.publications.models import (
    PublicationAttempts,
    PublicationStatus,
    Publications,
    PublishApprovals,
)
from oki.youtube.models import AuthorizedChannel
from oki.renders.models import RenderAttempt, RenderManifest, RenderOutput
from oki.youtube.client import YoutubeClient


def _get_uow_factory():
    # Import lazily to avoid circular imports
    from oki.db.engine import async_session_factory

    async def factory():
        return UnitOfWork(async_session_factory)

    return factory


def _get_store():
    from oki.storage.s3 import S3ObjectStore

    return S3ObjectStore(get_settings())


def _get_youtube_client():
    from oki.youtube.oauth import YoutubeOAuthService
    from oki.youtube.client import YoutubeClient
    from oki.crypto.envelope import EnvelopeCipher
    from oki.identity.authorization import Authorizer

    settings = get_settings()
    if not settings.token_encryption_key:
        raise RuntimeError("OKI_TOKEN_ENCRYPTION_KEY must be set for YouTube uploads")
    uow_factory = _get_uow_factory()
    cipher = EnvelopeCipher(settings.token_encryption_key)
    authorizer = Authorizer()
    oauth = YoutubeOAuthService(uow_factory, authorizer, cipher)
    return YoutubeClient(oauth)


async def upload_to_platform_task(
    publication_id: UUID,
    *,
    hatchet_workflow_run_id: str | None = None,
    hatchet_task_run_id: str | None = None,
) -> dict[str, Any]:
    """Upload a rendered video privately to YouTube."""
    del hatchet_workflow_run_id, hatchet_task_run_id

    uow_factory = _get_uow_factory()
    store = _get_store()
    youtube_client = _get_youtube_client()

    async with uow_factory() as uow:
        publication = await uow.session.get(Publications, publication_id)
        if publication is None:
            return {"error": "publication_not_found"}

        # Load the latest render output for this job
        render_output = await uow.session.scalar(
            select(RenderOutput)
            .join(RenderAttempt, RenderAttempt.id == RenderOutput.render_attempt_id)
            .join(RenderManifest, RenderManifest.id == RenderAttempt.render_manifest_id)
            .where(RenderManifest.job_id == publication.job_id)
            .order_by(RenderOutput.created_at.desc())
            .limit(1)
        )
        if render_output is None:
            publication.status = PublicationStatus.FAILED
            return {"error": "no_render_output"}

        channel = await uow.session.get(AuthorizedChannel, publication.channel_id)
        if channel is None:
            publication.status = PublicationStatus.FAILED
            return {"error": "no_channel"}

        # Download video from S3 to temp file
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            async for chunk in store.iter_object(render_output.asset_reference):
                with open(tmp_path, "ab") as f:
                    f.write(chunk)

            job = await uow.session.get(
                __import__("oki.jobs.models", fromlist=["LocalizationJob"]).LocalizationJob,
                publication.job_id,
            )

            title = getattr(publication, "title", None) or (
                f"{getattr(job, 'title', None) or 'Video'} [Localized]"
            )
            description = getattr(publication, "description", None) or "Localized content."
            tags = [getattr(publication, "language_code", None) or "localized"]

            yt_metadata = {
                "snippet": {
                    "title": title,
                    "description": description,
                    "tags": tags,
                },
                "status": {
                    "privacyStatus": "private",
                    "selfDeclaredMadeForKids": False,
                },
            }

            result = await youtube_client.upload_video(
                channel.connection_id,
                tmp_path,
                yt_metadata,
            )
            video_id = result["id"]

            publication.private_video_id = video_id
            publication.status = PublicationStatus.PRIVATE_UPLOADED

            attempt = PublicationAttempts(
                organization_id=publication.organization_id,
                publication_id=publication_id,
                attempt_number=1,
                action="upload_private",
                platform_response=result,
            )
            uow.session.add(attempt)

        except Exception as exc:
            publication.status = PublicationStatus.FAILED
            attempt = PublicationAttempts(
                organization_id=publication.organization_id,
                publication_id=publication_id,
                attempt_number=1,
                action="upload_private",
                error_message=str(exc)[:2000],
            )
            uow.session.add(attempt)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    return {
        "video_id": getattr(publication, "private_video_id", None),
        "status": publication.status.value,
    }


async def publish_task(
    publication_id: UUID,
    *,
    hatchet_workflow_run_id: str | None = None,
    hatchet_task_run_id: str | None = None,
) -> dict[str, Any]:
    """Transition a private video to public after approval."""
    del hatchet_workflow_run_id, hatchet_task_run_id

    uow_factory = _get_uow_factory()
    youtube_client = _get_youtube_client()

    async with uow_factory() as uow:
        publication = await uow.session.get(Publications, publication_id)
        if publication is None:
            return {"error": "publication_not_found"}

        approval = await uow.session.scalar(
            select(PublishApprovals)
            .where(PublishApprovals.publication_id == publication_id)
            .where(
                (PublishApprovals.expires_at.is_(None))
                | (PublishApprovals.expires_at > datetime.now(UTC))
            )
            .order_by(PublishApprovals.approved_at.desc())
            .limit(1)
        )
        if approval is None:
            return {"error": "no_valid_approval"}

        channel = await uow.session.get(AuthorizedChannel, publication.channel_id)
        if channel is None:
            return {"error": "no_channel"}

        # Run platform checks
        checks = PlatformCheckService(uow_factory)
        await checks.validate_disclosure(publication_id)
        await checks.validate_metadata(publication_id)

        # Publish
        result = await youtube_client.publish_video(
            channel.connection_id,
            publication.private_video_id,
        )

        publication.video_id = publication.private_video_id
        publication.status = PublicationStatus.PUBLISHED
        publication.published_at = datetime.now(UTC)

    return {"video_id": publication.video_id, "status": "published"}
