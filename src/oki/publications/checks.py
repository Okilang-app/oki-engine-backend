from uuid import UUID


class PlatformCheckService:
    """Stub for platform compliance validation.

    TODO: Replace with real FTC/YouTube disclosure and metadata validators.
    """

    async def validate_disclosure(self, publication_id: UUID) -> None:
        """Validate sponsorship disclosure requirements."""
        raise NotImplementedError("TODO: FTC/YouTube disclosure validation")

    async def validate_metadata(self, publication_id: UUID) -> None:
        """Validate title, description, and metadata compliance."""
        raise NotImplementedError("TODO: title/description/metadata compliance")
