from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from oki.db.uow import UnitOfWork
from oki.jobs.models import OutboxEvent

Publish = Callable[[OutboxEvent], Awaitable[None]]
UnitOfWorkFactory = Callable[[], UnitOfWork]


@dataclass(frozen=True, slots=True)
class OutboxPublishResult:
    claimed: int
    published: int
    failed: int


class OutboxPublisher:
    """Claim pending PostgreSQL outbox rows and publish them at least once."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        publish: Publish,
        *,
        clock: Callable[[], datetime] | None = None,
        event_types: set[str] | frozenset[str] | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._publish = publish
        self._event_types = frozenset(event_types) if event_types is not None else None
        self._clock = clock or (lambda: datetime.now(UTC))

    async def publish_batch(self, *, limit: int = 100) -> OutboxPublishResult:
        if limit < 1 or limit > 1_000:
            raise ValueError("limit must be between 1 and 1000")

        now = self._clock()
        published = 0
        failed = 0
        async with self._uow_factory() as uow:
            conditions = [
                OutboxEvent.published_at.is_(None),
                OutboxEvent.available_at <= now,
            ]
            if self._event_types is not None:
                conditions.append(OutboxEvent.event_type.in_(self._event_types))
            events = list(
                await uow.session.scalars(
                    select(OutboxEvent)
                    .where(*conditions)
                    .order_by(OutboxEvent.available_at, OutboxEvent.id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            )
            for event in events:
                event.attempts += 1
                try:
                    await self._publish(event)
                except Exception as exception:
                    failed += 1
                    event.last_error = f"{type(exception).__name__}: {exception}"[:2_000]
                    delay_seconds = min(5 * (2 ** min(event.attempts - 1, 6)), 300)
                    event.available_at = now + timedelta(seconds=delay_seconds)
                else:
                    published += 1
                    event.published_at = now
                    event.last_error = None

        return OutboxPublishResult(
            claimed=published + failed,
            published=published,
            failed=failed,
        )
