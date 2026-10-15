# Backtesting Documentation

## Overview

The backtest engine evaluates whether scoring rules historically provide information. It is NOT designed to prove profitability.

## Key Principles

- **Point-in-Time**: No look-ahead bias
- **No Survivorship Bias**: Includes delisted stocks
- **Realistic Execution**: Models slippage and commissions
- **Liquidity-Aware**: Cannot execute large orders in illiquid stocks

## Backtest Configuration

```yaml
backtesting:
  default_commission_pct: 0.001  # 0.1%
  default_slippage_pct: 0.01     # 1% mínimo (nunca ejecución perfecta al último precio)
  min_liquidity_for_execution: 500000
  default_spread_threshold_pct: 3.0   # spread mayor → término extra de cruce
  default_spread_penalty_pct: 0.01    # +1% por lado sobre el spread ancho
```

Execution cost per side = commission + slippage (+ spread penalty only
when the measured quote spread exceeds the threshold; unknown spread
applies no invented penalty). `apply_costs(price, side, cfg, spread_pct)`.

## Signal Generation

Signals are generated from the scoring engine output:
- Score ≥ `minimum_score` → BUY signal
- Score < threshold → No action
- Score drops below threshold → SELL signal

## Trade Simulation

For each signal:
1. Check liquidity (can we execute?)
2. Apply slippage based on spread
3. Apply commission
4. Record entry price, date, score
5. Wait for exit signal or holding period
6. Record exit price, date, return

## Metrics

| Metric | Description |
|--------|-------------|
| number_of_signals | Total signals generated |
| win_rate | Percentage of winning trades |
| average_return | Mean return per trade |
| median_return | Median return per trade |
| expectancy | Average profit per trade |
| profit_factor | Gross profit / Gross loss |
| max_drawdown | Maximum peak-to-trough decline |
| Sharpe | Risk-adjusted return |
| Sortino | Downside-adjusted return |
| MAE | Maximum Adverse Excursion |
| MFE | Maximum Favorable Excursion |

## Post-Signal Analysis

More important than overall metrics:

```
return +5 min
return +15 min
return +30 min
return +60 min
return close
return next day
```

This evaluates the information content of scores without assuming an execution strategy.

## Historical bundle (rvol-momentum rule)

`app/backtesting/history.py` runs an end-to-end bundle over daily bars:

- signal: RVOL(20d) ≥ 2.0 and day change ≥ +5% (configurable `BundleRule`),
  entry at close all-in, exit after 5 sessions or −8% stop, one position
  per symbol, decisions strictly on data ≤ T;
- output: `summarize()` metrics + `walk_forward_report()` + per-trade rows;
- run it: `python -m app.cli backtest --symbols AAA,BBB --days 120 [--mock]`
  or `POST /api/v1/backtest/run?symbols=AAA,BBB`.

The rule carries no scoring model (`score_at_entry=0`, never invented):
it measures whether raw rvol-momentum bursts had follow-through, which
is the baseline any future scored strategy must beat.

## Walk-Forward Validation

When optimizing parameters:
1. **Train** on historical data
2. **Validate** on recent data
3. **Test** on out-of-sample data
4. **Walk forward** in time

Never optimize on the full history.

Implemented in `app.backtesting`:

```python
from app.backtesting import walk_forward_report, calibrate_by_score

items = [{"date": ..., "symbol": ..., "score": 78, "return_pct": 2.5}, ...]
report = walk_forward_report(items, n_splits=3)  # expanding window, no leakage
bands = calibrate_by_score(items)  # subsequent returns per score band
```

- `walk_forward_splits` sorts chronologically and tests each next block
  on data strictly after the train window (max train date < min test date).
- `walk_forward_report` applies `summarize()` per out-of-sample fold plus
  mean win_rate/average/median/expectancy. It checks information content
  across time; it never fits parameters.
- `calibrate_by_score` shows subsequent-return distributions per band
  (50-59 … 90-100) — informational only, never a win probability.

## Score Calibration

Analyze historical performance by score group:

```
Score 50-59 → Average return: X%
Score 60-69 → Average return: Y%
Score 70-79 → Average return: Z%
```

This does NOT convert to "probability of winning".

## Important

- Backtest results are NOT predictions
- Penny stocks have execution challenges
- Past performance does not guarantee future results
- This is a research tool, not a trading system

## Historical bundle execution model (`app/backtesting/history.py`)

- **Entry** `next_open` (default): the signal needs the close of day T, so
  the fill is the open of T+1, gap included. `close` keeps the legacy
  close-of-T fill (optimistic).
- **Stops / targets** are checked against each bar's low/high. A gap
  through the level fills at the open (worse than the level), never at the
  level itself.
- **Costs**: commission + slippage on both sides via `apply_costs`.
- **Point-in-time score**: each signal carries the momentum/volume/technical
  score computed on bars ≤ T, so `calibration` shows the average return per
  score band.
- **Metrics**: win rate, expectancy, profit factor, payoff ratio, per-trade
  Sharpe, compounded return and equity drawdown risking
  `position_fraction` (20%) of equity per trade, plus walk-forward folds.

A sanity run on 14 liquid sub-$5 names (250 days, RVOL ≥ 2, day ≥ +5%,
next-open entry, -8% stop, +20% target, 5-day hold) produced 29 trades
with a 17% win rate and negative expectancy: buying the open after a
spike day mostly buys the top. That is why live BUYs require intraday
confirmation (VWAP hold, same-time RVOL) and pass the chase guard.
