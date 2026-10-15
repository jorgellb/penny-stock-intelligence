# Scoring Engine Documentation

## Overview

The scoring engine produces deterministic, explainable scores for each stock in the universe. Scores represent how well a stock matches the configured quantitative model - NOT probability of price increase.

## Score Components

### Base Score (0-100)

| Category | Weight | Description |
|----------|--------|-------------|
| Momentum | 20 | Price trend strength and direction |
| Volume | 20 | Relative volume activity |
| Catalyst | 20 | News and event catalyst strength |
| Technical | 15 | Technical indicator quality |
| Liquidity | 10 | Market liquidity assessment |
| Fundamentals | 10 | Fundamental health |
| Data Quality | 5 | Completeness of available data |

### Risk Penalties (0 to -100)

| Flag | Penalty | Severity |
|------|---------|----------|
| TRADING_HALT | 50 | Critical |
| GOING_CONCERN | 30 | Critical |
| DELISTING_WARNING | 30 | Critical |
| RECENT_OFFERING | 20 | High |
| ACTIVE_ATM | 20 | High |
| DILUTION | 25 | High |
| LOW_LIQUIDITY | 25 | High |
| LOW_CASH_RUNWAY | 15 | Medium |
| NEGATIVE_WORKING_CAPITAL | 15 | Medium |
| SHELF_REGISTRATION | 15 | Medium |
| WIDE_SPREAD | 15 | Medium |
| REVERSE_SPLIT | 10 | Medium |
| WARRANT_OVERHANG | 10 | Medium |
| CONVERTIBLE_DEBT | 10 | Medium |
| NO_RECENT_FILINGS | 10 | Low |
| INSUFFICIENT_DATA | 20 | Low |
| NEWS_UNVERIFIED | 5 | Low |
| MICRO_FLOAT | 5 | Low |
| LOW_FLOAT | 0 | Info (low float fuels runners; risk is handled by sizing and stops) |

### How each sub-score is built (0-100, then scaled by its weight)

All sub-scores live in `app/scoring/components.py` (pure, unit-tested).

| Component | Inputs | Mapping |
|-----------|--------|---------|
| Momentum | day change, daily ATR %, 5-day ROC, VWAP distance | Day move measured in ATR units (2 ATR = 65 pts), +15 for 5-day drift, +20 when holding above VWAP. A +8% day on a stock that moves 20%/day is noise; on one that moves 3%/day it is a real move. |
| Volume | same-time-of-day RVOL (daily proxy fallback), float rotation | Log-scaled: RVOL 1x = 0, 2x ≈ 30, 5x ≈ 70, 10x+ = 100. Session volume / float adds up to +15. The old mapping saturated at 2x, so a sleepy 2x name tied a 15x runner. |
| Technical | daily OHLC | Trend structure (price > EMA9 > EMA20, > EMA50, EMA20 rising: 30), proximity to the 20d/52w high (25), RSI regime (55-75 best, > 85 penalized as exhaustion: 20), MACD impulse (15), Bollinger-width coil (10). Divergences, stochastics and Wyckoff footprints adjust it afterwards. The old version used the raw RSI value, so RSI 95 earned the maximum. |
| Liquidity | session dollar volume, spread | Log-scaled dollar volume ($1M ≈ 45, $5M ≈ 80, $20M+ = 100) × spread factor. Unknown spread is neutral (0.9×), never a free pass. |
| Catalyst | AI / heuristic news classification | strong 100, moderate 55, weak 25, none 0. **Unknown** (no news provider, or not checked) re-normalizes the other components to 100 instead of silently capping every score at 80. |

Sub-scores are rounded (not truncated) when scaled by weight.

## Score Calculation

```
raw_score = momentum + volume + catalyst + technical + liquidity + fundamentals + data_quality
risk_penalty = sum(applicable penalties)
final_score = max(0, raw_score - risk_penalty)
```

## Example Score Breakdown

```
Base score: +81

+18 RVOL
+17 strong catalyst
+14 momentum
+13 technical
+9 liquidity
+6 fundamentals
+4 data quality

Risk penalties:
-15 recent offering
-10 share dilution

FINAL = 56
```

## Configuration

Weights and penalties are configurable via `config/settings.yaml`:

```yaml
scoring:
  weights:
    momentum: 20
    volume: 20
    catalyst: 20
    technical: 15
    liquidity: 10
    fundamentals: 10
    data_quality: 5
  penalties:
    recent_offering: 20
    active_atm: 20
    # ...
```

## Explicability

Every score is reproducible via `ScoreBreakdown` which stores all component values, penalties, and features. Given a score_id, the entire decision can be reconstructed.

## Important

- Scores are **ranking metrics**, not probability forecasts
- The scoring model uses configurable weights, not ML predictions
- AI is only used for feature extraction (news classification), NOT for scoring

## From score to action

A score alone never produces a BUY. After a setup matches (see
`app/signals/setups.py`) the monitor applies, in order:

1. **Hard vetoes** — halt, stale data, dilution freeze, $1 rule, circuit breakers.
2. **Chase guard** (`buy_block_overextended`) — price more than
   `extension_max_vwap_atr` daily ATRs above VWAP, RSI above
   `extension_max_rsi`, or a > 150% day demotes the BUY to HOLD with
   "esperar pullback a VWAP".
3. **Trade plan** (`app/signals/trade_plan.py`) — the stop is the tightest
   structural level (VWAP, opening-range low, premarket high for gap plays,
   day low) at least `plan_min_stop_pct` below entry, falling back to one
   daily ATR and clamped at `plan_max_stop_pct`. Targets are 1R/2R/3R. If
   the 20-day high caps the reward below 1R, the BUY is dropped.
4. **Grade A/B/C** — confluence of score (≥ 80 / ≥ 70), ≥ 2 matched setups,
   catalyst, aligned trend and R:R ≥ `plan_min_rr`.
5. **Sizing** — `risk_per_trade_pct` of paper equity divided by the plan's
   stop distance, capped by 5% of the average *5-minute* volume of the
   session, 10% of float and a dollar cap per score band.
6. **Round gates** — market regime, correlation clones, breadth cap.

Paper positions opened from a plan are managed by it: stop, break-even
after T1, exit at T2 (`plan_exits_enabled`).
