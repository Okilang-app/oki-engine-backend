"""Report builders for daily production and weekly management reports."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any


class DailyProductionReport:
    """Build a daily production status report."""

    def build(self, report_date: date) -> dict[str, Any]:
        """Return a daily production report structure.

        Args:
            report_date: The calendar date for the report.

        Returns:
            A dict with sections: jobs_completed, shorts_generated, costs, issues.
        """
        return {
            "report_type": "daily_production",
            "date": report_date.isoformat(),
            "jobs_completed": {
                "count": 0,
                "items": [],
            },
            "shorts_generated": {
                "count": 0,
                "items": [],
            },
            "costs": {
                "total": Decimal("0.00"),
                "currency": "USD",
                "breakdown": [],
            },
            "issues": {
                "count": 0,
                "items": [],
            },
        }


class WeeklyManagementReport:
    """Build a weekly management summary report."""

    def build(self, week_starting: date) -> dict[str, Any]:
        """Return a weekly management report structure.

        Args:
            week_starting: The Monday (or start-of-week) date for the report.

        Returns:
            A dict with sections: revenue, creator_acquisitions, pipeline_status, action_items.
        """
        return {
            "report_type": "weekly_management",
            "week_starting": week_starting.isoformat(),
            "week_ending": (week_starting + timedelta(days=6)).isoformat(),
            "revenue": {
                "total": Decimal("0.00"),
                "currency": "USD",
                "by_creator": [],
            },
            "creator_acquisitions": {
                "new_creators": 0,
                "pending_agreements": 0,
                "signed_agreements": 0,
            },
            "pipeline_status": {
                "in_translation": 0,
                "in_dubbing": 0,
                "in_render": 0,
                "awaiting_review": 0,
            },
            "action_items": {
                "count": 0,
                "items": [],
            },
        }
