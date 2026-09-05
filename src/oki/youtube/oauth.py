"""YouTube OAuth flow service with PKCE and token encryption."""

import base64
import hashlib
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select

from oki.api.errors import ProblemException
from oki.config import get_settings
from oki.crypto.envelope import EnvelopeCipher
from oki.creators.models import Creator
from oki.db.uow import UnitOfWork
from oki.identity.authorization import Authorizer
from oki.identity.enums import Action
from oki.identity.schemas import Principal, ResourceScope
from oki.youtube.models import OAuthConnection, AuthorizedChannel


class YoutubeOAuthService:
    """Real OAuth service for YouTube channel authorization."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        authorizer: Authorizer,
        cipher: EnvelopeCipher,
    ) -> None:
        self._uow_factory = uow_factory
        self._authorizer = authorizer
        self._cipher = cipher

    async def start(self, callback_url: str, principal: Principal) -> dict[str, str]:
        """Generate PKCE state and return the authorization URL."""
        async with self._uow_factory() as uow:
            self._authorizer.require(
                principal,
                Action.CREATOR_CREATE,
                self._scope(principal.organization_id),
            )

            settings = get_settings()
            state = uuid4().hex
            code_verifier = base64.urlsafe_b64encode(
                secrets.token_bytes(32)
            ).rstrip(b"=").decode()
            code_challenge = base64.urlsafe_b64encode(
                hashlib.sha256(code_verifier.encode()).digest()
            ).rstrip(b"=").decode()

            # TODO: Replace stub with real creator lookup once flow is wired.
            creator = await uow.session.scalar(
                select(Creator).limit(1)
            )
            creator_id = creator.id if creator else uuid4()

            connection = OAuthConnection(
                organization_id=principal.organization_id,
                creator_id=creator_id,
                provider="youtube",
                access_token_encrypted=b"",
                refresh_token_encrypted=b"",
                token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                scope="https://www.googleapis.com/auth/youtube.upload",
                state=state,
                code_verifier=code_verifier,
                created_by_user_id=principal.user_id,
            )
            uow.session.add(connection)
            await uow.session.flush()

            auth_url = (
                "https://accounts.google.com/o/oauth2/v2/auth"
                f"?client_id={settings.youtube_client_id}"
                f"&redirect_uri={callback_url}"
                f"&response_type=code"
                f"&scope={connection.scope}"
                f"&state={state}"
                f"&code_challenge={code_challenge}"
                f"&code_challenge_method=S256"
                f"&access_type=offline"
                f"&prompt=consent"
            )

            return {"auth_url": auth_url}

    async def callback(
        self, code: str, state: str, principal: Principal
    ) -> AuthorizedChannel:
        """Exchange authorization code for tokens and store encrypted credentials."""
        async with self._uow_factory() as uow:
            self._authorizer.require(
                principal,
                Action.CREATOR_CREATE,
                self._scope(principal.organization_id),
            )

            connection = await uow.session.scalar(
                select(OAuthConnection)
                .where(
                    OAuthConnection.state == state,
                    OAuthConnection.provider == "youtube",
                )
            )
            if connection is None:
                self._not_found("oauth_state_not_found", "OAuth state not found")

            settings = get_settings()
            async with httpx.AsyncClient() as client:
                token_resp = await client.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "code": code,
                        "client_id": settings.youtube_client_id,
                        "client_secret": settings.youtube_client_secret,
                        "redirect_uri": settings.youtube_oauth_callback_url,
                        "grant_type": "authorization_code",
                        "code_verifier": connection.code_verifier,
                    },
                )
                token_resp.raise_for_status()
                token_data = token_resp.json()

            access_token = token_data["access_token"]
            refresh_token = token_data.get("refresh_token", "")
            expires_in = token_data.get("expires_in", 3600)

            connection.access_token_encrypted = self._cipher.encrypt(
                access_token.encode()
            )
            connection.refresh_token_encrypted = self._cipher.encrypt(
                refresh_token.encode()
            )
            connection.token_expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=expires_in
            )
            connection.state = None
            connection.code_verifier = None
            uow.session.add(connection)

            async with httpx.AsyncClient() as client:
                channel_resp = await client.get(
                    "https://www.googleapis.com/youtube/v3/channels",
                    params={"part": "snippet", "mine": "true"},
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                channel_resp.raise_for_status()
                channel_data = channel_resp.json()

            items = channel_data.get("items", [])
            if not items:
                raise ProblemException(
                    status_code=400,
                    code="youtube_channel_not_found",
                    title="YouTube channel not found",
                    detail="No YouTube channel associated with this Google account.",
                )

            snippet = items[0].get("snippet", {})
            platform_channel_id = items[0]["id"]
            channel_title = snippet.get("title", "Unknown Channel")

            channel = AuthorizedChannel(
                organization_id=connection.organization_id,
                connection_id=connection.id,
                platform_channel_id=platform_channel_id,
                channel_title=channel_title,
                upload_defaults={},
                is_active=True,
                linked_at=datetime.now(timezone.utc),
            )
            uow.session.add(channel)
            await uow.session.flush()

            return channel

    async def get_valid_access_token(self, connection_id: UUID) -> str:
        """Load connection, return decrypted access token, refreshing if needed."""
        async with self._uow_factory() as uow:
            connection = await uow.session.get(OAuthConnection, connection_id)
            if connection is None or not connection.is_active:
                self._not_found("connection_not_found", "Connection not found")

            now = datetime.now(timezone.utc)
            if connection.token_expires_at > now + timedelta(minutes=5):
                return self._cipher.decrypt(
                    connection.access_token_encrypted
                ).decode()

            refresh_token = self._cipher.decrypt(
                connection.refresh_token_encrypted
            ).decode()

            settings = get_settings()
            async with httpx.AsyncClient() as client:
                refresh_resp = await client.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "client_id": settings.youtube_client_id,
                        "client_secret": settings.youtube_client_secret,
                        "refresh_token": refresh_token,
                        "grant_type": "refresh_token",
                    },
                )
                refresh_resp.raise_for_status()
                refresh_data = refresh_resp.json()

            new_access_token = refresh_data["access_token"]
            new_expires_in = refresh_data.get("expires_in", 3600)

            connection.access_token_encrypted = self._cipher.encrypt(
                new_access_token.encode()
            )
            connection.token_expires_at = now + timedelta(seconds=new_expires_in)
            uow.session.add(connection)

            return new_access_token

    async def revoke(self, connection_id: UUID, principal: Principal) -> None:
        """Revoke a connection by marking it and its channels inactive."""
        async with self._uow_factory() as uow:
            connection = await uow.session.get(OAuthConnection, connection_id)
            if connection is None:
                self._not_found("connection_not_found", "Connection not found")

            self._authorizer.require(
                principal,
                Action.CREATOR_CREATE,
                self._scope(connection.organization_id),
            )

            connection.is_active = False
            # Mark all associated channels inactive.
            for channel in await uow.session.scalars(
                select(AuthorizedChannel).where(
                    AuthorizedChannel.connection_id == connection_id
                )
            ):
                channel.is_active = False
                uow.session.add(channel)

            uow.session.add(connection)

    @staticmethod
    def _scope(organization_id: UUID) -> ResourceScope:
        return ResourceScope(
            organization_id=organization_id,
            creator_organization_id=organization_id,
        )

    @staticmethod
    def _not_found(code: str, title: str) -> Any:
        raise ProblemException(
            status_code=404,
            code=code,
            title=title,
            detail=f"The requested {title.lower()} does not exist.",
        )
