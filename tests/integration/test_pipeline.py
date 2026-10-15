"""Pipeline integration: universe -> scanners -> risk -> scoring -> alerts."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.alerts import AlertEngine, ConsoleAlertProvider
from app.backtesting import BacktestConfig, Trade, apply_costs, summarize
from app.core.market_calendar import market_session
from app.domain.models import (
    DataProvider,
    Fundamentals,
    Quote,
    RiskFlag,
    RiskFlagType,
    RiskSeverity,
)
from app.scanners.gap import gap_percent, rank_intraday, rank_premarket
from app.scanners.universe import UniverseEngine
from app.scoring import ScoringEngine
from app.scoring.dilution import DilutionEngine
from app.scoring.risk import RiskEngine


def test_universe_filter_reasons() -> None:
    eng = UniverseEngine()
    ok = eng.get_filter_result(
        symbol="ABCD", price=2.20, volume=600_000, spread_pct=1.0, exchange="NASDAQ"
    )
    assert ok.eligible is True
    assert ok.reasons == []
    assert ok.dollar_volume == pytest.approx(2.20 * 600_000)
    bad = eng.get_filter_result(
        symbol="XYZ", price=0.05, volume=100, spread_pct=18.0, exchange="OTC"
    )
    assert bad.eligible is False
    assert "below_min_price" in bad.reasons
    assert "avg_daily_volume_below_threshold" in bad.reasons
    assert "spread_too_wide" in bad.reasons
    # OTC must not be mislabeled as ETF
    assert "etf_excluded" not in bad.reasons
    thin = eng.get_filter_result(
        symbol="THIN", price=1.0, volume=600_000, spread_pct=1.0, exchange="NASDAQ"
    )
    assert thin.eligible is False
    assert "dollar_volume_below_threshold" in thin.reasons


def test_gap_and_ranking() -> None:
    assert gap_percent(1.00, 1.10) == pytest.approx(10.0)
    rows = [
        {
            "symbol": "ABCD",
            "price": 2.20,
            "gap_pct": 8.0,
            "rvol": 5.8,
            "dollar_volume": 22_600_000,
            "catalyst_strength": "strong",
        }
    ]
    ranked = rank_premarket(rows)
    assert ranked[0].symbol == "ABCD"
    assert ranked[0].score == 100
    intra = rank_intraday(
        [
            {
                "symbol": "ABCD",
                "price": 2.20,
                "vwap_distance_pct": 0.5,
                "rvol": 3.0,
                "breakout_20d": True,
                "rsi14": 67.0,
                "dollar_volume": 1_000_000,
            }
        ]
    )
    assert intra[0].score == 90


def test_case_a_momentum_healthy_scores_high() -> None:
    """Plan Case A: strong momentum, no offering -> high score."""
    eng = ScoringEngine()
    score = eng.score_security(
        rvol=6.0,
        catalyst_strength="strong",
        momentum_score=85.0,
        technical_score=75.0,
        liquidity_score=90.0,
        fundamentals_score=60.0,
        data_quality_score=80.0,
        risk_flags=[],
    )
    assert score.final_score > 50
    text = eng.generate_score_explanation(score)
    assert "probability forecast" in text


def test_case_b_dilution_trap_penalized() -> None:
    """Plan Case B: +40%, RVOL 10, offering + ATM + dilution -> heavy penalty."""
    eng = ScoringEngine()
    flags = [
        RiskFlag(
            symbol="ABCD",
            flag_type=RiskFlagType.RECENT_OFFERING,
            severity=RiskSeverity.HIGH,
            source=DataProvider.SEC_EDGAR,
            explanation="offering",
            score_penalty=20,
        ),
        RiskFlag(
            symbol="ABCD",
            flag_type=RiskFlagType.ACTIVE_ATM,
            severity=RiskSeverity.HIGH,
            source=DataProvider.SEC_EDGAR,
            explanation="atm",
            score_penalty=20,
        ),
        RiskFlag(
            symbol="ABCD",
            flag_type=RiskFlagType.SHARE_DILUTION,
            severity=RiskSeverity.HIGH,
            source=DataProvider.SEC_EDGAR,
            explanation="dilution",
            score_penalty=25,
        ),
    ]
    score = eng.score_security(
        rvol=10.0,
        catalyst_strength="strong",
        momentum_score=90.0,
        technical_score=80.0,
        data_quality_score=60.0,
        risk_flags=flags,
    )
    assert score.risk_penalty == 65
    assert score.final_score < score.raw_score


def test_case_c_illiquid_penalized() -> None:
    """Plan Case C: +80% on tiny volume, 18% spread -> wide-spread flag."""
    eng = RiskEngine()
    quote = Quote(
        symbol="XYZ",
        bid=Decimal("0.41"),
        ask=Decimal("0.50"),
        timestamp=datetime.now(UTC),
        provider=DataProvider.YFINANCE,
    )
    assessment = eng.assess(symbol="XYZ", quote=quote)
    assert any(f.flag_type == RiskFlagType.WIDE_SPREAD for f in assessment.flags)


def test_dilution_share_changes() -> None:
    eng = DilutionEngine()
    now = datetime.now(UTC)
    from datetime import timedelta

    history = [(now - timedelta(days=d), shares) for d, shares in [(100, 20_000_000)]]
    out = eng.analyze_share_changes(31_000_000, history)
    assert out["changes"]["shares_outstanding_change_90d"] == pytest.approx(55.0)


def test_cash_runway_low_flag() -> None:
    eng = RiskEngine()
    fund = Fundamentals(
        symbol="ABCD",
        period_end=datetime.now(UTC),
        period_type="ttm",
        total_cash=Decimal(1_000_000),
        operating_cash_flow=Decimal(-1_000_000),
        provider=DataProvider.YFINANCE,
    )
    assessment = eng.assess(symbol="ABCD", fundamentals=fund)
    assert any(f.flag_type == RiskFlagType.LOW_CASH_RUNWAY for f in assessment.flags)


@pytest.mark.asyncio
async def test_alert_cooldown_and_console() -> None:
    eng = AlertEngine()
    assert eng.should_send("ABCD", 80) is True
    eng.mark_sent("ABCD", 80)
    assert eng.should_send("ABCD", 81) is False  # cooldown, small delta
    assert eng.should_send("ABCD", 95) is True  # big delta re-alerts
    assert eng.should_send("XYZ", 10) is False  # below minimum
    msg = eng.format_alert("ABCD", 2.20, 80, catalyst="contract")
    assert "not a probability forecast" in msg
    provider = ConsoleAlertProvider()
    assert await provider.health_check() is True


def test_backtest_helpers() -> None:
    cfg = BacktestConfig()
    assert apply_costs(100.0, "buy", cfg) > 100.0
    assert apply_costs(100.0, "sell", cfg) < 100.0
    now = datetime.now(UTC)
    trades = [
        Trade(symbol="A", entry_date=now, entry_price=1.0, exit_price=1.2, score_at_entry=80),
        Trade(symbol="B", entry_date=now, entry_price=1.0, exit_price=0.9, score_at_entry=75),
    ]
    m = summarize(trades)
    assert m["number_of_signals"] == 2
    assert m["win_rate"] == pytest.approx(50.0)


def test_market_calendar_and_cache() -> None:
    assert market_session() is not None
    from app.core.cache import Cache

    c = Cache()
    assert c.get("missing") is None
    c.set("k", {"a": 1}, ttl=60)
    assert c.get("k") == {"a": 1}
