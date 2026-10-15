"""Live session view: merge intraday into daily history, pure and testable.

Daily history is cached for a long time (it does not change intraday), so
today's bar is rebuilt from regular-session 5m bars. This also fixes the
premarket case: before the open there is no daily bar for today, and the
day change must be measured against the *previous session close*, not
yesterday's change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from app.core.market_calendar import to_et

REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)


def bar_session_date(value: Any) -> date:
    """Session date of a daily bar (naive datetimes are taken at face value)."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.date()
        return to_et(value).date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value)).date()


@dataclass
class SyntheticDailyBar:
    """Duck-typed stand-in for DailyBar built from intraday bars."""

    symbol: str
    date: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


@dataclass
class LiveSession:
    bars: list[Any]
    session_date: date | None
    prev_close: float | None
    change_pct: float
    phase: str  # premarket | regular | closed
    premarket_high: float | None = None
    premarket_volume: int = 0
    day_high: float | None = None
    day_low: float | None = None
    opening_range_high: float | None = None
    opening_range_low: float | None = None
    session_volume: int = 0
    notes: list[str] = field(default_factory=list)


def _is_regular(ts: datetime) -> bool:
    t = to_et(ts).time()
    return REGULAR_OPEN <= t < REGULAR_CLOSE


def _is_premarket(ts: datetime) -> bool:
    return to_et(ts).time() < REGULAR_OPEN


def build_live_session(
    daily_bars: list[Any],
    bars_5m: list[Any],
    price: float,
    opening_range_minutes: int = 15,
) -> LiveSession:
    """Merge today's intraday activity into the daily series.

    Returns the merged bars plus session context (prev close, day change,
    premarket high/volume, HOD/LOD, opening range).
    """
    bars = list(daily_bars or [])
    last_daily = bar_session_date(bars[-1].date) if bars else None

    intraday_day: date | None = None
    today: list[Any] = []
    if bars_5m:
        intraday_day = max(to_et(b.timestamp).date() for b in bars_5m)
        today = [b for b in bars_5m if to_et(b.timestamp).date() == intraday_day]
    if last_daily is not None and intraday_day is not None and intraday_day < last_daily:
        today, intraday_day = [], None  # stale intraday: daily is the newer truth

    regular = [b for b in today if _is_regular(b.timestamp)]
    pre = [b for b in today if _is_premarket(b.timestamp)]

    out = LiveSession(
        bars=bars, session_date=last_daily, prev_close=None, change_pct=0.0, phase="closed"
    )

    if pre:
        out.premarket_high = max(float(b.high) for b in pre)
        out.premarket_volume = int(sum(int(b.volume or 0) for b in pre))

    if regular:
        synth = SyntheticDailyBar(
            symbol=getattr(regular[0], "symbol", ""),
            date=datetime.combine(intraday_day, time(0, 0)),  # type: ignore[arg-type]
            open=Decimal(str(regular[0].open)),
            high=Decimal(str(max(float(b.high) for b in regular))),
            low=Decimal(str(min(float(b.low) for b in regular))),
            close=Decimal(str(regular[-1].close)),
            volume=int(sum(int(b.volume or 0) for b in regular)),
        )
        if last_daily == intraday_day:
            bars[-1] = synth
        else:
            bars.append(synth)
        out.session_date = intraday_day
        out.day_high = float(synth.high)
        out.day_low = float(synth.low)
        out.session_volume = synth.volume
        first_ts = to_et(regular[0].timestamp)
        or_bars = [
            b
            for b in regular
            if (to_et(b.timestamp) - first_ts).total_seconds() < opening_range_minutes * 60
        ]
        if or_bars:
            out.opening_range_high = max(float(b.high) for b in or_bars)
            out.opening_range_low = min(float(b.low) for b in or_bars)
        last_t = to_et(regular[-1].timestamp).time()
        out.phase = "regular" if last_t < time(15, 55) else "closed"
        prev = bars[-2] if len(bars) >= 2 else None
        out.prev_close = float(prev.close) if prev is not None else None
        ref_price = float(synth.close)
    elif pre and (last_daily is None or (intraday_day and intraday_day > last_daily)):
        # Premarket: today's daily bar does not exist yet.
        out.phase = "premarket"
        out.session_date = intraday_day
        out.prev_close = float(bars[-1].close) if bars else None
        ref_price = price or float(pre[-1].close)
        out.day_high = max(float(b.high) for b in pre)
        out.day_low = min(float(b.low) for b in pre)
        out.session_volume = out.premarket_volume
    else:
        prev = bars[-2] if len(bars) >= 2 else None
        out.prev_close = float(prev.close) if prev is not None else None
        ref_price = float(bars[-1].close) if bars else price
        if bars:
            out.day_high = float(bars[-1].high)
            out.day_low = float(bars[-1].low)
            out.session_volume = int(bars[-1].volume or 0)

    if out.prev_close and out.prev_close > 0 and ref_price:
        out.change_pct = (ref_price - out.prev_close) / out.prev_close * 100
    return out
