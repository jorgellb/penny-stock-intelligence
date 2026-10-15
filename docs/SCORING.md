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