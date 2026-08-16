"""YouTube OAuth flow service with PKCE and token encryption."""

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select

from oki.api.errors import ProblemException
from oki.crypto.envelope import EnvelopeCipher
from oki.creators.models import Creator
from oki.db.uow import UnitOfWork
from oki.identity.authorization import Authorizer
from oki.identity.enums import Action
from oki.identity.schemas import Principal, ResourceScope
from oki.youtube.models import OAuthConnection, AuthorizedChannel


class YoutubeOAuthService:
    """Stub OAuth service for YouTube channel authorization."""

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

            state = uuid4().hex
            code_verifier = uuid4().hex + uuid4().hex

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
                f"?client_id=CLIENT_ID"
                f"&redirect_uri={callback_url}"
                f"&response_type=code"
                f"&scope={connection.scope}"
                f"&state={state}"
                f"&code_challenge={code_verifier}"
                f"&code_challenge_method=plain"
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

            # TODO: Exchange code for real tokens via Google OAuth token endpoint.
            access_token = f"stub_access_token_{code}"
            refresh_token = f"stub_refresh_token_{state}"
            expires_in = 3600

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

            # TODO: Fetch real channel info from YouTube Data API.
            channel = AuthorizedChannel(
                organization_id=connection.organization_id,
                connection_id=connection.id,
                platform_channel_id=f"stub_channel_{connection.id.hex[:8]}",
                channel_title="Stub Channel",
                upload_defaults={},
                is_active=True,
                linked_at=datetime.now(timezone.utc),
            )
            uow.session.add(channel)
            await uow.session.flush()

            return channel

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
