"""Unit tests for scoring engine."""

import pytest

from app.domain.models import DataProvider, RiskFlag, RiskFlagType, RiskSeverity
from app.scoring import ScoringEngine


class TestScoringEngine:
    """Tests for ScoringEngine."""

    @pytest.fixture(autouse=True)
    def setup_engine(self):
        """Set up scoring engine."""
        self.engine = ScoringEngine()

    def test_raw_score_momentum(self):
        """Test momentum scoring."""
        score = self.engine.compute_raw_score(
            momentum_score=80.0,
        )
        assert score.momentum > 0
        assert score.raw_score >= score.momentum

    def test_raw_score_volume(self):
        """Test volume scoring."""
        score = self.engine.compute_raw_score(
            rvol=3.0,
        )
        assert score.volume > 0

    def test_raw_score_catalyst(self):
        """Test catalyst scoring."""
        score = self.engine.compute_raw_score(
            catalyst_strength="strong",
        )
        assert score.catalyst > 0

    def test_raw_score_full(self):
        """Test full raw score computation."""
        score = self.engine.compute_raw_score(
            rvol=5.0,
            catalyst_strength="strong",
            momentum_score=80.0,
            technical_score=70.0,
            liquidity_score=80.0,
            fundamentals_score=60.0,
            data_quality_score=80.0,
        )
        assert score.raw_score > 0
        assert score.raw_score <= 100

    def test_final_score_with_penalties(self):
        """Test final score with risk penalties."""
        flags = [
            RiskFlag(
                symbol="ABCD",
                flag_type=RiskFlagType.RECENT_OFFERING,
                severity=RiskSeverity.HIGH,
                source=DataProvider.YFINANCE,
                explanation="Recent offering detected",
                score_penalty=20,
            ),
        ]
        score = self.engine.compute_final_score(
            self.engine.compute_raw_score(
                rvol=5.0,
                catalyst_strength="strong",
                momentum_score=80.0,
                technical_score=70.0,
                liquidity_score=80.0,
                fundamentals_score=60.0,
                data_quality_score=80.0,
            ),
            flags,
        )
        assert score.final_score < score.raw_score
        assert score.penalties["RECENT_OFFERING"] == 20

    def test_score_zero_penalty(self):
        """Test score with no penalties."""
        score = self.engine.compute_final_score(
            self.engine.compute_raw_score(
                rvol=5.0,
                catalyst_strength="strong",
                momentum_score=80.0,
                technical_score=70.0,
                liquidity_score=80.0,
                fundamentals_score=60.0,
                data_quality_score=80.0,
            ),
            [],
        )
        assert score.final_score == score.raw_score

    def test_score_minimum_zero(self):
        """Test score doesn't go below zero."""
        flags = [
            RiskFlag(
                symbol="ABCD",
                flag_type=RiskFlagType.TRADING_HALT,
                severity=RiskSeverity.CRITICAL,
                source=DataProvider.YFINANCE,
                explanation="Trading halt",
                score_penalty=50,
            )
        ] * 3
        score = self.engine.compute_final_score(
            self.engine.compute_raw_score(
                rvol=1.0,
                catalyst_strength="none",
                data_quality_score=20.0,
            ),
            flags,
        )
        assert score.final_score >= 0

    def test_score_explanation(self):
        """Test score explanation."""
        score = self.engine.compute_final_score(
            self.engine.compute_raw_score(
                rvol=5.0,
                catalyst_strength="strong",
                momentum_score=80.0,
                data_quality_score=80.0,
            ),
            [],
        )
        explanation = self.engine.generate_score_explanation(score)
        assert "Base score" in explanation
        assert "FINAL" in explanation
        assert "probability forecast" in explanation

    def test_case_momentum_healthy(self):
        """Test Case A: Momentum healthy should have high score."""
        score = self.engine.compute_final_score(
            self.engine.compute_raw_score(
                rvol=6.0,
                catalyst_strength="strong",
                momentum_score=85.0,
                technical_score=75.0,
                liquidity_score=90.0,
                fundamentals_score=60.0,
                data_quality_score=80.0,
            ),
            [],
        )
        # Should have relatively high score
        assert score.final_score > 50

    def test_case_dilution_trap(self):
        """Test Case B: Dilution trap should have penalties."""
        flags = [
            RiskFlag(
                symbol="ABCD",
                flag_type=RiskFlagType.RECENT_OFFERING,
                severity=RiskSeverity.HIGH,
                source=DataProvider.YFINANCE,
                explanation="Recent offering",
                score_penalty=20,
            ),
            RiskFlag(
                symbol="ABCD",
                flag_type=RiskFlagType.SHARE_DILUTION,
                severity=RiskSeverity.HIGH,
                source=DataProvider.YFINANCE,
                explanation="Share dilution",
                score_penalty=25,
            ),
            RiskFlag(
                symbol="ABCD",
                flag_type=RiskFlagType.ACTIVE_ATM,
                severity=RiskSeverity.HIGH,
                source=DataProvider.YFINANCE,
                explanation="Active ATM",
                score_penalty=20,
            ),
        ]
        score = self.engine.compute_final_score(
            self.engine.compute_raw_score(
                rvol=10.0,
                catalyst_strength="strong",
                momentum_score=90.0,
                technical_score=80.0,
                data_quality_score=60.0,
            ),
            flags,
        )
        assert score.penalties["RECENT_OFFERING"] == 20
        assert score.penalties["SHARE_DILUTION"] == 25
        assert score.penalties["ACTIVE_ATM"] == 20
        # Score should be significantly reduced
        assert score.final_score < score.raw_score


class TestScoringConfig:
    """Tests for scoring configuration."""

    def test_weights_sum(self):
        """Test weights sum to 100."""
        from app.config import get_settings

        settings = get_settings()
        total = sum(
            [
                settings.scoring.weights.momentum,
                settings.scoring.weights.volume,
                settings.scoring.weights.catalyst,
                settings.scoring.weights.technical,
                settings.scoring.weights.liquidity,
                settings.scoring.weights.fundamentals,
                settings.scoring.weights.data_quality,
            ]
        )
        assert total == 100

    def test_default_penalties(self):
        """Test default penalties exist."""
        from app.config import get_settings

        settings = get_settings()
        assert settings.scoring.penalties.recent_offering > 0
        assert settings.scoring.penalties.dilution > 0
        assert settings.scoring.penalties.low_liquidity > 0

    def test_map_catalyst_strength(self):
        from app.scoring import map_catalyst_strength

        assert map_catalyst_strength("high") == "strong"
        assert map_catalyst_strength("MEDIUM") == "moderate"
        assert map_catalyst_strength("low") == "weak"
        assert map_catalyst_strength(None) is None
        assert map_catalyst_strength("unknown") is None

    def test_fundamentals_health_score(self):
        from datetime import UTC, datetime
        from decimal import Decimal

        from app.domain.models import DataProvider, Fundamentals
        from app.scoring import fundamentals_health_score

        assert fundamentals_health_score(None) is None
        empty = Fundamentals(
            symbol="ABCD",
            period_end=datetime.now(UTC),
            period_type="ttm",
            provider=DataProvider.YFINANCE,
        )
        assert fundamentals_health_score(empty) == 40.0

        healthy = Fundamentals(
            symbol="ABCD",
            period_end=datetime.now(UTC),
            period_type="ttm",
            provider=DataProvider.YFINANCE,
            working_capital=Decimal("1000000"),
            total_cash=Decimal("5000000"),
            operating_cash_flow=Decimal("-100000"),
            revenue_yoy_growth=0.25,
            data_quality_score=0.8,
        )
        # cash_runway = 5000000/100000 = 50 months → 100; WC 80; growth 70; dq 80
        score = fundamentals_health_score(healthy)
        assert score is not None and score > 70

    def test_data_quality_from_completeness(self):
        from app.scoring import data_quality_from_completeness

        assert data_quality_from_completeness(1.0) == 100.0
        assert data_quality_from_completeness(0.25) == 25.0
        assert data_quality_from_completeness(0.5, feed_lag_stale=True) == 35.0

    def test_float_flags_penalized(self):
        engine = ScoringEngine()
        flags = [
            RiskFlag(
                symbol="ABCD",
                flag_type=RiskFlagType.MICRO_FLOAT,
                severity=RiskSeverity.MEDIUM,
                source=DataProvider.YFINANCE,
                explanation="micro",
                score_penalty=25,
            ),
            RiskFlag(
                symbol="EFGH",
                flag_type=RiskFlagType.LOW_FLOAT,
                severity=RiskSeverity.LOW,
                source=DataProvider.YFINANCE,
                explanation="low",
                score_penalty=12,
            ),
        ]
        penalties = engine.compute_risk_penalties(flags)
        assert penalties["MICRO_FLOAT"] == engine.penalties.low_liquidity
        assert penalties["LOW_FLOAT"] == max(5, engine.penalties.low_liquidity // 2)
