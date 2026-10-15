"""Unit: paper portfolio tracker (no pyramid, costs, day rollover)."""

from datetime import UTC, datetime, timedelta

from app.risk.paper import PaperTracker


def test_open_close_roundtrip_with_costs() -> None:
    t = PaperTracker(starting_equity=10_000.0)
    pos = t.on_buy("ABCD", 2.00, shares=100, spread_pct=1.0)
    assert pos is not None and pos.shares == 100
    assert pos.entry_price > 2.00  # all-in with costs
    assert t.on_buy("ABCD", 2.10, shares=50) is None  # no pyramiding
    t.mark("ABCD", 2.20)
    assert t.position_pnl_pct("ABCD") is not None and t.position_pnl_pct("ABCD") > 0
    trade = t.on_sell("ABCD", 2.20, spread_pct=1.0)
    assert trade is not None and trade.pnl_dollars > 0
    assert t.on_sell("ABCD", 2.20) is None  # flat: nothing to close
    assert t.equity == 10_000.0 + trade.pnl_dollars
    assert t.summary()["closed_trades"] == 1


def test_wide_spread_worsens_fill() -> None:
    cheap = PaperTracker()
    wide = PaperTracker()
    p1 = cheap.on_buy("A", 2.0, shares=100, spread_pct=1.0)
    p2 = wide.on_buy("A", 2.0, shares=100, spread_pct=9.0)
    assert p1 is not None and p2 is not None
    assert p2.entry_price > p1.entry_price


def test_default_notional_when_no_shares() -> None:
    t = PaperTracker(default_position_notional=2_000.0)
    pos = t.on_buy("A", 2.0)
    assert pos is not None and pos.shares == 1000


def test_rejects_bad_prices() -> None:
    t = PaperTracker()
    assert t.on_buy("A", 0.0) is None
    assert t.on_buy("A", -1.0) is None


def test_daily_pnl_resets_on_day_rollover() -> None:
    t = PaperTracker()
    t.on_buy("A", 2.0, shares=100)
    t.on_sell("A", 3.0)  # realized gain today
    assert t.realized_today > 0
    first_day = t._day
    assert first_day  # day stamped (ET)
    t.on_buy("B", 1.0, shares=10, now=datetime.now(UTC) + timedelta(days=2))
    assert t.realized_today == 0.0  # new ET day (or same late-night edge: see below)


def test_summary_shape() -> None:
    t = PaperTracker()
    t.on_buy("A", 1.0, shares=100)
    s = t.summary()
    assert s["open_positions"] == 1
    assert s["positions"]["A"]["shares"] == 100
    assert "daily_pnl_pct" in s
