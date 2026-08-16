"""Integration tests for single-step asset upload flow."""

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from oki.api.errors import register_problem_handlers
from oki.api.middleware import install_middleware
from oki.assets.router import router as assets_router
from oki.assets.service import AssetService
from oki.config import Settings
from oki.creators.router import router as creators_router
from oki.creators.service import CreatorService
from oki.db.uow import UnitOfWork
from oki.identity.authorization import Authorizer
from oki.identity.dependencies import current_principal
from oki.identity.enums import Action
from oki.identity.schemas import Principal, PrincipalMembership
from oki.storage.protocol import ObjectStore


class FakeStore:
    """In-memory object store for integration testing."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.multipart_uploads: dict[str, dict] = {}
        self.deleted: list[str] = []

    async def presign_upload(
        self,
        key: str,
        content_type: str,
        *,
        expires_in: int = 3600,
    ) -> str:
        return f"http://fake-store/{key}"

    async def presign_put(
        self,
        key: str,
        content_type: str,
        *,
        expires_in: int = 3600,
    ) -> str:
        return f"http://fake-store/{key}"

    async def initiate_multipart_upload(self, key: str, content_type: str) -> str:
        upload_id = str(uuid4())
        self.multipart_uploads[upload_id] = {"key": key, "parts": []}
        return upload_id

    async def presign_upload_part(
        self,
        key: str,
        upload_id: str,
        part_number: int,
        *,
        expires_in: int = 3600,
    ) -> str:
        return f"http://fake-store/{key}?part={part_number}&upload={upload_id}"

    async def complete_multipart(
        self,
        key: str,
        upload_id: str,
        parts: list[dict],
    ) -> dict:
        self.multipart_uploads.get(upload_id, {})["parts"] = parts
        return {"key": key}

    async def abort_multipart_upload(self, key: str, upload_id: str) -> None:
        self.multipart_uploads.pop(upload_id, None)

    async def get_object(self, key: str, *, range_bytes: tuple[int, int] | None = None) -> bytes:
        return self.objects.get(key, b"")

    async def head_object(self, key: str) -> dict:
        return {"content_length": len(self.objects.get(key, b""))}

    async def delete_object(self, key: str) -> None:
        self.deleted.append(key)
        self.objects.pop(key, None)


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(Settings(environment="test").database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture
async def identity_rows(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[tuple[UUID, UUID]]:
    organization_id = uuid4()
    user_id = uuid4()
    async with session_factory.begin() as session:
        await session.execute(
            text(
                "insert into organizations (id, slug, name) "
                "values (:id, :slug, 'Simple upload tenant')"
            ),
            {"id": organization_id, "slug": f"simple-upload-{organization_id}"},
        )
        await session.execute(
            text(
                "insert into users (id, keycloak_subject, email, display_name) "
                "values (:id, :subject, :email, 'Uploader')"
            ),
            {
                "id": user_id,
                "subject": f"simple-upload-{user_id}",
                "email": f"simple-upload-{user_id}@example.test",
            },
        )
    try:
        yield organization_id, user_id
    finally:
        async with session_factory.begin() as session:
            await session.execute(
                text("delete from audit_events where organization_id = :organization_id"),
                {"organization_id": organization_id},
            )
            await session.execute(
                text("delete from source_assets where organization_id = :organization_id"),
                {"organization_id": organization_id},
            )
            await session.execute(
                text("delete from creators where organization_id = :organization_id"),
                {"organization_id": organization_id},
            )
            await session.execute(
                text("delete from organizations where id = :organization_id"),
                {"organization_id": organization_id},
            )
            await session.execute(
                text("delete from users where id = :user_id"),
                {"user_id": user_id},
            )


@pytest.fixture
def principal(identity_rows: tuple[UUID, UUID]) -> Principal:
    organization_id, user_id = identity_rows
    return Principal(
        subject=f"simple-upload-{user_id}",
        user_id=user_id,
        email=f"simple-upload-{user_id}@example.test",
        display_name="Uploader",
        memberships=(
            PrincipalMembership(
                organization_id=organization_id,
                role_names=frozenset({"uploader"}),
                actions=frozenset(
                    {
                        Action.CREATOR_CREATE,
                        Action.CREATOR_READ,
                        Action.ASSET_CREATE,
                        Action.ASSET_READ,
                        Action.ASSET_VALIDATE,
                    }
                ),
                creator_organization_ids=frozenset({organization_id}),
            ),
        ),
    )


@pytest.fixture
async def client_and_principal(
    session_factory: async_sessionmaker[AsyncSession],
    principal: Principal,
) -> AsyncIterator[tuple[httpx.AsyncClient, Principal]]:
    app = FastAPI()
    install_middleware(app)
    register_problem_handlers(app)
    uow_factory = lambda: UnitOfWork(session_factory)
    store: ObjectStore = FakeStore()
    app.state.creator_service = CreatorService(uow_factory, Authorizer())
    app.state.asset_service = AssetService(uow_factory, Authorizer(), store)
    app.include_router(creators_router)
    app.include_router(assets_router)

    async def override_principal() -> Principal:
        return principal

    app.dependency_overrides[current_principal] = override_principal
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client, principal


def creator_payload(organization_id: UUID) -> dict[str, object]:
    return {
        "organization_id": str(organization_id),
        "legal_name": "Test Creator LLC",
        "display_name": "Test Creator",
        "primary_email": "creator@example.test",
        "channels": [],
    }


async def test_simple_upload_returns_presigned_url(
    client_and_principal: tuple[httpx.AsyncClient, Principal],
    identity_rows: tuple[UUID, UUID],
) -> None:
    client, _ = client_and_principal
    organization_id, _ = identity_rows

    # Create a creator first so creator_id resolves properly
    creator_resp = await client.post("/api/creators", json=creator_payload(organization_id))
    assert creator_resp.status_code == 201

    payload = {
        "title": "Test Asset",
        "file_name": "test.txt",
        "content_type": "text/plain",
        "size_bytes": 12,
    }
    resp = await client.post("/api/assets/simple-upload", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "asset_id" in data
    assert "presigned_url" in data
    assert data["storage_key"].startswith("uploads/")
    assert data["storage_key"].endswith("/test.txt")


async def test_finalize_upload_sets_status_active(
    client_and_principal: tuple[httpx.AsyncClient, Principal],
    identity_rows: tuple[UUID, UUID],
) -> None:
    client, _ = client_and_principal
    organization_id, _ = identity_rows

    creator_resp = await client.post("/api/creators", json=creator_payload(organization_id))
    assert creator_resp.status_code == 201

    upload_payload = {
        "title": "Finalize Test",
        "file_name": "finalize.txt",
        "content_type": "text/plain",
        "size_bytes": 12,
    }
    upload_resp = await client.post("/api/assets/simple-upload", json=upload_payload)
    assert upload_resp.status_code == 200
    asset_id = upload_resp.json()["asset_id"]

    finalize_payload = {
        "sha256": "a" * 64,
    }
    finalize_resp = await client.post(f"/api/assets/{asset_id}/finalize", json=finalize_payload)
    assert finalize_resp.status_code == 200, finalize_resp.text
    data = finalize_resp.json()
    assert data["status"] == "active"
    assert data["sha256"] == "a" * 64
    assert data["id"] == asset_id


async def test_list_assets_includes_simple_upload(
    client_and_principal: tuple[httpx.AsyncClient, Principal],
    identity_rows: tuple[UUID, UUID],
) -> None:
    client, _ = client_and_principal
    organization_id, _ = identity_rows

    creator_resp = await client.post("/api/creators", json=creator_payload(organization_id))
    assert creator_resp.status_code == 201

    upload_payload = {
        "title": "List Test",
        "file_name": "list.txt",
        "content_type": "text/plain",
        "size_bytes": 12,
    }
    upload_resp = await client.post("/api/assets/simple-upload", json=upload_payload)
    assert upload_resp.status_code == 200
    asset_id = upload_resp.json()["asset_id"]

    list_resp = await client.get("/api/assets")
    assert list_resp.status_code == 200
    assets = list_resp.json()
    ids = [a["id"] for a in assets]
    assert str(asset_id) in ids
