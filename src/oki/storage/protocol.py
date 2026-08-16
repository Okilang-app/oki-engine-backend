"""Object storage abstraction protocol."""

from typing import Protocol
from uuid import UUID


class ObjectStore(Protocol):
    """Abstract interface for S3-compatible object storage."""

    async def presign_upload(
        self,
        key: str,
        content_type: str,
        *,
        expires_in: int = 3600,
    ) -> str:
        """Return a presigned URL for a single-part PUT upload."""
        ...

    async def presign_put(
        self,
        key: str,
        content_type: str,
        *,
        expires_in: int = 3600,
    ) -> str:
        """Return a presigned URL for a single-part PUT upload."""
        ...

    async def initiate_multipart_upload(
        self,
        key: str,
        content_type: str,
    ) -> str:
        """Begin a multipart upload and return the upload ID."""
        ...

    async def presign_upload_part(
        self,
        key: str,
        upload_id: str,
        part_number: int,
        *,
        expires_in: int = 3600,
    ) -> str:
        """Return a presigned URL for one multipart part."""
        ...

    async def complete_multipart(
        self,
        key: str,
        upload_id: str,
        parts: list[dict],
    ) -> dict:
        """Complete a multipart upload given ordered part ETags."""
        ...

    async def abort_multipart_upload(
        self,
        key: str,
        upload_id: str,
    ) -> None:
        """Abort an in-progress multipart upload."""
        ...

    async def get_object(
        self,
        key: str,
        *,
        range_bytes: tuple[int, int] | None = None,
    ) -> bytes:
        """Fetch an object (or byte range) from storage."""
        ...

    async def head_object(
        self,
        key: str,
    ) -> dict:
        """Return metadata for an object without fetching its body."""
        ...

    async def delete_object(
        self,
        key: str,
    ) -> None:
        """Remove an object from storage."""
        ...
