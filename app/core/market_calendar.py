"""US market calendar: sessions, holidays, intraday helpers."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.domain.models import MarketSession

NY = ZoneInfo("America/New_York")
HOLIDAYS_2025_2026 = {
    date(2025, 1, 1),
    date(2025, 1, 20),
    date(2025, 2, 17),
    date(2025, 4, 18),
    date(2025, 5, 26),
    date(2025, 6, 19),
    date(2025, 7, 4),
    date(2025, 9, 1),
    date(2025, 11, 27),
    date(2025, 12, 25),
    date(2026, 1, 1),
}


def market_session(now: datetime | None = None) -> MarketSession:
    now = now or datetime.now(NY)
    if now.tzinfo is None:
        now = now.replace(tzinfo=NY)
    ny = now.astimezone(NY)
    if ny.weekday() >= 5 or ny.date() in HOLIDAYS_2025_2026:
        return MarketSession.CLOSED
    mins = ny.hour * 60 + ny.minute
    if 4 * 60 <= mins < 9 * 60 + 30:
        return MarketSession.PREMARKET
    if 9 * 60 + 30 <= mins < 16 * 60:
        return MarketSession.REGULAR
    if 16 * 60 <= mins < 20 * 60:
        return MarketSession.AFTER_HOURS
    return MarketSession.CLOSED


def to_et(ts: datetime) -> datetime:
    """Any timestamp -> America/New_York (naive assumed UTC)."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts.astimezone(NY)


def et_date(ts: datetime) -> date:
    """Trading-session date: a 15:55 ET bar and a 00:30 UTC bar agree."""
    return to_et(ts).date()


def group_by_et_day(bars: list[Any]) -> dict[date, list[Any]]:
    """Group intraday bars by ET session date (no UTC-midnight splits)."""
    by_day: dict[date, list[Any]] = {}
    for b in bars:
        by_day.setdefault(et_date(b.timestamp), []).append(b)
    return by_day
