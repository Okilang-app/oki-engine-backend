from decimal import Decimal

import pytest

from oki.finance.calculator import ContributionMarginCalculator, PayoutCalculator


class TestPayoutCalculator:
    def test_basic_share(self) -> None:
        result = PayoutCalculator.calculate(Decimal("1000.00"), 500, "USD")
        assert result == Decimal("50.000000")

    def test_full_share(self) -> None:
        result = PayoutCalculator.calculate(Decimal("1000.00"), 10000, "USD")
        assert result == Decimal("1000.000000")

    def test_zero_share(self) -> None:
        result = PayoutCalculator.calculate(Decimal("1000.00"), 0, "USD")
        assert result == Decimal("0.000000")

    def test_decimal_precision(self) -> None:
        result = PayoutCalculator.calculate(Decimal("999.99"), 3333, "USD")
        assert result == Decimal("333.296667")


class TestContributionMarginCalculator:
    def test_healthy_margin(self) -> None:
        result = ContributionMarginCalculator.calculate(Decimal("1000.00"), Decimal("400.00"))
        assert result["gross_profit"] == Decimal("600.000000")
        assert result["margin_pct"] == Decimal("60.0000")
        assert result["margin_bps"] == Decimal("6000.0000")

    def test_zero_revenue(self) -> None:
        result = ContributionMarginCalculator.calculate(Decimal("0"), Decimal("100.00"))
        assert result["gross_profit"] == Decimal("-100.000000")
        assert result["margin_pct"] == Decimal("0.0000")
        assert result["margin_bps"] == Decimal("0.0000")

    def test_negative_margin(self) -> None:
        result = ContributionMarginCalculator.calculate(Decimal("100.00"), Decimal("150.00"))
        assert result["gross_profit"] == Decimal("-50.000000")
        assert result["margin_pct"] == Decimal("-50.0000")
        assert result["margin_bps"] == Decimal("-5000.0000")

    def test_perfect_efficiency(self) -> None:
        result = ContributionMarginCalculator.calculate(Decimal("500.00"), Decimal("0"))
        assert result["gross_profit"] == Decimal("500.000000")
        assert result["margin_pct"] == Decimal("100.0000")
        assert result["margin_bps"] == Decimal("10000.0000")
