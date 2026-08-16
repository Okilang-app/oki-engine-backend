from decimal import Decimal


class PayoutCalculator:
    """Calculate creator payout amounts using precise Decimal arithmetic."""

    @staticmethod
    def calculate(gross: Decimal, share_bps: int, currency: str) -> Decimal:
        """Return payout amount from gross revenue and share in basis points.

        Args:
            gross: Gross revenue amount.
            share_bps: Revenue share in basis points (1 bp = 0.01%).
            currency: ISO-4217 currency code (ignored in calculation but required for API consistency).

        Returns:
            Calculated payout as Decimal.
        """
        _ = currency  # reserved for future rounding rules per currency
        factor = Decimal(share_bps) / Decimal("10000")
        return (gross * factor).quantize(Decimal("0.000001"))


class ContributionMarginCalculator:
    """Calculate contribution margin metrics using precise Decimal arithmetic."""

    @staticmethod
    def calculate(revenue: Decimal, cost: Decimal) -> dict:
        """Return margin metrics from revenue and cost.

        Args:
            revenue: Total revenue.
            cost: Total cost.

        Returns:
            Dictionary with margin_bps (basis points), margin_pct (percentage),
            and gross_profit.
        """
        gross_profit = revenue - cost
        if revenue == Decimal("0"):
            margin_pct = Decimal("0")
        else:
            margin_pct = (gross_profit / revenue) * Decimal("100")
            margin_pct = margin_pct.quantize(Decimal("0.0001"))
        margin_bps = (margin_pct * Decimal("100")).quantize(Decimal("0.0001"))
        return {
            "margin_bps": margin_bps,
            "margin_pct": margin_pct,
            "gross_profit": gross_profit.quantize(Decimal("0.000001")),
        }
