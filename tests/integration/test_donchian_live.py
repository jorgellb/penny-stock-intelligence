"""Integration: live Donchian gate with stub news + AI providers."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.domain.models import (
    CatalystCategory,
    DailyBar,
    DataProvider,
    ImpactLevel,
    NewsAnalysis,
    NewsArticle,
    Sentiment,
    TimeHorizon,
)
from app.jobs.monitor import MonitorService


class BreakoutBarsProvider:
    """29 calm bars + one breakout bar on huge volume."""

    def __init__(self, close: float = 2.60) -> None:
        self.close = close
        bars = []
        base = datetime.now(UTC) - timedelta(days=29)
        for i in range(29):
            price = 1.0 + i * 0.05
            bars.append(
                DailyBar(
                    symbol="ABCD",
                    date=base + timedelta(days=i),
                    open=Decimal(str(price)),
                    high=Decimal(str(price + 0.05)),
                    low=Decimal(str(price - 0.05)),
                    close=Decimal(str(price)),
                    volume=500_000,
                    provider=DataProvider.YFINANCE,
                )
            )
        bars.append(
            DailyBar(
                symbol="ABCD",
                date=base + timedelta(days=29),
                open=Decimal("2.45"),
                high=Decimal(str(close)),
                low=Decimal("2.40"),
                close=Decimal(str(close)),
                volume=10_000_000,
                provider=DataProvider.YFINANCE,
            )
        )
        self._bars = bars

    async def get_quote(self, symbol: str):  # type: ignore[no-untyped-def]
        from app.domain.models import Quote

        return Quote(
            symbol=symbol,
            bid=Decimal("2.59"),
            ask=Decimal("2.61"),
            last=Decimal(str(self.close)),
            timestamp=datetime.now(UTC),
            provider=DataProvider.YFINANCE,
        )

    async def get_daily_bars(self, symbol: str, start):  # type: ignore[no-untyped-def]
        return self._bars


class StubNewsProvider:
    def __init__(self, articles: list) -> None:
        self._articles = articles

    async def get_news(self, symbols=None, start=None, limit: int = 100):  # type: ignore[no-untyped-def]
        return [a for a in self._articles if symbols is None or a.symbol in symbols][:limit]


class StubAIProvider:
    async def analyze_news(self, article: NewsArticle) -> NewsAnalysis:
        return NewsAnalysis(
            article_id=article.id,
            symbol=article.symbol,
            category=CatalystCategory.FDA,
            sentiment=Sentiment.POSITIVE,
            impact=ImpactLevel.HIGH,
            time_horizon=TimeHorizon.SHORT_TERM,
            is_material=True,
            is_primary_source=True,
            confidence=0.9,
            summary="FDA approval",
            provider=DataProvider.OPENAI,
            model="stub",
        )


def _article(hours_ago: float = 2.0) -> NewsArticle:
    return NewsArticle(
        symbol="ABCD",
        headline="ABCD receives FDA approval",
        source="Company PR",
        url="https://example.com/pr",
        published_at=datetime.now(UTC) - timedelta(hours=hours_ago),
        provider=DataProvider.FINNHUB,
    )


@pytest.mark.asyncio
async def test_donchian_gate_passes_live() -> None:
    svc = MonitorService(
        market_data_provider=BreakoutBarsProvider(),
        news_provider=StubNewsProvider([_article()]),
        ai_provider=StubAIProvider(),
    )
    event, details = await svc.evaluate_symbol("ABCD")
    assert details["donchian_gate"] is True
    assert details["catalyst"] is not None
    assert details["catalyst"]["impact"] == "high"
    assert any("Donchian" in r for r in event.reasons)


@pytest.mark.asyncio
async def test_no_news_means_gate_skipped() -> None:
    svc = MonitorService(market_data_provider=BreakoutBarsProvider())
    _, details = await svc.evaluate_symbol("ABCD")
    assert details["donchian_gate"] is None
    assert details["catalyst"] is None


@pytest.mark.asyncio
async def test_heuristic_fallback_when_ai_missing() -> None:
    svc = MonitorService(
        market_data_provider=BreakoutBarsProvider(),
        news_provider=StubNewsProvider([_article()]),
        ai_provider=None,  # heuristic path
    )
    _, details = await svc.evaluate_symbol("ABCD")
    assert details["catalyst"] is not None
    assert details["catalyst"]["impact"] == "high"
    # heuristic is not a primary source -> gate stays closed
    assert details["donchian_gate"] is False


@pytest.mark.asyncio
async def test_low_rvol_skips_ai_cost() -> None:
    calls: list[str] = []

    class CountingAI(StubAIProvider):
        async def analyze_news(self, article: NewsArticle) -> NewsAnalysis:
            calls.append(article.symbol)
            return await super().analyze_news(article)

    class CalmProvider(BreakoutBarsProvider):
        async def get_daily_bars(self, symbol: str, start):  # type: ignore[no-untyped-def]
            bars = list(self._bars)
            calm = bars[-1].model_copy(update={"volume": 100_000})
            return bars[:-1] + [calm]

    svc = MonitorService(
        market_data_provider=CalmProvider(),
        news_provider=StubNewsProvider([_article()]),
        ai_provider=CountingAI(),
    )
    await svc.evaluate_symbol("ABCD")
    assert calls == []  # RVOL too low -> no AI call
