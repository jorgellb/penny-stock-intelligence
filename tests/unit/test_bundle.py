"""Unit: historical bundle (signals, stop, costs, no look-ahead)."""

from app.backtesting import BacktestConfig
from app.backtesting.history import BundleRule, fetch_series, run_bundle


def _bars(n: int = 30, spike_at: int = 25, base_vol: int = 100_000) -> list[dict]:
    bars = []
    px = 1.0
    for i in range(n):
        vol = base_vol * (8 if i == spike_at else 1)
        px = px * (1.10 if i == spike_at else 1.005)
        bars.append({"date": f"2026-01-{i + 1:02d}", "close": round(px, 4), "volume": vol})
    return bars


CLOSE = BundleRule(entry="close")


def test_spike_triggers_one_trade() -> None:
    res = run_bundle({"AAA": _bars()}, rule=CLOSE)
    assert len(res.trades) == 1
    t = res.trades[0]
    assert t.symbol == "AAA" and 0 <= t.score_at_entry <= 100
    assert t.entry_price > _bars()[25]["close"]  # all-in above raw close
    assert t.exit_price is not None and t.return_pct is not None
    assert res.metrics["number_of_signals"] == 1.0
    assert res.skipped == []


def test_flat_series_no_signals() -> None:
    bars = [{"date": f"2026-02-{i + 1:02d}", "close": 2.0, "volume": 100_000} for i in range(30)]
    res = run_bundle({"AAA": bars})
    assert res.trades == [] and res.metrics["number_of_signals"] == 0.0


def test_stop_exits_early() -> None:
    bars = _bars()
    # crash the day after the spike: stop must cut before holding_days
    bars[26] = {
        "date": "2026-01-27",
        "close": round(bars[25]["close"] * 0.85, 4),
        "volume": 200_000,
    }
    res = run_bundle({"AAA": bars}, rule=BundleRule(holding_days=5, entry="close"))
    assert len(res.trades) == 1
    assert res.trades[0].return_pct is not None and res.trades[0].return_pct < -5.0


def test_costs_make_breakeven_negative() -> None:
    res = run_bundle({"AAA": _bars()}, costs=BacktestConfig())
    t = res.trades[0]
    assert t.entry_price > _bars()[25]["close"]  # slippage+commission on entry


def test_price_filter_and_bad_symbols() -> None:
    res = run_bundle({"BIG": _bars(), "BAD": [{"close": 1.0}]})
    assert "BAD" in res.skipped
    pricey = [
        {"date": f"2026-03-{i + 1:02d}", "close": 50.0, "volume": 5_000_000} for i in range(30)
    ]
    res2 = run_bundle({"BIG": pricey})
    assert res2.trades == []  # above max_price: no penny signals


def test_walk_forward_included_with_enough_trades() -> None:
    series = {f"S{i}": _bars(n=40, spike_at=25) for i in range(4)}
    res = run_bundle(series)
    assert len(res.trades) == 4
    assert len(res.walk_forward["folds"]) >= 1


def test_no_lookahead_signal_day_uses_only_past() -> None:
    # spike on the LAST bar: rvol needs prior average, signal fires at T
    # using volumes <= T only; entry must equal close_T all-in
    bars = _bars(n=30, spike_at=29)
    res = run_bundle({"AAA": bars}, rule=CLOSE)
    assert len(res.trades) == 1
    assert abs(res.trades[0].entry_price - bars[29]["close"] * 1.011) < 1e-4  # rounded


def test_fetch_series_fail_soft() -> None:
    import asyncio

    class _Boom:
        async def get_daily_bars(self, *a, **k):  # type: ignore[no-untyped-def]
            raise RuntimeError("down")

    out = asyncio.run(fetch_series(["AAA"], days=30, provider=_Boom()))
    assert out == {}


def test_next_open_entry_fills_at_following_open() -> None:
    bars = _bars()
    for b in bars:
        b.update(open=b["close"], high=b["close"] * 1.01, low=b["close"] * 0.99)
    bars[26]["open"] = round(bars[25]["close"] * 1.05, 4)  # gap up after signal
    res = run_bundle({"AAA": bars})
    assert len(res.trades) == 1
    assert res.trades[0].entry_date.day == 27  # bar index 26 = 2026-01-27
    assert abs(res.trades[0].entry_price - bars[26]["open"] * 1.011) < 1e-3


def test_next_open_signal_on_last_bar_has_no_fill() -> None:
    assert run_bundle({"AAA": _bars(n=30, spike_at=29)}).trades == []


def test_intraday_stop_gap_fills_at_open_not_at_stop() -> None:
    bars = _bars()
    for b in bars:
        b.update(open=b["close"], high=b["close"] * 1.01, low=b["close"] * 0.99)
    entry = bars[26]["open"]
    bars[27].update(open=entry * 0.80, low=entry * 0.78, close=entry * 0.82)
    res = run_bundle({"AAA": bars}, rule=BundleRule(stop_pct=-8.0))
    t = res.trades[0]
    assert t.exit_price is not None and t.exit_price < entry * 0.81  # gapped through -8%
    assert "stop" in res.exit_reasons.values()


def test_target_and_equity_curve_metrics() -> None:
    bars = _bars()
    for b in bars:
        b.update(open=b["close"], high=b["close"] * 1.01, low=b["close"] * 0.99)
    entry = bars[26]["open"]
    bars[27].update(high=entry * 1.30)
    res = run_bundle({"AAA": bars}, rule=BundleRule(target_pct=20.0))
    t = res.trades[0]
    assert t.return_pct is not None and t.return_pct > 15
    assert res.equity_curve and res.equity_curve[-1]["equity"] > 100
    assert res.metrics["total_return_compounded"] > 0
    assert "payoff_ratio" in res.metrics and "sharpe_per_trade" in res.metrics
