"""Async command runner for external media tools."""

import asyncio
import logging
from collections.abc import Sequence
from typing import Any

logger = logging.getLogger(__name__)


class CommandRunner:
    """Run external CLI tools asynchronously and capture stdout/stderr."""

    def __init__(self, timeout_seconds: float = 120.0) -> None:
        self._timeout = timeout_seconds

    async def run(
        self,
        cmd: Sequence[str],
        *,
        stdin: bytes | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> dict[str, Any]:
        """Execute *cmd* and return a dict with rc, stdout, and stderr."""
        program = cmd[0]
        logger.debug("Running command: %s", " ".join(cmd))
        proc = await asyncio.create_subprocess_exec(
            program,
            *cmd[1:],
            stdin=asyncio.subprocess.PIPE if stdin else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**dict(__import__("os").environ), **(env or {})},
            cwd=cwd,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(stdin),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise

        return {
            "rc": proc.returncode or 0,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
        }
