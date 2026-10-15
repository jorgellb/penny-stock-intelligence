"""Fundamentals providers: yfinance + mock with deterministic fallback."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.domain.models import DataProvider, Fundamentals, ShareStatistics


def _fund_ttl() -> float:
    try:
        from app.config import get_settings

        return float(get_settings().providers.fundamentals.cache_ttl_seconds)
    except Exception:
        return 3600.0


class YFinanceFundamentalsProvider:
    """yfinance `.info` fundamentals.

    `.info` is slow (~1s) and blocking: it runs in a worker thread and is
    cached per symbol (fundamentals change quarterly, not per minute).
    Failures are cached briefly too so a dead symbol is not hammered.
    """

    _NEG_TTL = 300.0

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, Fundamentals | None]] = {}

    @property
    def name(self) -> DataProvider:
        return DataProvider.YFINANCE

    @property
    def rate_limit_per_minute(self) -> int:
        return 60

    async def health_check(self) -> bool:
        try:
            import yfinance  # type: ignore[import-not-found]

            t = yfinance.Ticker("AAPL")
            _ = t.info
            return True
        except Exception:
            return False

    async def get_fundamentals(self, symbol: str, period_type: str = "ttm") -> Fundamentals | None:
        sym = symbol.upper()
        cache = getattr(self, "_cache", None)
        if cache is None:
            cache = self._cache = {}
        hit = cache.get(sym)
        if hit is not None:
            ts, cached = hit
            ttl = _fund_ttl() if cached is not None else self._NEG_TTL
            if time.monotonic() - ts <= ttl:
                return cached
        result = await self._fetch_fundamentals(sym, period_type)
        cache[sym] = (time.monotonic(), result)
        return result

    async def _fetch_fundamentals(self, symbol: str, period_type: str) -> Fundamentals | None:
        try:
            import yfinance

            info: dict[str, Any] = await asyncio.to_thread(
                lambda: yfinance.Ticker(symbol).info or {}
            )
            if not info or (
                info.get("marketCap") is None and info.get("sharesOutstanding") is None
            ):
                return None
            return Fundamentals(
                symbol=symbol,
                period_end=datetime.now(UTC),
                period_type=period_type,
                market_cap=info.get("marketCap"),
                enterprise_value=info.get("enterpriseValue"),
                shares_outstanding=info.get("sharesOutstanding"),
                float_shares=info.get("floatShares"),
                insider_ownership_pct=(info.get("heldPercentInsiders") or 0) * 100
                if info.get("heldPercentInsiders")
                else None,
                institutional_ownership_pct=(info.get("heldPercentInstitutions") or 0) * 100
                if info.get("heldPercentInstitutions")
                else None,
                revenue=info.get("totalRevenue"),
                gross_profit=info.get("grossProfits"),
                operating_income=info.get("operatingIncome"),
                net_income=info.get("netIncomeToCommon"),
                eps_diluted=info.get("trailingEps"),
                cash=info.get("totalCash"),
                total_cash=info.get("totalCash"),
                total_debt=info.get("totalDebt"),
                operating_cash_flow=info.get("operatingCashflow"),
                free_cash_flow=info.get("freeCashflow"),
                revenue_yoy_growth=info.get("revenueGrowth"),
                data_quality_score=0.6,
                provider=DataProvider.YFINANCE,
            )
        except Exception:
            return None

    async def get_fundamentals_batch(
        self, symbols: list[str], period_type: str = "ttm"
    ) -> dict[str, Fundamentals]:
        out: dict[str, Fundamentals] = {}
        for s in symbols:
            f = await self.get_fundamentals(s, period_type)
            if f is not None:
                out[s] = f
        return out

    async def get_share_statistics(self, symbol: str) -> ShareStatistics | None:
        f = await self.get_fundamentals(symbol)
        if f is None:
            return None
        return ShareStatistics(
            symbol=symbol,
            date=datetime.now(UTC),
            shares_outstanding=f.shares_outstanding,
            float_shares=f.float_shares,
            provider=DataProvider.YFINANCE,
        )

    async def get_share_statistics_batch(self, symbols: list[str]) -> dict[str, ShareStatistics]:
        out: dict[str, ShareStatistics] = {}
        for s in symbols:
            v = await self.get_share_statistics(s)
            if v is not None:
                out[s] = v
        return out


class MockFundamentalsProvider(YFinanceFundamentalsProvider):
    @property
    def name(self) -> DataProvider:
        return DataProvider.YFINANCE

    async def health_check(self) -> bool:
        return True

    async def get_fundamentals(self, symbol: str, period_type: str = "ttm") -> Fundamentals | None:
        return Fundamentals(
            symbol=symbol,
            period_end=datetime.now(UTC),
            period_type=period_type,
            market_cap=Decimal(72_000_000),
            shares_outstanding=31_000_000,
            float_shares=18_200_000,
            revenue=Decimal(15_000_000),
            net_income=Decimal(-2_000_000),
            cash=Decimal(18_000_000),
            total_cash=Decimal(18_000_000),
            total_debt=Decimal(7_000_000),
            operating_cash_flow=Decimal(-800_000),
            free_cash_flow=Decimal(-1_000_000),
            revenue_yoy_growth=0.15,
            data_quality_score=0.7,
            provider=DataProvider.YFINANCE,
        )
