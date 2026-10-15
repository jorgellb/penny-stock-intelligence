"""Unit: backtest execution costs incl. illiquidity spread term."""

from app.backtesting import BacktestConfig, apply_costs


def test_legacy_behavior_without_spread() -> None:
    cfg = BacktestConfig()
    assert apply_costs(100.0, "buy", cfg) == round(100.0 * 1.011, 4)
    assert apply_costs(100.0, "sell", cfg) == round(100.0 * 0.989, 4)
    assert apply_costs(100.0, "buy", cfg, spread_pct=None) == apply_costs(100.0, "buy", cfg)


def test_tight_spread_no_extra_penalty() -> None:
    cfg = BacktestConfig()
    assert apply_costs(2.0, "buy", cfg, spread_pct=1.0) == apply_costs(2.0, "buy", cfg)
    assert apply_costs(2.0, "sell", cfg, spread_pct=2.9) == apply_costs(2.0, "sell", cfg)
    # at the threshold: no penalty (strictly greater triggers)
    assert apply_costs(2.0, "buy", cfg, spread_pct=3.0) == apply_costs(2.0, "buy", cfg)


def test_wide_spread_adds_penalty_both_sides() -> None:
    cfg = BacktestConfig()
    buy_wide = apply_costs(2.0, "buy", cfg, spread_pct=8.0)
    buy_base = apply_costs(2.0, "buy", cfg)
    assert buy_wide == round(2.0 * (1 + 0.01 + 0.001 + 0.01), 4)
    assert buy_wide > buy_base  # worse fill on entry
    sell_wide = apply_costs(2.0, "sell", cfg, spread_pct=8.0)
    sell_base = apply_costs(2.0, "sell", cfg)
    assert sell_wide == round(2.0 * (1 - 0.01 - 0.001 - 0.01), 4)
    assert sell_wide < sell_base  # worse fill on exit


def test_roundtrip_cost_grows_with_spread() -> None:
    cfg = BacktestConfig()
    base_cost = apply_costs(2.0, "buy", cfg) - apply_costs(2.0, "sell", cfg)
    wide_cost = apply_costs(2.0, "buy", cfg, spread_pct=10.0) - apply_costs(
        2.0, "sell", cfg, spread_pct=10.0
    )
    assert wide_cost > base_cost


def test_custom_threshold_and_penalty() -> None:
    cfg = BacktestConfig(spread_penalty_threshold_pct=1.0, spread_penalty_pct=0.02)
    assert apply_costs(1.0, "buy", cfg, spread_pct=1.5) == round(1.0 * 1.031, 4)
    assert apply_costs(1.0, "buy", cfg, spread_pct=0.5) == round(1.0 * 1.011, 4)
