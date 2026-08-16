"""S3-compatible object store implementation using boto3."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from oki.config import Settings

# Chunk size for streaming reads. Large enough to keep syscall overhead low,
# small enough that a media file never lands in memory all at once.
STREAM_CHUNK_SIZE = 1024 * 1024


class S3ObjectStore:
    """Async wrapper around boto3 for S3-compatible storage (SeaweedFS, MinIO, etc.)."""

    def __init__(self, settings: Settings) -> None:
        self._bucket = settings.s3_bucket
        self._public_url = settings.s3_public_url
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key or "",
            aws_secret_access_key=settings.s3_secret_key or "",
            config=BotoConfig(
                signature_version="s3v4",
                retries={"max_attempts": 3, "mode": "adaptive"},
                # Streaming responses hold a connection for the whole download,
                # so the default pool of 10 is exhausted by a handful of viewers.
                max_pool_connections=50,
            ),
        )
        # Separate client for presigned URLs so v4 signatures are computed
        # against the public endpoint the browser will actually use.
        self._presign_client = boto3.client(
            "s3",
            endpoint_url=settings.s3_public_url or settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key or "",
            aws_secret_access_key=settings.s3_secret_key or "",
            config=BotoConfig(
                signature_version="s3v4",
                retries={"max_attempts": 3, "mode": "adaptive"},
            ),
        ) if settings.s3_public_url else self._client

    async def _run(self, method: str, *args: Any, **kwargs: Any) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: getattr(self._client, method)(*args, **kwargs),
        )

    async def presign_upload(
        self,
        key: str,
        content_type: str,
        *,
        expires_in: int = 3600,
    ) -> str:
        return self._presign_client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self._bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=expires_in,
        )

    async def presign_put(
        self,
        key: str,
        content_type: str,
        *,
        expires_in: int = 3600,
    ) -> str:
        """Alias for presign_upload using put_object."""
        return await self.presign_upload(key=key, content_type=content_type, expires_in=expires_in)

    async def presign_get(
        self,
        key: str,
        *,
        expires_in: int = 3600,
    ) -> str:
        """Generate a presigned URL for GET (video playback)."""
        return self._presign_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    async def initiate_multipart_upload(
        self,
        key: str,
        content_type: str,
    ) -> str:
        response = await self._run(
            "create_multipart_upload",
            Bucket=self._bucket,
            Key=key,
            ContentType=content_type,
        )
        return response["UploadId"]

    async def presign_upload_part(
        self,
        key: str,
        upload_id: str,
        part_number: int,
        *,
        expires_in: int = 3600,
    ) -> str:
        return self._presign_client.generate_presigned_url(
            "upload_part",
            Params={
                "Bucket": self._bucket,
                "Key": key,
                "UploadId": upload_id,
                "PartNumber": part_number,
            },
            ExpiresIn=expires_in,
        )

    async def complete_multipart(
        self,
        key: str,
        upload_id: str,
        parts: list[dict],
    ) -> dict:
        return await self._run(
            "complete_multipart_upload",
            Bucket=self._bucket,
            Key=key,
            UploadId=upload_id,
            MultipartUpload={"Parts": parts},
        )

    async def abort_multipart_upload(
        self,
        key: str,
        upload_id: str,
    ) -> None:
        await self._run(
            "abort_multipart_upload",
            Bucket=self._bucket,
            Key=key,
            UploadId=upload_id,
        )

    async def get_object(
        self,
        key: str,
        *,
        range_bytes: tuple[int, int] | None = None,
    ) -> bytes:
        params: dict[str, Any] = {"Bucket": self._bucket, "Key": key}
        if range_bytes is not None:
            params["Range"] = f"bytes={range_bytes[0]}-{range_bytes[1]}"
        response = await self._run("get_object", **params)
        return await asyncio.get_running_loop().run_in_executor(
            None, lambda: response["Body"].read()
        )

    async def iter_object(
        self,
        key: str,
        *,
        range_bytes: tuple[int, int] | None = None,
        chunk_size: int = STREAM_CHUNK_SIZE,
    ) -> AsyncIterator[bytes]:
        """Yield an object's bytes in chunks.

        Unlike :meth:`get_object` this never materialises the whole body, so a
        multi-gigabyte media file costs one chunk of memory per active reader
        instead of its full size. The underlying HTTP connection is released
        even if the client disconnects mid-stream.
        """
        params: dict[str, Any] = {"Bucket": self._bucket, "Key": key}
        if range_bytes is not None:
            params["Range"] = f"bytes={range_bytes[0]}-{range_bytes[1]}"
        response = await self._run("get_object", **params)
        body = response["Body"]
        loop = asyncio.get_running_loop()
        try:
            while True:
                chunk = await loop.run_in_executor(None, body.read, chunk_size)
                if not chunk:
                    break
                yield chunk
        finally:
            await loop.run_in_executor(None, body.close)

    async def head_object(
        self,
        key: str,
    ) -> dict:
        try:
            response = await self._run(
                "head_object",
                Bucket=self._bucket,
                Key=key,
            )
            return {
                "content_length": response.get("ContentLength"),
                "content_type": response.get("ContentType"),
                "etag": response.get("ETag", "").strip('"'),
                "last_modified": response.get("LastModified"),
                "metadata": response.get("Metadata", {}),
            }
        except ClientError as exc:
            error = exc.response.get("Error", {})
            if error.get("Code") == "404":
                return {}
            raise

    async def put_object(
        self,
        key: str,
        body: bytes,
        content_type: str = "application/octet-stream",
    ) -> dict:
        return await self._run(
            "put_object",
            Bucket=self._bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
        )

    async def delete_object(
        self,
        key: str,
    ) -> None:
        await self._run("delete_object", Bucket=self._bucket, Key=key)
