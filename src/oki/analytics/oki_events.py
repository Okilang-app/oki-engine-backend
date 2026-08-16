"""Oki event ingestion stub."""

from typing import Any


class OkiEventIngestor:
    """Ingestor for storing Oki platform conversion events.

    TODO: Implement actual event persistence and attribution pipeline.
    """

    async def record_conversion(self, event_data: dict[str, Any]) -> dict[str, Any]:
        """Store a conversion event and run attribution.

        Args:
            event_data: Arbitrary payload describing the conversion event.

        Raises:
            NotImplementedError: Oki conversion event storage is not yet implemented.
        """
        raise NotImplementedError("TODO: store Oki conversion event")
