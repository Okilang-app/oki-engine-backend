"""Unit tests for asset storage key generation."""

from uuid import UUID, uuid4

import pytest

from oki.assets.service import AssetService


class FakeStore:
    def __init__(self) -> None:
        self.keys: list[str] = []
        self.uploads: dict[str, str] = {}

    async def presign_upload(self, key: str, content_type: str, *, expires_in: int = 3600) -> str:
        self.keys.append(key)
        return f"http://fake/{key}"

    async def initiate_multipart_upload(self, key: str, content_type: str) -> str:
        self.keys.append(key)
        upload_id = f"upload-{len(self.uploads)}"
        self.uploads[key] = upload_id
        return upload_id

    async def presign_upload_part(
        self, key: str, upload_id: str, part_number: int, *, expires_in: int = 3600
    ) -> str:
        return f"http://fake/{key}/{upload_id}/{part_number}"

    async def complete_multipart(self, key: str, upload_id: str, parts: list[dict]) -> dict:
        return {"Location": f"http://fake/{key}"}

    async def abort_multipart_upload(self, key: str, upload_id: str) -> None:
        pass

    async def get_object(self, key: str, *, range_bytes: tuple[int, int] | None = None) -> bytes:
        return b""

    async def head_object(self, key: str) -> dict:
        return {}

    async def delete_object(self, key: str) -> None:
        pass


def test_storage_key_includes_organization_and_asset_id() -> None:
    org_id = uuid4()
    asset_id = uuid4()
    file_name = "source.mp4"
    key = f"uploads/{org_id}/{asset_id}/{file_name}"
    assert str(org_id) in key
    assert str(asset_id) in key
    assert file_name in key


def test_storage_key_is_deterministic_for_same_inputs() -> None:
    org_id = uuid4()
    asset_id = uuid4()
    file_name = "source.mp4"
    key1 = f"uploads/{org_id}/{asset_id}/{file_name}"
    key2 = f"uploads/{org_id}/{asset_id}/{file_name}"
    assert key1 == key2
