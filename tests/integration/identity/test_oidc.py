import json
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends
from fastapi.testclient import TestClient

from oki.api.errors import UnauthorizedProblem
from oki.identity.enums import Action
from oki.identity.dependencies import require_action
from oki.identity.keycloak import LocalMembershipResolver, TokenVerifier
from oki.identity.schemas import Principal, PrincipalMembership, ResourceScope
from oki.main import create_app

ISSUER = "https://identity.example.test/realms/oki"
AUDIENCE = "oki-api"
AUTHORIZED_PARTY = "oki-web"
JWKS_URI = f"{ISSUER}/protocol/openid-connect/certs"


def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def jwk_for(key: rsa.RSAPrivateKey, kid: str) -> dict[str, Any]:
    result = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    result.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return result


def access_token(
    key: rsa.RSAPrivateKey,
    *,
    kid: str = "current",
    claims: dict[str, Any] | None = None,
    omit_claims: frozenset[str] = frozenset(),
    algorithm: str = "RS256",
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "keycloak-subject-1",
        "azp": AUTHORIZED_PARTY,
        "typ": "Bearer",
        "iat": now,
        "nbf": now - timedelta(seconds=1),
        "exp": now + timedelta(minutes=5),
    }
    payload.update(claims or {})
    for claim in omit_claims:
        payload.pop(claim, None)
    return jwt.encode(payload, key, algorithm=algorithm, headers={"kid": kid, "typ": "JWT"})


@pytest.fixture
def principal() -> Principal:
    organization_id = uuid4()
    return Principal(
        subject="keycloak-subject-1",
        user_id=uuid4(),
        email="creator@example.test",
        display_name="Creator",
        memberships=(
            PrincipalMembership(
                organization_id=organization_id,
                role_names=frozenset({"creator"}),
                actions=frozenset({Action.PROJECT_READ}),
                creator_organization_ids=frozenset({organization_id}),
                project_ids=frozenset({uuid4()}),
            ),
        ),
    )


class StaticResolver:
    def __init__(self, principal: Principal) -> None:
        self.principal = principal
        self.subjects: list[str] = []

    async def __call__(self, subject: str) -> Principal:
        self.subjects.append(subject)
        return self.principal


def verifier_for(
    client: httpx.AsyncClient,
    principal: Principal,
    *,
    cache_seconds: float = 300,
) -> tuple[TokenVerifier, StaticResolver]:
    resolver = StaticResolver(principal)
    verifier = TokenVerifier(
        issuer=ISSUER,
        audience=AUDIENCE,
        authorized_party=AUTHORIZED_PARTY,
        jwks_uri=JWKS_URI,
        membership_resolver=resolver,
        http_client=client,
        jwks_cache_seconds=cache_seconds,
    )
    return verifier, resolver


async def test_valid_signed_access_token_uses_cached_jwks(principal: Principal) -> None:
    key = rsa_key()
    requests: list[httpx.Request] = []

    def serve_jwks(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"keys": [jwk_for(key, "current")]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(serve_jwks)) as client:
        verifier, resolver = verifier_for(client, principal)
        token = access_token(key)

        first = await verifier.verify(token)
        second = await verifier.verify(token)

    assert first is principal
    assert second is principal
    assert resolver.subjects == ["keycloak-subject-1", "keycloak-subject-1"]
    assert len(requests) == 1
    assert requests[0].url == httpx.URL(JWKS_URI)


async def test_valid_keycloak_access_token_may_omit_optional_not_before(
    principal: Principal,
) -> None:
    key = rsa_key()

    def serve_jwks(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"keys": [jwk_for(key, "current")]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(serve_jwks)) as client:
        verifier, _ = verifier_for(client, principal)
        resolved = await verifier.verify(access_token(key, omit_claims=frozenset({"nbf"})))

    assert resolved is principal


@pytest.mark.parametrize(
    "claims",
    [
        {"iss": "https://attacker.example.test/realms/oki"},
        {"aud": "another-api"},
        {"azp": "untrusted-client"},
        {"typ": "ID"},
        {"exp": datetime.now(UTC) - timedelta(minutes=1)},
        {"nbf": datetime.now(UTC) + timedelta(minutes=1)},
    ],
    ids=["issuer", "audience", "authorized-party", "token-type", "expiry", "not-before"],
)
async def test_invalid_token_claim_dimensions_fail_closed(
    principal: Principal,
    claims: dict[str, Any],
) -> None:
    key = rsa_key()

    def serve_jwks(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"keys": [jwk_for(key, "current")]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(serve_jwks)) as client:
        verifier, resolver = verifier_for(client, principal)

        with pytest.raises(UnauthorizedProblem) as error:
            await verifier.verify(access_token(key, claims=claims))

    assert error.value.code == "invalid_access_token"
    assert resolver.subjects == []


async def test_wrong_signature_fails_closed(principal: Principal) -> None:
    trusted_key = rsa_key()
    attacker_key = rsa_key()

    def serve_jwks(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"keys": [jwk_for(trusted_key, "current")]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(serve_jwks)) as client:
        verifier, _ = verifier_for(client, principal)
        with pytest.raises(UnauthorizedProblem) as error:
            await verifier.verify(access_token(attacker_key))

    assert error.value.code == "invalid_access_token"


async def test_unapproved_algorithm_fails_before_jwks_fetch(principal: Principal) -> None:
    requests = 0

    def serve_jwks(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, json={"keys": []})

    payload = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "keycloak-subject-1",
        "azp": AUTHORIZED_PARTY,
        "typ": "Bearer",
        "nbf": datetime.now(UTC) - timedelta(seconds=1),
        "exp": datetime.now(UTC) + timedelta(minutes=5),
    }
    token = jwt.encode(
        payload,
        "attacker-secret-that-is-long-enough",
        algorithm="HS256",
        headers={"kid": "bad"},
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(serve_jwks)) as client:
        verifier, _ = verifier_for(client, principal)
        with pytest.raises(UnauthorizedProblem):
            await verifier.verify(token)

    assert requests == 0


async def test_unknown_key_triggers_only_one_bounded_refresh(principal: Principal) -> None:
    current_key = rsa_key()
    unknown_key = rsa_key()
    requests = 0

    def serve_jwks(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, json={"keys": [jwk_for(current_key, "current")]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(serve_jwks)) as client:
        verifier, _ = verifier_for(client, principal)
        await verifier.verify(access_token(current_key))

        with pytest.raises(UnauthorizedProblem) as error:
            await verifier.verify(access_token(unknown_key, kid="unknown"))
        with pytest.raises(UnauthorizedProblem):
            await verifier.verify(access_token(unknown_key, kid="another-unknown"))

    assert error.value.code == "invalid_access_token"
    assert requests == 2


async def test_unknown_key_refresh_accepts_rotated_signing_key(principal: Principal) -> None:
    old_key = rsa_key()
    rotated_key = rsa_key()
    requests = 0

    def serve_jwks(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        keys = [jwk_for(old_key, "old")]
        if requests == 2:
            keys.append(jwk_for(rotated_key, "rotated"))
        return httpx.Response(200, json={"keys": keys})

    async with httpx.AsyncClient(transport=httpx.MockTransport(serve_jwks)) as client:
        verifier, _ = verifier_for(client, principal)
        await verifier.verify(access_token(old_key, kid="old"))
        resolved = await verifier.verify(access_token(rotated_key, kid="rotated"))

    assert resolved is principal
    assert requests == 2


async def test_jwks_http_failure_is_unauthorized_not_server_error(principal: Principal) -> None:
    key = rsa_key()

    def unavailable(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "unavailable"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(unavailable)) as client:
        verifier, _ = verifier_for(client, principal)
        with pytest.raises(UnauthorizedProblem) as error:
            await verifier.verify(access_token(key))

    assert error.value.code == "invalid_access_token"


class MappingResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> "MappingResult":
        return self

    def all(self) -> list[dict[str, Any]]:
        return self._rows


class MappingSession:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.parameters: dict[str, Any] | None = None

    async def execute(self, statement: Any, parameters: dict[str, Any]) -> MappingResult:
        self.parameters = parameters
        return MappingResult(self.rows)


class MappingSessionFactory:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.session = MappingSession(rows)

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[MappingSession]:
        yield self.session


class SqliteMappingSession:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    async def execute(self, statement: Any, parameters: dict[str, Any]) -> MappingResult:
        cursor = self._connection.execute(str(statement), parameters)
        return MappingResult([dict(row) for row in cursor.fetchall()])


class SqliteMappingSessionFactory:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._session = SqliteMappingSession(connection)

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[SqliteMappingSession]:
        yield self._session


async def test_membership_cannot_inherit_role_owned_by_another_organization() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE users (
            id TEXT PRIMARY KEY, keycloak_subject TEXT, email TEXT,
            display_name TEXT, is_active INTEGER
        );
        CREATE TABLE organizations (id TEXT PRIMARY KEY, is_active INTEGER);
        CREATE TABLE roles (
            id TEXT PRIMARY KEY, organization_id TEXT, name TEXT, is_system INTEGER
        );
        CREATE TABLE memberships (
            id TEXT PRIMARY KEY, organization_id TEXT, user_id TEXT,
            role_id TEXT, is_active INTEGER
        );
        CREATE TABLE permissions (id TEXT PRIMARY KEY, code TEXT);
        CREATE TABLE role_permissions (role_id TEXT, permission_id TEXT);
        CREATE TABLE creator_account_scopes (
            membership_id TEXT, creator_organization_id TEXT, project_id TEXT
        );
        INSERT INTO users VALUES (
            'user-1', 'cross-tenant-subject', 'user@example.test', 'Cross tenant', 1
        );
        INSERT INTO organizations VALUES ('org-a', 1), ('org-b', 1);
        INSERT INTO roles VALUES ('role-a', 'org-a', 'legal_reviewer', 0);
        INSERT INTO permissions VALUES ('permission-1', 'agreement.approve');
        INSERT INTO role_permissions VALUES ('role-a', 'permission-1');
        INSERT INTO memberships VALUES (
            'membership-b', 'org-b', 'user-1', 'role-a', 1
        );
        """
    )
    try:
        resolver = LocalMembershipResolver(SqliteMappingSessionFactory(connection))
        with pytest.raises(UnauthorizedProblem) as error:
            await resolver("cross-tenant-subject")
    finally:
        connection.close()

    assert error.value.code == "identity_not_registered"


async def test_subject_maps_to_local_membership_permissions_and_creator_scope() -> None:
    user_id = uuid4()
    membership_id = uuid4()
    organization_id = uuid4()
    creator_organization_id = uuid4()
    project_id = uuid4()
    common = {
        "user_id": user_id,
        "subject": "keycloak-subject-1",
        "email": "creator@example.test",
        "display_name": "Creator",
        "membership_id": membership_id,
        "organization_id": organization_id,
        "role_name": "creator",
        "creator_organization_id": creator_organization_id,
        "project_id": project_id,
    }
    factory = MappingSessionFactory(
        [
            {**common, "permission_code": Action.PROJECT_READ.value},
            {**common, "permission_code": Action.CREATOR_REVIEW_SUBMIT.value},
        ]
    )

    resolved = await LocalMembershipResolver(factory)("keycloak-subject-1")

    assert factory.session.parameters == {"subject": "keycloak-subject-1"}
    assert resolved.user_id == user_id
    assert resolved.subject == "keycloak-subject-1"
    assert len(resolved.memberships) == 1
    membership = resolved.memberships[0]
    assert membership.organization_id == organization_id
    assert membership.actions == frozenset(
        {Action.PROJECT_READ, Action.CREATOR_REVIEW_SUBMIT}
    )
    assert membership.creator_organization_ids == frozenset({creator_organization_id})
    assert membership.project_ids == frozenset({project_id})


async def test_unknown_local_subject_is_unauthorized() -> None:
    with pytest.raises(UnauthorizedProblem) as error:
        await LocalMembershipResolver(MappingSessionFactory([]))("unknown")

    assert error.value.code == "identity_not_registered"


def test_identity_router_uses_bearer_verifier_and_problem_contract(
    principal: Principal,
) -> None:
    class FakeVerifier:
        async def verify(self, token: str) -> Principal:
            assert token == "signed-access-token"
            return principal

    app = create_app()
    app.state.token_verifier = FakeVerifier()
    client = TestClient(app)

    missing = client.get("/api/identity/me")
    accepted = client.get(
        "/api/identity/me",
        headers={"Authorization": "Bearer signed-access-token"},
    )

    assert missing.status_code == 401
    assert missing.headers["content-type"].startswith("application/problem+json")
    assert missing.headers["www-authenticate"] == "Bearer"
    assert missing.json()["code"] == "missing_access_token"
    assert accepted.status_code == 200
    assert accepted.json()["subject"] == principal.subject
    assert accepted.json()["memberships"][0]["actions"] == [Action.PROJECT_READ.value]


def test_require_action_dependency_enforces_authoritative_resource_scope(
    principal: Principal,
) -> None:
    class FakeVerifier:
        async def verify(self, token: str) -> Principal:
            return principal

    organization_id = principal.memberships[0].organization_id

    async def resource_scope() -> ResourceScope:
        return ResourceScope(
            organization_id=organization_id,
            creator_organization_id=organization_id,
        )

    app = create_app()
    app.state.token_verifier = FakeVerifier()

    @app.get("/protected")
    async def protected(
        authorized: Annotated[
            Principal,
            Depends(require_action(Action.PROJECT_READ, resource_scope)),
        ],
    ) -> dict[str, str]:
        return {"subject": authorized.subject}

    response = TestClient(app).get(
        "/protected",
        headers={"Authorization": "Bearer signed-access-token"},
    )

    assert response.status_code == 200
    assert response.json() == {"subject": principal.subject}


def test_application_lifespan_clears_only_its_owned_verifier() -> None:
    owned_app = create_app()
    with TestClient(owned_app):
        owned_verifier = owned_app.state.token_verifier
        assert owned_verifier is not None
    assert getattr(owned_app.state, "token_verifier", None) is None

    external_verifier = object()
    external_app = create_app()
    external_app.state.token_verifier = external_verifier
    with TestClient(external_app):
        assert external_app.state.token_verifier is external_verifier
    assert external_app.state.token_verifier is external_verifier


def test_realm_export_hardens_employee_and_creator_identity() -> None:
    realm_path = Path(__file__).parents[3] / "deploy" / "keycloak" / "oki-realm.json"
    realm = json.loads(realm_path.read_text(encoding="utf-8"))

    assert realm["realm"] == "oki"
    assert realm["verifyEmail"] is True
    assert realm["resetPasswordAllowed"] is True
    assert realm["revokeRefreshToken"] is True
    assert realm["refreshTokenMaxReuse"] == 0
    assert 0 < realm["accessTokenLifespan"] <= 300
    assert 0 < realm["ssoSessionIdleTimeout"] < realm["ssoSessionMaxLifespan"]
    assert realm["bruteForceProtected"] is True
    assert realm["failureFactor"] <= 5
    assert realm["eventsEnabled"] is True
    assert realm["adminEventsEnabled"] is True
    assert not realm.get("users")

    clients = {client["clientId"]: client for client in realm["clients"]}
    assert clients["oki-web"]["publicClient"] is True
    assert clients["oki-web"]["directAccessGrantsEnabled"] is False
    assert clients["oki-api"]["bearerOnly"] is True
    assert all("secret" not in client for client in realm["clients"])

    role_conditions = {
        config["config"]["condUserRole"]
        for config in realm["authenticatorConfig"]
        if "condUserRole" in config["config"]
    }
    assert role_conditions == {"employee"}
    employee_mfa = next(
        flow for flow in realm["authenticationFlows"] if flow["alias"] == "employee-mfa"
    )
    assert any(
        execution.get("authenticator") == "auth-otp-form"
        and execution["requirement"] == "REQUIRED"
        for execution in employee_mfa["authenticationExecutions"]
    )
