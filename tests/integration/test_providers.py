"""Integration tests for providers using mocks + recorded fixtures (no real APIs)."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.domain.models import (
    DataProvider,
    Filing,
    FilingType,
    NewsArticle,
)
from app.providers.ai import MockAIProvider
from app.providers.fundamentals import MockFundamentalsProvider
from app.providers.market_data import MockMarketDataProvider


@pytest.mark.asyncio
async def test_mock_market_data_quote() -> None:
    p = MockMarketDataProvider()
    assert await p.health_check() is True
    p.set_quote("ABCD", 2.20)
    q = await p.get_quote("ABCD")
    assert q.symbol == "ABCD"
    assert q.last == Decimal("2.20")
    assert q.mid == Decimal("2.20")
    assert q.provider == DataProvider.YFINANCE


@pytest.mark.asyncio
async def test_mock_market_data_daily_bars() -> None:
    from datetime import timedelta

    p = MockMarketDataProvider()
    bars = await p.get_daily_bars("ABCD", start=datetime.now(UTC) - timedelta(days=30))
    assert len(bars) == 30
    assert bars[0].symbol == "ABCD"
    assert bars[0].volume > 0


@pytest.mark.asyncio
async def test_mock_fundamentals() -> None:
    p = MockFundamentalsProvider()
    assert await p.health_check() is True
    f = await p.get_fundamentals("ABCD")
    assert f is not None
    assert f.symbol == "ABCD"
    assert f.market_cap == Decimal(72_000_000)
    assert f.cash_runway_months is not None
    stats = await p.get_share_statistics("ABCD")
    assert stats is not None
    assert stats.shares_outstanding == 31_000_000


@pytest.mark.asyncio
async def test_mock_ai_news_analysis() -> None:
    p = MockAIProvider()
    assert await p.health_check() is True
    article = NewsArticle(
        symbol="ABCD",
        headline="ABCD announces contract",
        source="Test",
        url="https://example.com/1",
        published_at=datetime.now(UTC),
        provider=DataProvider.FINNHUB,
    )
    analysis = await p.analyze_news(article)
    assert analysis.symbol == "ABCD"
    assert 0.0 <= analysis.confidence <= 1.0


@pytest.mark.asyncio
async def test_mock_ai_filing_analysis() -> None:
    p = MockAIProvider()
    filing = Filing(
        symbol="ABCD",
        cik="0001234567",
        accession_number="0001234567-26-000001",
        filing_type=FilingType.S_1,
        filing_date=datetime.now(UTC),
        accepted_at=datetime.now(UTC),
        url="https://example.com/filing",
        provider=DataProvider.SEC_EDGAR,
    )
    analysis = await p.analyze_filing(filing, "excerpt")
    assert analysis.symbol == "ABCD"
    assert analysis.confidence == "low"


@pytest.mark.asyncio
async def test_sec_edgar_fail_soft(monkeypatch: pytest.MonkeyPatch) -> None:
    """SEC provider must fail soft (empty list / bool), never raise."""
    import httpx

    from app.providers.sec import SecEdgarProvider

    class _Boom:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise httpx.ConnectError("no network in tests")

    monkeypatch.setattr(httpx, "AsyncClient", _Boom)
    p = SecEdgarProvider()
    assert await p.health_check() is False
    assert await p.get_filings("ABCD", limit=5) == []
    assert await p.get_corporate_actions("ABCD") == []
