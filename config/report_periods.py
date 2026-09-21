"""Shared monthly reporting-period helpers."""

from __future__ import annotations

import re
from datetime import date


def integration_opening_period(month: str) -> tuple[str, str]:
    """Return the售中工单 period for a report month: previous-month 26th to current-month 25th."""
    if not re.fullmatch(r"\d{4}-\d{2}", str(month)):
        raise ValueError("月份格式应为 YYYY-MM")
    year, number = map(int, month.split("-"))
    if not 1 <= number <= 12:
        raise ValueError("月份格式应为 YYYY-MM")
    previous_year, previous_month = (year - 1, 12) if number == 1 else (year, number - 1)
    return date(previous_year, previous_month, 26).isoformat(), date(year, number, 25).isoformat()
