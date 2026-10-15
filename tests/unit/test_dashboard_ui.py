"""Unit: dashboard HTML fragments and chart builders (pure functions)."""

from datetime import datetime
from zoneinfo import ZoneInfo

from dashboard import charts
from dashboard import components as ui

NY = ZoneInfo("America/New_York")


def test_formatters_handle_missing_values() -> None:
    assert ui.fnum(None) == "—"
    assert ui.fnum(3.14159, 1, suffix="%", sign=True) == "+3.1%"
    assert ui.fprice(0.4567) == "$0.4567" and ui.fprice(2.5) == "$2.50"
    assert ui.fmoney(14_100_000) == "$14.1M"
    assert ui.tone_class(-1) == "down" and ui.tone_class("x") == "muted"


def test_market_phase_by_new_york_clock() -> None:
    assert ui.market_phase(datetime(2026, 10, 15, 8, 0, tzinfo=NY))[0] == "PREMARKET"
    assert ui.market_phase(datetime(2026, 10, 15, 10, 0, tzinfo=NY))[0] == "REGULAR SESSION"
    assert ui.market_phase(datetime(2026, 10, 17, 10, 0, tzinfo=NY))[0].startswith("CLOSED")


def test_signal_card_escapes_and_renders_plan() -> None:
    card = ui.signal_card(
        {
            "symbol": "<b>X</b>",
            "action": "buy",
            "score": 82,
            "grade": "A",
            "price": 1.5,
            "reasons": ["<script>alert(1)</script>"],
            "trade_plan": {
                "entry": 1.5,
                "stop": 1.44,
                "risk_pct": 4.0,
                "stop_basis": "VWAP",
                "targets": [1.56, 1.62, 1.68],
                "reward_risk": 2.0,
            },
            "order_template": {"quantity": 100, "instruction": "BUY 100x"},
        }
    )
    assert "<script>" not in card and "&lt;script&gt;" in card
    assert "&lt;b&gt;X&lt;/b&gt;" in card
    assert "nt-ladder" in card and "$1.62" in card and "BUY 100x" in card


def test_charts_build_from_api_shapes() -> None:
    bars = [
        {"date": f"2026-0{1 + i // 28}-{1 + i % 28:02d}", "open": 1 + i * 0.01,
         "high": 1.05 + i * 0.01, "low": 0.95 + i * 0.01, "close": 1 + i * 0.012,
         "volume": 1000 + i}
        for i in range(60)
    ]  # fmt: skip
    assert charts.daily_chart(bars, "ABC", {"entry": 1.7, "stop": 1.6, "targets": [1.8]})
    assert charts.daily_chart([], "ABC") is None
    intra = [
        {"ts": f"2026-10-15T09:{30 + i:02d}:00-04:00", "open": 1, "high": 1.1, "low": 0.9,
         "close": 1.05, "volume": 10, "regular": True, "vwap": 1.0}
        for i in range(10)
    ]  # fmt: skip
    assert charts.intraday_chart(intra, "ABC", None, {"prev_close": 0.9}) is not None
    assert charts.equity_curve_chart([{"date": "2026-01-02", "equity": 101.0, "symbol": "A",
                                       "return_pct": 5.0}]) is not None  # fmt: skip
    assert charts.calibration_chart({"60-70": {"n": 0.0}}) is None
