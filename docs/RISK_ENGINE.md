# Risk Engine Documentation

## Overview

The Risk Engine detects and classifies risk factors for each security. Each risk flag includes severity, penalty, explanation, and source.

## Risk Flags

### Low Float Risk
- **MICRO_FLOAT**: Float < 5M shares
- **LOW_FLOAT**: Float between 5M and 20M shares

### Liquidity Risk
- **LOW_LIQUIDITY**: Average daily volume below threshold
- **VERY_LOW_LIQUIDITY**: Severely insufficient liquidity
- **WIDE_SPREAD**: Bid/ask spread exceeds configured maximum

### Volatility Risk
- **EXTREME_VOLATILITY**: ATR exceeds configured maximum

### Dilution Risk
- **RECENT_OFFERING**: Recent public offering
- **ACTIVE_ATM**: Active at-the-market program
- **SHELF_REGISTRATION**: Shelf registration filed
- **WARRANT_OVERHANG**: Significant warrant overhang
- **CONVERTIBLE_DEBT**: Convertible debt outstanding
- **SHARE_DILUTION**: Shares outstanding increased significantly

### Corporate Action Risk
- **RECENT_REVERSE_SPLIT**: Reverse split within lookback period
- **DELISTING_WARNING**: Exchange delisting warning

### Financial Health Risk
- **GOING_CONCERN**: Auditor going concern opinion
- **NEGATIVE_WORKING_CAPITAL**: Negative working capital
- **LOW_CASH_RUNWAY**: Estimated cash runway under threshold

### Trading Risk
- **TRADING_HALT**: Currently halted from trading
- **NO_RECENT_FILINGS**: No recent SEC filings
- **INSUFFICIENT_DATA**: Insufficient data for analysis
- **NEWS_UNVERIFIED**: News from unverified source

## Risk Assessment Process

1. **Collect data**: Quote, fundamentals, share statistics, float
2. **Check thresholds**: Compare against configured risk parameters
3. **Generate flags**: Create RiskFlag objects for each violation
4. **Assign severity**: Based on impact and probability
5. **Apply penalties**: Add score_penalty for each flag
6. **Aggregate severity**: Determine overall risk level

## Data Freshness Check

The Risk Engine also checks data freshness:
- Stale data flag if data > 2 hours old
- Data quality score based on available categories
- Missing data fields reported explicitly

## Confidence Levels

Each risk flag includes a confidence assessment based on:
- Source reliability (confirmed vs reported vs rumor)
- Data completeness
- Temporal relevance