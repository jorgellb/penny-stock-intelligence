"""Integration tests."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.config import get_settings
from app.core.database import DatabaseManager
from app.domain.models import Quote, Security


class TestDatabase:
    """Database integration tests."""

    @pytest.mark.asyncio
    async def test_create_tables(self, tmp_path):
        """Test that tables can be created."""
        db = DatabaseManager(database_url=f"sqlite+aiosqlite:///{tmp_path}/d.db")
        await db.create_tables()
        # If no exception, tables were created successfully
        assert True
        await db.close()

    @pytest.mark.asyncio
    async def test_session(self, tmp_path):
        """Test database session."""
        db = DatabaseManager(database_url=f"sqlite+aiosqlite:///{tmp_path}/s.db")
        async with db.session() as session:
            assert session is not None
        await db.close()


class TestConfig:
    """Configuration tests."""

    def test_settings_load(self):
        """Test settings load correctly."""
        settings = get_settings()
        assert settings.universe.min_price == 0.10
        assert settings.universe.max_price == 5.00
        assert len(settings.universe.exchanges) == 3

    def test_scoring_weights(self):
        """Test scoring weights."""
        settings = get_settings()
        assert settings.scoring.weights.momentum == 20
        assert settings.scoring.weights.volume == 20
        assert settings.scoring.weights.catalyst == 20

    def test_risk_config(self):
        """Test risk configuration."""
        settings = get_settings()
        assert settings.risk.low_float_max == 20000000
        assert settings.risk.micro_float_max == 5000000

    def test_paper_mode(self):
        """Test paper mode is enabled."""
        settings = get_settings()
        assert settings.paper_mode is True


class TestDomainModels:
    """Domain model tests."""

    def test_security_creation(self):
        """Test Security model."""
        from app.domain.models import Exchange

        sec = Security(symbol="ABCD", exchange=Exchange.NASDAQ)
        assert sec.symbol == "ABCD"
        assert sec.exchange == Exchange.NASDAQ

    def test_quote_calculations(self):
        """Test Quote computed fields."""
        from app.domain.models import DataProvider

        quote = Quote(
            symbol="ABCD",
            bid=Decimal("1.81"),
            ask=Decimal("1.83"),
            timestamp=datetime.now(UTC),
            provider=DataProvider.YFINANCE,
        )
        assert quote.mid == Decimal("1.82")
        assert quote.spread_absolute == Decimal("0.02")
        assert abs(quote.spread_pct - 1.0989) < 0.01

    def test_fundamentals_cash_runway(self):
        """Test cash runway calculation."""
        from app.domain.models import DataProvider, Fundamentals

        fund = Fundamentals(
            symbol="ABCD",
            period_end=datetime.now(UTC),
            period_type="ttm",
            total_cash=18000000,
            operating_cash_flow=-800000,
            provider=DataProvider.YFINANCE,
        )
        assert fund.cash_runway_months is not None
        assert fund.cash_runway_months > 0

    def test_score_breakdown(self):
        """Test score breakdown."""
        from app.domain.models import ScoreBreakdown

        breakdown = ScoreBreakdown(
            momentum=18,
            volume=19,
            catalyst=17,
            technical=12,
            liquidity=8,
            fundamentals=6,
            data_quality=4,
            raw_score=84,
        )
        assert breakdown.raw_score == 84
        assert breakdown.total_penalty == 0
        assert breakdown.final_score == 84
