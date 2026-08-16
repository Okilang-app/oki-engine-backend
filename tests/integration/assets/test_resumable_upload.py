"""Integration tests for asset resumable upload flow."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from oki.api.errors import register_problem_handlers
from oki.api.middleware import install_middleware
from oki.assets.router import router as assets_router
from oki.assets.schemas import AssetCreate, UploadUrlRequest
from oki.assets.service import AssetService
from oki.config import Settings
from oki.creators.router import router as creators_router
from oki.creators.schemas import CreatorCreate
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
        self.next_upload_id = 0

    async def presign_upload(self, key: str, content_type: str, *, expires_in: int = 3600) -> str:
        return f"http://fake/{key}"

    async def initiate_multipart_upload(self, key: str, content_type: str) -> str:
        upload_id = f"mpu-{self.next_upload_id}"
        self.next_upload_id += 1
        self.multipart_uploads[upload_id] = {"key": key, "parts": []}
        return upload_id

    async def presign_upload_part(
        self, key: str, upload_id: str, part_number: int, *, expires_in: int = 3600
    ) -> str:
        return f"http://fake/{key}/{upload_id}/{part_number}"

    async def complete_multipart(self, key: str, upload_id: str, parts: list[dict]) -> dict:
        self.multipart_uploads[upload_id]["parts"] = parts
        self.objects[key] = b"completed"
        return {"Location": f"http://fake/{key}"}

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
                "values (:id, :slug, 'Assets upload tenant')"
            ),
            {"id": organization_id, "slug": f"assets-upload-{organization_id}"},
        )
        await session.execute(
            text(
                "insert into users (id, keycloak_subject, email, display_name) "
                "values (:id, :subject, :email, 'Uploader')"
            ),
            {
                "id": user_id,
                "subject": f"assets-upload-{user_id}",
                "email": f"assets-upload-{user_id}@example.test",
            },
        )
    try:
        yield organization_id, user_id
    finally:
        async with session_factory.begin() as session:
            await session.execute(
                text("delete from upload_parts where asset_upload_id in (select id from asset_uploads where organization_id = :organization_id)"),
                {"organization_id": organization_id},
            )
            await session.execute(
                text("delete from asset_uploads where organization_id = :organization_id"),
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
        subject=f"assets-upload-{user_id}",
        user_id=user_id,
        email=f"assets-upload-{user_id}@example.test",
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


async def test_resumable_upload_creates_asset_and_parts(
    client_and_principal: tuple[httpx.AsyncClient, Principal],
    identity_rows: tuple[UUID, UUID],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    client, _ = client_and_principal
    organization_id, _ = identity_rows

    # Create creator
    creator_resp = await client.post("/api/creators", json=creator_payload(organization_id))
    assert creator_resp.status_code == 201, creator_resp.text
    creator = creator_resp.json()

    # Create asset
    asset_resp = await client.post(
        "/api/assets",
        json={
            "creator_id": creator["id"],
            "title": "Source Video",
            "description": "A test source video",
        },
    )
    assert asset_resp.status_code == 201, asset_resp.text
    asset = asset_resp.json()
    assert asset["status"] == "draft"

    # Request upload URL
    upload_resp = await client.post(
        "/api/assets/upload-url",
        json={
            "asset_id": asset["id"],
            "file_name": "source.mp4",
            "content_type": "video/mp4",
            "total_size": 120_000_000,
            "part_size": 50_000_000,
        },
    )
    assert upload_resp.status_code == 200, upload_resp.text
    upload_data = upload_resp.json()
    assert upload_data["storage_key"].endswith("source.mp4")
    assert len(upload_data["parts"]) == 3  # 120MB / 50MB = 3 parts

    # Verify upload record in DB
    async with session_factory() as session:
        upload_count = await session.scalar(
            select(func.count()).select_from(text("asset_uploads")).where(text("source_asset_id = :asset_id")).params(asset_id=asset["id"])
        )
    assert upload_count == 1


async def test_complete_upload_finalizes_asset(
    client_and_principal: tuple[httpx.AsyncClient, Principal],
    identity_rows: tuple[UUID, UUID],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    client, _ = client_and_principal
    organization_id, _ = identity_rows

    creator_resp = await client.post("/api/creators", json=creator_payload(organization_id))
    assert creator_resp.status_code == 201
    creator = creator_resp.json()

    asset_resp = await client.post(
        "/api/assets",
        json={"creator_id": creator["id"], "title": "Final Video"},
    )
    assert asset_resp.status_code == 201
    asset = asset_resp.json()

    upload_resp = await client.post(
        "/api/assets/upload-url",
        json={
            "asset_id": asset["id"],
            "file_name": "final.mp4",
            "content_type": "video/mp4",
            "total_size": 10_000_000,
            "part_size": 50_000_000,
        },
    )
    assert upload_resp.status_code == 200
    upload_data = upload_resp.json()

    complete_resp = await client.post(
        "/api/assets/complete-upload",
        json={
            "upload_id": upload_data["upload_id"],
            "parts": [{"part_number": 1, "etag": '"etag1"'}],
            "sha256": "a" * 64,
        },
    )
    assert complete_resp.status_code == 200, complete_resp.text
    completed = complete_resp.json()
    assert completed["status"] == "active"
    assert completed["sha256"] == "a" * 64
    assert completed["storage_key"] == upload_data["storage_key"]
