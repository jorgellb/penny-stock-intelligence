"""Tests for NASDAQ/NYSE adaptation modules."""

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from app.brokers.templates import (
    MarketOrderForbiddenError,
    build_limit_template,
    build_template,
)
from app.domain.models import DataProvider, Filing, FilingType
from app.risk.circuit import CircuitBreaker
from app.risk.freeze import DilutionFreeze, DollarRuleTracker
from app.risk.halt import HaltGuardian
from app.risk.sizing import PositionSizer, SizingInput
from app.signals import SignalInput, evaluate
from app.signals.gates import (
    DonchianInput,
    ShortSqueezeGate,
    detect_squeeze,
    donchian_entry_gate,
)
from app.signals.regime import (
    MarketRegime,
    classify_regime,
    correlation_filter,
    regime_buy_thresholds,
)


def _filing(ftype: FilingType, days_ago: int, items: list | None = None) -> Filing:
    now = datetime.now(UTC)
    return Filing(
        symbol="ABCD",
        cik="0001234567",
        accession_number=f"0001-{days_ago}",
        filing_type=ftype,
        filing_date=now - timedelta(days=days_ago),
        accepted_at=now - timedelta(days=days_ago),
        url="https://example.com",
        items=items or [],
        provider=DataProvider.SEC_EDGAR,
    )


# ---- HaltGuardian ----


def test_halt_freezes_and_cools_down() -> None:
    g = HaltGuardian(cooldown_seconds=60)
    assert g.is_frozen("ABCD") is False
    g.report_limit_state("ABCD")
    assert g.is_frozen("ABCD") is True
    g.report_halt("ABCD")
    assert g.is_frozen("ABCD") is True
    assert g.penalty("ABCD") == 50
    assert "congeladas" in g.freeze_reasons("ABCD")[0]
    g.report_resume("ABCD")
    assert g.is_frozen("ABCD") is True  # cooldown
    future = datetime.now(UTC) + timedelta(seconds=61)
    assert g.is_frozen("ABCD", now=future) is False
    assert g.penalty("ABCD") == 0
    assert g.halts_today("ABCD") == 1


# ---- DilutionFreeze + DollarRule ----


def test_dilution_freeze_on_s1_and_424b5() -> None:
    fz = DilutionFreeze()
    d = fz.evaluate("ABCD", [_filing(FilingType.S_1, 5)])
    assert d.freeze_buys is True
    assert any("S-1" in r for r in d.reasons)
    d = fz.evaluate("ABCD", [_filing(FilingType.FORM_424B5, 2)])
    assert d.freeze_buys is True
    d = fz.evaluate("ABCD", [_filing(FilingType.S_1, 60)])
    assert d.freeze_buys is False  # older than freeze window
    d = fz.evaluate("ABCD", [_filing(FilingType.FORM_10K, 1)])
    assert d.freeze_buys is False


def test_dilution_freeze_on_8k_atm() -> None:
    fz = DilutionFreeze()
    d = fz.evaluate("ABCD", [_filing(FilingType.FORM_8K, 1, items=["1.01", "3.02"])])
    assert d.freeze_buys is True
    assert d.atm_active is True


def test_dollar_rule_warning_and_critical() -> None:
    t = DollarRuleTracker()
    for _ in range(90):
        st = t.update("ABCD", 0.85)
    assert st.level == "warning"
    assert t.score_penalty("ABCD") == 10
    blocked, _ = t.buy_blocked("ABCD")
    assert blocked is False
    for _ in range(60):
        st = t.update("ABCD", 0.85)
    assert st.level == "critical"
    assert t.score_penalty("ABCD") == 30
    blocked, reason = t.buy_blocked("ABCD")
    assert blocked is True
    assert "$1" in reason
    assert t.max_spread_pct("ABCD") == 2.0
    t.update("ABCD", 1.50)  # back above $1 resets
    assert t.state("ABCD").level == "ok"


# ---- Squeeze + Donchian ----


def test_detect_squeeze() -> None:
    closes = np.array([1.0, 1.15, 1.32, 1.50, 1.70])
    vols = np.array([100, 150, 200, 300, 500])
    sq = detect_squeeze(closes, vols)
    assert sq.active is True
    assert sq.parabolic_days >= 3
    flat = detect_squeeze(np.array([1.0, 1.01, 1.0, 1.01]), np.array([100, 100, 100, 100]))
    assert flat.active is False


def test_short_squeeze_gate() -> None:
    gate = ShortSqueezeGate()
    closes = np.array([1.0, 1.15, 1.32, 1.50, 1.70])
    vols = np.array([100, 150, 200, 300, 500])
    sq = detect_squeeze(closes, vols)
    d = gate.evaluate(5.0, 2.0, squeeze=sq)
    assert d.allow_contrarian_short is False
    assert d.allow_momentum_long is True
    d = gate.evaluate(35.0, 2.0, downtrend_confirmed=False)
    assert d.allow_contrarian_short is False
    d = gate.evaluate(35.0, 2.0, downtrend_confirmed=True)
    assert d.allow_contrarian_short is True
    d = gate.evaluate(5.0, 25.0)
    assert d.allow_contrarian_short is False
    d = gate.evaluate(5.0, 2.0)
    assert d.allow_contrarian_short is True


def _donchian_ok(**over: object) -> DonchianInput:
    base: dict = {
        "close": 5.10,
        "high_20d": 5.00,
        "rvol_same_time": 4.0,
        "catalyst_impact": "high",
        "catalyst_confidence": 0.9,
        "catalyst_age_hours": 5.0,
        "catalyst_primary_source": True,
        "spread_pct": 1.0,
        "dollar_volume": 3_000_000.0,
    }
    base.update(over)
    return DonchianInput(**base)


def test_donchian_gate() -> None:
    ok, reasons = donchian_entry_gate(_donchian_ok())
    assert ok is True and len(reasons) >= 3
    assert donchian_entry_gate(_donchian_ok(close=4.90))[0] is False
    assert donchian_entry_gate(_donchian_ok(rvol_same_time=1.5))[0] is False
    assert donchian_entry_gate(_donchian_ok(catalyst_impact="medium"))[0] is False
    assert donchian_entry_gate(_donchian_ok(catalyst_confidence=0.5))[0] is False
    assert donchian_entry_gate(_donchian_ok(spread_pct=4.0))[0] is False
    assert donchian_entry_gate(_donchian_ok(dollar_volume=100_000.0))[0] is False
    assert donchian_entry_gate(_donchian_ok(dilution_frozen=True))[0] is False
    assert donchian_entry_gate(_donchian_ok(halted_recently=True))[0] is False


# ---- Regime + correlation ----


def test_regime_classification() -> None:
    assert classify_regime(70.0, 2.0, 0) == MarketRegime.RISK_ON
    assert classify_regime(50.0, 0.0, 0) == MarketRegime.CHOP
    assert classify_regime(20.0, -3.0, 0) == MarketRegime.RISK_OFF
    assert classify_regime(70.0, 2.0, 12) == MarketRegime.HALT_STORM
    storm = regime_buy_thresholds(MarketRegime.HALT_STORM)
    assert storm["min_score"] > 100  # unreachable: exits only
    chop = regime_buy_thresholds(MarketRegime.CHOP)
    assert chop["min_score"] == 80.0 and chop["min_rvol"] == 4.0


def test_correlation_filter_drops_clone() -> None:
    base = np.linspace(0, 1, 30)
    rets = {"A": base, "B": base * 1.0 + 0.0001, "C": np.random.default_rng(7).normal(size=30)}
    cands = [
        {"symbol": "A", "score": 90},
        {"symbol": "B", "score": 80},
        {"symbol": "C", "score": 70},
    ]
    kept = correlation_filter(cands, rets)
    syms = [c["symbol"] for c in kept]
    assert "A" in syms and "C" in syms and "B" not in syms


# ---- Sizing + circuit + templates ----


def test_position_sizer() -> None:
    s = PositionSizer()
    r = s.compute(
        SizingInput(
            equity=10000.0,
            score=78,
            atr=0.20,
            price=2.0,
            avg_vol_5m=1_000_000.0,
            float_shares=20_000_000.0,
        )
    )
    assert r.shares > 0 and r.risk_dollars == 50.0
    tiny = s.compute(
        SizingInput(
            equity=10000.0,
            score=95,
            atr=0.05,
            price=0.5,
            avg_vol_5m=10_000.0,
            float_shares=1_000_000.0,
        )
    )
    assert tiny.shares <= 500  # 5% of 5m volume
    assert "volume_impact_5pct" in tiny.capped_by
    bad = s.compute(SizingInput(equity=0.0, score=80, atr=0.2, price=2.0))
    assert bad.shares == 0


def test_circuit_breaker() -> None:
    cb = CircuitBreaker()
    assert cb.check_symbol("ABCD", -2.0) is None
    ev = cb.check_symbol("ABCD", -9.0)
    assert ev is not None and ev.level == "symbol"
    assert cb.is_vetoed("ABCD") is True
    future = datetime.now(UTC) + timedelta(hours=25)
    assert cb.is_vetoed("ABCD", now=future) is False
    ev = cb.check_symbol("EFGH", 0.0, halted=True)
    assert ev is not None
    assert cb.check_strategy("momentum", -4.0) is not None
    assert "momentum" in cb.disabled_strategies
    ev = cb.check_portfolio(-6.0, 0)
    assert ev is not None and cb.killed is True
    cb.reset_day()
    assert cb.killed is False


def test_order_templates_limit_only() -> None:
    t = build_limit_template("abcd", "buy", 100, 2.0, reason="test")
    assert t.order_type == "limit" and float(t.limit_price) == 2.002
    assert "DEGIRO" in t.to_manual_instruction()
    s = build_limit_template("ABCD", "sell", 100, 2.0)
    assert float(s.limit_price) == 1.998
    with pytest.raises(MarketOrderForbiddenError):
        build_template("ABCD", "buy", 100, "market", reference_price=2.0)
    with pytest.raises(ValueError):
        build_limit_template("ABCD", "buy", 100, 2.0, venue="NYSE")


# ---- Feeds ----


@pytest.mark.asyncio
async def test_feeds() -> None:
    from app.feeds import DirectFeed, NotConfiguredError, SipFeed
    from app.providers.market_data import MockMarketDataProvider

    sip = SipFeed(MockMarketDataProvider())
    q = await sip.get_quote("ABCD")
    assert q.symbol == "ABCD"
    assert sip.lag_ok() is True
    direct = DirectFeed()
    with pytest.raises(NotConfiguredError):
        await direct.get_quote("ABCD")


# ---- Signals respect halt/freeze ----


def test_signals_respect_halt_and_freeze() -> None:
    base: dict = {
        "symbol": "ABCD",
        "price": 2.20,
        "score": 85,
        "rvol": 6.0,
        "vwap_distance_pct": 0.5,
        "spread_pct": 1.0,
    }
    assert evaluate(SignalInput(**base)).action.value == "buy"
    assert evaluate(SignalInput(**base, halted=True)).action.value == "hold"
    assert evaluate(SignalInput(**base, buys_frozen=True)).action.value == "hold"
