"""Oki event ingestion."""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from oki.analytics.models import OkiConversionEvents
from oki.db.uow import UnitOfWork


class OkiEventIngestor:
    def __init__(self, uow_factory) -> None:
        self._uow_factory = uow_factory

    async def record_conversion(
        self,
        organization_id: UUID,
        video_id: str,
        click_timestamp: datetime,
        attribution_source: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record an Oki conversion event with attribution."""
        event_metadata = {"video_id": video_id, "attribution_source": attribution_source}
        if metadata:
            event_metadata.update(metadata)

        async with self._uow_factory() as uow:
            event = OkiConversionEvents(
                id=uuid4(),
                organization_id=organization_id,
                event_type="conversion",
                event_metadata=event_metadata,
                occurred_at=click_timestamp.astimezone(timezone.utc)
                if click_timestamp.tzinfo
                else click_timestamp.replace(tzinfo=timezone.utc),
                created_at=datetime.now(timezone.utc),
            )
            uow.session.add(event)
            await uow.session.flush()
            return {
                "event_id": str(event.id),
                "organization_id": str(organization_id),
                "video_id": video_id,
                "attribution_source": attribution_source,
                "recorded_at": event.created_at.isoformat(),
            }
