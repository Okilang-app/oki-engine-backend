import asyncio
from urllib.parse import unquote, urlsplit

import httpx
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine


async def database_is_ready(engine: AsyncEngine) -> bool:
    """Return whether PostgreSQL accepts a trivial query."""

    try:
        async with engine.connect() as connection:
            await connection.execute(text("select 1"))
    except (SQLAlchemyError, OSError, TimeoutError):
        return False
    return True


def _valkey_command(*parts: str) -> bytes:
    encoded_parts = [part.encode() for part in parts]
    chunks = [f"*{len(encoded_parts)}\r\n".encode()]
    for part in encoded_parts:
        chunks.extend((f"${len(part)}\r\n".encode(), part, b"\r\n"))
    return b"".join(chunks)


async def valkey_is_ready(url: str, *, timeout: float = 2.0) -> bool:
    """Return whether Valkey accepts authentication, database selection, and PING."""

    parsed = urlsplit(url)
    if parsed.scheme not in {"valkey", "valkeys"} or parsed.hostname is None:
        return False

    writer: asyncio.StreamWriter | None = None
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(
                parsed.hostname,
                parsed.port or 6379,
                ssl=True if parsed.scheme == "valkeys" else None,
            ),
            timeout,
        )

        if parsed.password is not None:
            auth_parts = ["AUTH"]
            if parsed.username is not None:
                auth_parts.append(unquote(parsed.username))
            auth_parts.append(unquote(parsed.password))
            writer.write(_valkey_command(*auth_parts))
            await writer.drain()
            if await asyncio.wait_for(reader.readline(), timeout) != b"+OK\r\n":
                return False

        database = parsed.path.removeprefix("/")
        if database and database != "0":
            int(database)
            writer.write(_valkey_command("SELECT", database))
            await writer.drain()
            if await asyncio.wait_for(reader.readline(), timeout) != b"+OK\r\n":
                return False

        writer.write(_valkey_command("PING"))
        await writer.drain()
        return await asyncio.wait_for(reader.readline(), timeout) == b"+PONG\r\n"
    except (OSError, TimeoutError, ValueError):
        return False
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass


async def seaweedfs_s3_is_ready(endpoint_url: str, *, timeout: float = 2.0) -> bool:
    """Return whether the SeaweedFS S3 endpoint is reachable."""

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(f"{endpoint_url.rstrip('/')}/")
    except httpx.HTTPError:
        return False
    return response.status_code in {200, 403}
