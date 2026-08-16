"""Attribution resolution service."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy import select

from oki.db.uow import UnitOfWork
from oki.analytics.models import AttributionLinks, OkiConversionEvents


class AttributionService:
    """Resolve attribution chains for conversion events."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def resolve(self, event_id: UUID) -> dict[str, Any]:
        """Link an event to creator/video/language/campaign and return the attribution chain.

        Args:
            event_id: The OkiConversionEvent identifier.

        Returns:
            A dict describing the attribution resolution chain.
        """
        async with self._uow_factory() as uow:
            event = await uow.session.scalar(
                select(OkiConversionEvents).where(OkiConversionEvents.id == event_id)
            )
            if event is None:
                return {
                    "event_id": str(event_id),
                    "resolved": False,
                    "reason": "Event not found",
                    "chain": {},
                }

            links_result = await uow.session.scalars(
                select(AttributionLinks).where(AttributionLinks.event_id == event_id)
            )
            links = links_result.all()

            chain: dict[str, Any] = {
                "creator_id": str(event.attributed_creator_id) if event.attributed_creator_id else None,
                "job_id": str(event.attributed_job_id) if event.attributed_job_id else None,
                "language": event.attributed_language,
                "campaign_id": event.attributed_campaign_id,
                "value": event.value,
                "currency": event.currency,
                "sources": [
                    {
                        "source": link.source,
                        "link_token": link.link_token,
                        "landing_url": link.landing_url,
                    }
                    for link in links
                ],
            }

            return {
                "event_id": str(event_id),
                "resolved": True,
                "chain": chain,
            }
