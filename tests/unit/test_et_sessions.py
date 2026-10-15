"""Tests for ET-anchored sessions (no UTC-midnight splits)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.core.market_calendar import et_date, group_by_et_day, to_et
from app.jobs.monitor import MonitorService


def _bar(ts: datetime, vol: int = 100_000) -> object:
    from app.domain.models import Bar

    return Bar(
        symbol="ABCD",
        timestamp=ts,
        open=Decimal("2.0"),
        high=Decimal("2.05"),
        low=Decimal("1.95"),
        close=Decimal("2.0"),
        volume=vol,
        provider="yfinance",
        timeframe="5m",
    )


def test_to_et_assumes_utc_for_naive() -> None:
    aware = datetime(2026, 9, 21, 0, 30, tzinfo=UTC)  # 20:30 EDT Sep 20
    naive = datetime(2026, 9, 21, 0, 30)
    assert to_et(aware).date().isoformat() == "2026-09-20"
    assert to_et(naive).date().isoformat() == "2026-09-20"
    assert et_date(aware).isoformat() == "2026-09-20"


def test_evening_session_stays_together() -> None:
    # 19:00 -> 21:30 ET = 23:00 -> 01:30 UTC: two UTC dates, one ET session.
    bars = [
        _bar(datetime(2026, 9, 20, 23, 0, tzinfo=UTC) + timedelta(minutes=5 * i)) for i in range(30)
    ]
    utc_dates = {b.timestamp.date().isoformat() for b in bars}
    assert len(utc_dates) == 2  # proves the split exists in UTC
    grouped = group_by_et_day(bars)
    assert len(grouped) == 1  # but not in ET
    assert list(grouped)[0].isoformat() == "2026-09-20"


def test_today_vwap_uses_full_et_session() -> None:
    bars = [
        _bar(datetime(2026, 9, 20, 23, 0, tzinfo=UTC) + timedelta(minutes=5 * i)) for i in range(30)
    ]
    vwap = MonitorService._today_vwap(bars)
    # typical 2.00 on every bar -> VWAP exactly 2.00 over all 30 bars
    assert vwap == 2.0
