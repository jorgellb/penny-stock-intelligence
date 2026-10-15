"""Integration: accumulation engine live inside the monitor."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pytest

from app.domain.models import DailyBar, DataProvider, Quote
from app.jobs.monitor import MonitorService


class AccumulationTapeProvider:
    """Flat price, upper-range closes, 4x volume tail, full turnover."""

    def __init__(self, climax: bool = False) -> None:
        rng = np.random.default_rng(11)
        n = 30
        base = 2.0 + rng.normal(0, 0.004, n)
        highs = base + 0.03
        lows = base - 0.03
        closes = lows + 0.054
        volumes = np.full(n, 500_000.0)
        volumes[-5:] = 2_000_000.0
        if climax:
            closes = np.concatenate([np.full(29, 2.0), [2.8]])
            highs = np.concatenate([np.full(29, 2.05), [2.85]])
            lows = np.concatenate([np.full(29, 1.95), [2.0]])
            volumes = np.full(30, 500_000.0)
            volumes[-1] = 8_000_000.0
        start = datetime.now(UTC) - timedelta(days=29)
        self._bars = [
            DailyBar(
                symbol="ABCD",
                date=start + timedelta(days=i),
                open=Decimal(str(float(closes[i]))),
                high=Decimal(str(float(highs[i]))),
                low=Decimal(str(float(lows[i]))),
                close=Decimal(str(float(closes[i]))),
                volume=int(volumes[i]),
                provider=DataProvider.YFINANCE,
            )
            for i in range(30)
        ]

    async def get_quote(self, symbol: str):  # type: ignore[no-untyped-def]
        return Quote(
            symbol=symbol,
            bid=Decimal("2.01"),
            ask=Decimal("2.03"),
            last=Decimal("2.02"),
            timestamp=datetime.now(UTC),
            provider=DataProvider.YFINANCE,
        )

    async def get_daily_bars(self, symbol: str, start):  # type: ignore[no-untyped-def]
        return self._bars


class StubFundamentals:
    def __init__(self, float_shares: float | None = 10_000_000.0) -> None:
        self.calls = 0
        self._float = float_shares

    async def get_share_statistics(self, symbol: str):  # type: ignore[no-untyped-def]
        from app.domain.models import ShareStatistics

        self.calls += 1
        return ShareStatistics(
            symbol=symbol,
            date=datetime.now(UTC),
            shares_outstanding=30_000_000,
            float_shares=int(self._float) if self._float else None,
            provider=DataProvider.YFINANCE,
        )

    async def get_fundamentals(self, symbol: str, period_type: str = "ttm"):  # type: ignore[no-untyped-def]
        return None


@pytest.mark.asyncio
async def test_monitor_detects_accumulation_live() -> None:
    svc = MonitorService(
        market_data_provider=AccumulationTapeProvider(),
        fundamentals_provider=StubFundamentals(),
    )
    _, details = await svc.evaluate_symbol("ABCD")
    acc = details["accumulation"]
    assert acc is not None and acc["score"] >= 60
    assert details["climax"] is None
    assert details["markup_ready"] is False


@pytest.mark.asyncio
async def test_monitor_flags_climax() -> None:
    svc = MonitorService(
        market_data_provider=AccumulationTapeProvider(climax=True),
        fundamentals_provider=StubFundamentals(),
    )
    event, details = await svc.evaluate_symbol("ABCD")
    assert details["climax"] is not None
    assert any("clímax" in r for r in event.reasons)


@pytest.mark.asyncio
async def test_float_skipped_when_quiet() -> None:
    fund = StubFundamentals()
    svc = MonitorService(
        market_data_provider=AccumulationTapeProvider(), fundamentals_provider=fund
    )
    await svc.evaluate_symbol("ABCD")
    assert fund.calls >= 1  # tape is hot (RVOL tail), float fetched
    assert await svc._fetch_float("ABCD", rvol=0.5) is None  # quiet: skipped
