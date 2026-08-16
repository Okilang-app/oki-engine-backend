"""Factory for creating OpenAI-compatible clients (OpenAI, Azure, local)."""
from openai import AsyncOpenAI, AsyncAzureOpenAI
from oki.config import Settings


def create_openai_client(settings: Settings | None = None) -> AsyncOpenAI | AsyncAzureOpenAI | None:
    """Return an async OpenAI client configured for standard or Azure endpoints."""
    if settings is None:
        settings = Settings()

    # Azure OpenAI takes priority if endpoint is set
    if settings.azure_openai_endpoint and settings.azure_openai_api_key:
        return AsyncAzureOpenAI(
            api_key=settings.azure_openai_api_key,
            azure_endpoint=settings.azure_openai_endpoint,
            api_version=settings.openai_api_version,
        )

    # Standard OpenAI or custom base URL (local Ollama, etc.)
    if settings.openai_base_url or settings.openai_api_key:
        return AsyncOpenAI(
            api_key=settings.openai_api_key or "",
            base_url=settings.openai_base_url or None,
        )

    return None
