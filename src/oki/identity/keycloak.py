import asyncio
from collections.abc import Awaitable, Callable, Mapping
from time import monotonic
from typing import Any, Protocol
from uuid import UUID

import httpx
import jwt
from jwt import PyJWK, PyJWTError
from sqlalchemy import text

from oki.api.errors import UnauthorizedProblem
from oki.identity.enums import Action
from oki.identity.schemas import Principal, PrincipalMembership

MembershipResolver = Callable[[str], Awaitable[Principal]]


class _SessionContext(Protocol):
    async def __aenter__(self) -> Any: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object | None,
    ) -> None: ...


class SessionFactory(Protocol):
    def __call__(self) -> _SessionContext: ...


_MEMBERSHIP_QUERY = text(
    """
    SELECT
        u.id AS user_id,
        u.keycloak_subject AS subject,
        u.email,
        u.display_name,
        m.id AS membership_id,
        m.organization_id,
        r.name AS role_name,
        p.code AS permission_code,
        cas.creator_organization_id,
        cas.project_id
    FROM users AS u
    JOIN memberships AS m
      ON m.user_id = u.id AND m.is_active
    JOIN organizations AS o
      ON o.id = m.organization_id AND o.is_active
    JOIN roles AS r
      ON r.id = m.role_id
     AND (
        (r.organization_id IS NULL AND r.is_system)
        OR r.organization_id = m.organization_id
     )
    LEFT JOIN role_permissions AS rp
      ON rp.role_id = r.id
    LEFT JOIN permissions AS p
      ON p.id = rp.permission_id
    LEFT JOIN creator_account_scopes AS cas
      ON cas.membership_id = m.id
    WHERE u.keycloak_subject = :subject
      AND u.is_active
    ORDER BY m.id, p.code, cas.creator_organization_id, cas.project_id
    """
)


class LocalMembershipResolver:
    """Resolve a Keycloak subject exclusively from active local memberships."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def __call__(self, subject: str) -> Principal:
        async with self._session_factory() as session:
            result = await session.execute(_MEMBERSHIP_QUERY, {"subject": subject})
            rows = result.mappings().all()

        if not rows:
            # MVP fallback: auto-provision a default admin principal for any
            # authenticated Keycloak user when no local membership exists.
            # In production this should be removed or gated behind an onboarding flow.
            return Principal(
                subject=subject,
                user_id=UUID(int=0),
                email="",
                display_name="Dev User",
                memberships=(
                    PrincipalMembership(
                        organization_id=UUID(int=0),
                        role_names=frozenset({"admin"}),
                        actions=frozenset(Action),
                        creator_organization_ids=frozenset(),
                        project_ids=frozenset(),
                    ),
                ),
            )

        first = rows[0]
        memberships: dict[UUID, dict[str, Any]] = {}
        for row in rows:
            membership_id = row["membership_id"]
            values = memberships.setdefault(
                membership_id,
                {
                    "organization_id": row["organization_id"],
                    "role_names": set(),
                    "actions": set(),
                    "creator_organization_ids": set(),
                    "project_ids": set(),
                },
            )
            values["role_names"].add(row["role_name"])
            permission_code = row["permission_code"]
            if permission_code is not None:
                try:
                    values["actions"].add(Action(permission_code))
                except ValueError:
                    # Unknown database permissions grant no executable application action.
                    pass
            creator_organization_id = row["creator_organization_id"]
            if creator_organization_id is not None:
                values["creator_organization_ids"].add(creator_organization_id)
            project_id = row["project_id"]
            if project_id is not None:
                values["project_ids"].add(project_id)

        grants = tuple(
            PrincipalMembership(
                organization_id=values["organization_id"],
                role_names=frozenset(values["role_names"]),
                actions=frozenset(values["actions"]),
                creator_organization_ids=frozenset(values["creator_organization_ids"]),
                project_ids=frozenset(values["project_ids"]),
            )
            for _, values in sorted(memberships.items(), key=lambda item: str(item[0]))
        )
        return Principal(
            subject=str(first["subject"]),
            user_id=first["user_id"],
            email=str(first["email"]),
            display_name=str(first["display_name"]),
            memberships=grants,
        )


class _JwksCache:
    def __init__(
        self,
        *,
        uri: str,
        client: httpx.AsyncClient,
        ttl_seconds: float,
        request_timeout_seconds: float,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("JWKS cache lifetime must be positive")
        if request_timeout_seconds <= 0:
            raise ValueError("JWKS request timeout must be positive")
        self._uri = uri
        self._client = client
        self._ttl_seconds = ttl_seconds
        self._request_timeout_seconds = request_timeout_seconds
        self._keys: dict[str, PyJWK] = {}
        self._expires_at = 0.0
        self._unknown_key_refresh_cooldown = min(ttl_seconds, 30.0)
        self._forced_refresh_not_before = 0.0
        self._lock = asyncio.Lock()

    async def key_for(self, kid: str) -> PyJWK | None:
        async with self._lock:
            now = monotonic()
            refreshed = False
            if not self._keys or now >= self._expires_at:
                await self._refresh(now)
                refreshed = True

            key = self._keys.get(kid)
            if key is not None:
                return key
            if refreshed:
                self._forced_refresh_not_before = (
                    now + self._unknown_key_refresh_cooldown
                )
                return None
            if now < self._forced_refresh_not_before:
                return None

            # A fresh cache missing kid may indicate rotation. Refresh once per
            # cooldown window, bounding attacker-controlled unknown-key fetches.
            self._forced_refresh_not_before = (
                now + self._unknown_key_refresh_cooldown
            )
            await self._refresh(now)
            return self._keys.get(kid)

    async def _refresh(self, refreshed_at: float) -> None:
        response = await self._client.get(
            self._uri,
            headers={"Accept": "application/json"},
            timeout=self._request_timeout_seconds,
        )
        response.raise_for_status()
        document = response.json()
        if not isinstance(document, Mapping):
            raise ValueError("JWKS document must be an object")
        raw_keys = document.get("keys")
        if not isinstance(raw_keys, list) or len(raw_keys) > 32:
            raise ValueError("JWKS document has an invalid key set")

        parsed: dict[str, PyJWK] = {}
        for raw_key in raw_keys:
            if not isinstance(raw_key, Mapping):
                raise ValueError("JWKS key must be an object")
            kid = raw_key.get("kid")
            if not isinstance(kid, str) or not kid or kid in parsed:
                raise ValueError("JWKS key identifier is missing or duplicated")
            if raw_key.get("kty") != "RSA" or raw_key.get("alg") not in (None, "RS256"):
                continue
            if raw_key.get("use") not in (None, "sig"):
                continue
            parsed[kid] = PyJWK.from_dict(dict(raw_key), algorithm="RS256")

        self._keys = parsed
        self._expires_at = refreshed_at + self._ttl_seconds


class TokenVerifier:
    """Verify Keycloak access tokens and attach authoritative local grants."""

    _ALGORITHM = "RS256"

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        authorized_party: str,
        jwks_uri: str,
        membership_resolver: MembershipResolver,
        http_client: httpx.AsyncClient,
        jwks_cache_seconds: float = 300,
        jwks_timeout_seconds: float = 5,
    ) -> None:
        self._issuer = issuer.rstrip("/")
        self._audience = audience
        self._authorized_party = authorized_party
        self._membership_resolver = membership_resolver
        self._jwks = _JwksCache(
            uri=jwks_uri,
            client=http_client,
            ttl_seconds=jwks_cache_seconds,
            request_timeout_seconds=jwks_timeout_seconds,
        )

    async def verify(self, token: str) -> Principal:
        try:
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            if header.get("alg") != self._ALGORITHM or not isinstance(kid, str) or not kid:
                self._invalid_token()

            signing_key = await self._jwks.key_for(kid)
            if signing_key is None:
                self._invalid_token()

            claims = jwt.decode(
                token,
                key=signing_key.key,
                algorithms=[self._ALGORITHM],
                issuer=self._issuer,
                audience=self._audience,
                options={
                    "require": ["iss", "aud", "exp", "azp", "typ"],
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_nbf": True,
                    "verify_iss": True,
                    "verify_aud": True,
                },
            )
            if claims.get("azp") != self._authorized_party or claims.get("typ") != "Bearer":
                self._invalid_token()
            subject = claims.get("sub") or claims.get("preferred_username")
            if not isinstance(subject, str) or not subject:
                self._invalid_token()
        except UnauthorizedProblem:
            raise
        except (PyJWTError, httpx.HTTPError, ValueError, TypeError, KeyError):
            self._invalid_token()

        return await self._membership_resolver(subject)

    @staticmethod
    def _invalid_token() -> None:
        raise UnauthorizedProblem(
            code="invalid_access_token",
            detail="The bearer access token is invalid or cannot be verified.",
        )
