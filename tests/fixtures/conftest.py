"""Test fixtures for the Penny Stock Intelligence Engine."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest


@pytest.fixture
def sample_security():
    """Sample security data."""
    return {
        "symbol": "ABCD",
        "name": "ABCD Inc",
        "exchange": "NASDAQ",
        "is_etf": False,
        "is_preferred": False,
        "is_warrant": False,
        "is_spac_unit": False,
        "is_fund": False,
        "is_active": True,
    }


@pytest.fixture
def sample_quote():
    """Sample quote data."""
    return {
        "symbol": "ABCD",
        "bid": Decimal("1.81"),
        "ask": Decimal("1.83"),
        "last": Decimal("1.82"),
        "timestamp": datetime.now(UTC),
        "provider": "yfinance",
    }


@pytest.fixture
def sample_fundamentals():
    """Sample fundamentals data."""
    return {
        "symbol": "ABCD",
        "period_end": datetime.now(UTC),
        "period_type": "ttm",
        "market_cap": 72000000,
        "shares_outstanding": 31000000,
        "float_shares": 18200000,
        "revenue": 15000000,
        "net_income": -2000000,
        "cash": 18000000,
        "total_debt": 7000000,
        "operating_cash_flow": -800000,
        "free_cash_flow": -1000000,
        "revenue_yoy_growth": 0.15,
        "data_quality_score": 0.7,
    }


@pytest.fixture
def sample_technical_indicators():
    """Sample technical indicators."""
    return {
        "symbol": "ABCD",
        "timestamp": datetime.now(UTC),
        "ema_5": 1.80,
        "ema_9": 1.78,
        "ema_20": 1.75,
        "rsi_14": 67.0,
        "atr_14": 0.215,
        "atr_pct": 11.8,
        "vwap": 1.81,
        "vwap_distance_pct": 0.55,
        "rvol_daily": 5.8,
        "gap_pct": 8.3,
        "change_pct": 14.7,
        "dollar_volume": 22600000,
        "volume": 12400000,
    }


@pytest.fixture
def sample_daily_bars():
    """Sample daily bars."""
    bars = []
    base_price = 1.50
    for i in range(30):
        bars.append(
            {
                "symbol": "ABCD",
                "date": datetime.now(UTC) - timedelta(days=29 - i),
                "open": base_price + i * 0.02,
                "high": base_price + i * 0.02 + 0.10,
                "low": base_price + i * 0.02 - 0.05,
                "close": base_price + i * 0.03,
                "volume": 500000 + i * 100000,
            }
        )
    return bars


@pytest.fixture
def sample_news_article():
    """Sample news article."""
    return {
        "id": "test-uuid-1",
        "symbol": "ABCD",
        "headline": "ABCD Inc announces major contract win",
        "summary": "The company has been awarded a multi-million dollar government contract.",
        "source": "Reuters",
        "url": "https://example.com/news/1",
        "published_at": datetime.now(UTC),
        "category": "contract",
        "sentiment": "positive",
        "impact": "high",
    }


@pytest.fixture
def sample_case_momentum():
    """Test case A: Momentum healthy."""
    return {
        "price": 2.20,
        "rvol": 6.0,
        "liquidity": "high",
        "spread": 0.01,
        "catalyst": "strong",
        "offering": False,
    }


@pytest.fixture
def sample_case_dilution():
    """Test case B: Dilution trap."""
    return {
        "price": 2.80,
        "rvol": 10.0,
        "change_pct": 40.0,
        "offering": True,
        "atm": True,
        "shares_change": 70.0,
    }


@pytest.fixture
def sample_case_illiquid():
    """Test case C: Illiquid."""
    return {
        "price": 0.50,
        "change_pct": 80.0,
        "volume": 1000,
        "spread": 18.0,
    }


@pytest.fixture
def sample_case_no_catalyst():
    """Test case D: No catalyst."""
    return {
        "price": 1.50,
        "change_pct": 5.0,
        "news": False,
        "filings": False,
    }


@pytest.fixture
def sample_case_insufficient_data():
    """Test case E: Insufficient data."""
    return {
        "price": 1.00,
        "data_quality": "low",
        "missing": ["float", "spread", "fundamentals"],
    }


@pytest.fixture
def mock_db_session():
    """Mock database session fixture."""
    yield {}
