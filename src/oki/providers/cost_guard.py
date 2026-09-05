"""Simple in-memory cost guard for AI provider API calls."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from oki.api.errors import ProblemException

logger = logging.getLogger(__name__)


@dataclass
class _ProviderSpend:
    month_key: str = ""
    total_usd: float = 0.0
    limit_usd: float = 0.0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_REGISTRY: dict[str, _ProviderSpend] = {}


def _current_month_key() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m")


def initialize_guard(provider: str, monthly_limit_usd: float) -> None:
    """Configure the monthly spend limit for a provider.

    In production this should be backed by persistent storage (e.g. Redis or
    the CostLedgerEntries table) so limits survive process restarts.
    """
    _REGISTRY[provider] = _ProviderSpend(
        month_key=_current_month_key(),
        total_usd=0.0,
        limit_usd=monthly_limit_usd,
    )
    logger.info(
        "Cost guard initialized: provider=%s limit_usd=%.2f",
        provider,
        monthly_limit_usd,
    )


async def check_cost(provider: str, estimated_cost_usd: float = 0.0) -> None:
    """Record estimated spend and raise if the monthly limit would be exceeded."""
    spend = _REGISTRY.get(provider)
    if spend is None or spend.limit_usd <= 0:
        return

    async with spend._lock:
        month = _current_month_key()
        if spend.month_key != month:
            spend.month_key = month
            spend.total_usd = 0.0

        projected = spend.total_usd + estimated_cost_usd
        if projected > spend.limit_usd:
            raise ProblemException(
                status_code=429,
                code=f"{provider}_cost_limit_exceeded",
                title=f"{provider} monthly cost limit exceeded",
                detail=(
                    f"Estimated spend {projected:.4f} USD would exceed "
                    f"monthly limit {spend.limit_usd:.2f} USD."
                ),
                retryable=True,
            )
        spend.total_usd = projected
        logger.info(
            "Provider=%s estimated_cost=%.6f usd month=%s total=%.4f usd limit=%.2f usd",
            provider,
            estimated_cost_usd,
            month,
            spend.total_usd,
            spend.limit_usd,
        )
