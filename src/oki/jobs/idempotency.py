from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy import delete, select, text

from oki.api.errors import ProblemException
from oki.db.uow import UnitOfWork
from oki.jobs.enums import IdempotencyStatus
from oki.jobs.models import IdempotencyRecord

ResultT = TypeVar("ResultT")
UnitOfWorkFactory = Callable[[], UnitOfWork]


class IdempotencyConflict(ProblemException):
    def __init__(self) -> None:
        super().__init__(
            status_code=409,
            code="idempotency_key_conflict",
            title="Idempotency key conflict",
            detail="The idempotency key was already used with a different request.",
        )


class IdempotencyService:
    """Serialize duplicate commands in PostgreSQL and retain their JSON result."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        *,
        retention: timedelta = timedelta(hours=24),
        lock_timeout: timedelta = timedelta(minutes=15),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._retention = retention
        self._lock_timeout = lock_timeout
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(
        self,
        organization_id: UUID,
        scope: str,
        idempotency_key: str,
        command: Callable[[UnitOfWork], Awaitable[ResultT]],
        *,
        request_body: Any = None,
    ) -> ResultT:
        if not scope or len(scope) > 150:
            raise ValueError("scope must contain 1 to 150 characters")
        if not idempotency_key or len(idempotency_key) > 255:
            raise ValueError("idempotency_key must contain 1 to 255 characters")

        request_hash = self._request_hash(request_body)
        lock_key = self._lock_key(organization_id, scope, idempotency_key)
        now = self._clock()

        async with self._uow_factory() as uow:
            await uow.session.execute(
                text("select pg_advisory_xact_lock(:lock_key)"),
                {"lock_key": lock_key},
            )
            record = await uow.session.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.organization_id == organization_id,
                    IdempotencyRecord.scope == scope,
                    IdempotencyRecord.idempotency_key == idempotency_key,
                )
            )
            if record is not None and record.expires_at <= now:
                await uow.session.execute(
                    delete(IdempotencyRecord).where(IdempotencyRecord.id == record.id)
                )
                record = None

            if record is not None:
                if record.request_hash != request_hash:
                    raise IdempotencyConflict()
                if record.status is IdempotencyStatus.COMPLETED:
                    return record.response_body
                await uow.session.delete(record)

            record = IdempotencyRecord(
                organization_id=organization_id,
                scope=scope,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                status=IdempotencyStatus.PROCESSING,
                locked_until=now + self._lock_timeout,
                expires_at=now + self._retention,
            )
            uow.session.add(record)
            await uow.session.flush()

            result = await command(uow)
            normalized_result = json.loads(
                json.dumps(result, ensure_ascii=False, separators=(",", ":"))
            )
            record.status = IdempotencyStatus.COMPLETED
            record.response_status = 200
            record.response_body = normalized_result
            record.locked_until = None
            return normalized_result

    @staticmethod
    def _request_hash(request_body: Any) -> str:
        encoded = json.dumps(
            request_body,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        return sha256(encoded).hexdigest()

    @staticmethod
    def _lock_key(organization_id: UUID, scope: str, idempotency_key: str) -> int:
        digest = sha256(
            f"{organization_id}\0{scope}\0{idempotency_key}".encode()
        ).digest()
        return int.from_bytes(digest[:8], byteorder="big", signed=True)
