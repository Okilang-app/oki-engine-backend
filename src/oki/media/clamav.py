"""ClamAV virus scanner integration over TCP.

TODO: Replace with real clamav / pyClamd integration when available.
"""

import asyncio
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ClamAVScanner:
    """Stub ClamAV scanner that connects over TCP to clamd."""

    def __init__(self, host: str = "127.0.0.1", port: int = 3310, timeout: float = 30.0) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout

    async def scan(self, path: Path | str) -> dict[str, Any]:
        """Scan a file for malware.

        TODO: Implement real INSTREAM / zSCAN protocol against clamd.
        For now returns a clean pass so tests can continue.
        """
        logger.info("clamav scan stub called for %s", path)
        return {
            "clean": True,
            "threats": [],
            "path": str(path),
            "status": "stub",
        }

    async def ping(self) -> bool:
        """Check if clamd is reachable."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port),
                timeout=self._timeout,
            )
            writer.write(b"zPING\0")
            await writer.drain()
            data = await asyncio.wait_for(reader.read(1024), timeout=self._timeout)
            writer.close()
            await writer.wait_closed()
            return b"PONG" in data
        except Exception:
            return False
