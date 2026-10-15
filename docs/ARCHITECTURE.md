# Architecture

## Overview

The Penny Stock Intelligence Engine is a modular, decoupled system for scanning, analyzing, and scoring US penny stocks and micro-cap stocks.

## Architecture Diagram

```
┌─────────────────────┐
│   UNIVERSE ENGINE   │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│   LIQUIDITY FILTER  │
└──────────┬──────────┘
           │
    ┌──────┼──────┬──────┐
    ▼      ▼      ▼      ▼
┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐
│MARKET│ │FUND. │ │ SEC  │ │NEWS  │
│DATA  │ │      │ │      │ │      │
└──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘
   │        │       │       │
   ▼        ▼       ▼       ▼
┌─────────────────────────────────┐
│      TECHNICAL ENGINE           │
│      FUNDAMENTAL ENGINE         │
│      DILUTION ENGINE            │
│      NLP/AI ENGINE              │
└───────────┬─────────────────────┘
            │
            ▼
┌─────────────────────┐
│     RISK ENGINE     │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│    SCORING ENGINE   │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ RANKING / WATCHLIST │
└──────────┬──────────┘
    ┌──────┴──────┐
    ▼             ▼
┌──────┐   ┌──────────┐
│DASHBOARD│  │ALERTS    │
└──────┘   │Telegram/ │
           │Discord/  │
           │Email/    │
           └──────────┘
```

## Module Responsibilities

### Universe Engine
- Fetches stock universe from data providers
- Applies price, exchange, and liquidity filters
- Returns eligible symbols with exclusion reasons

### Liquidity Filter
- Checks average daily volume
- Validates dollar volume
- Measures bid/ask spread
- Classifies float (micro, low, normal)

### Market Data Provider
- Fetches quotes, bars, and historical data
- Implements retry and rate limiting
- Provides mock data for testing

### Technical Engine
- Calculates EMA, SMA, RSI, MACD, ATR
- Computes VWAP, RVOL, gap analysis
- Detects breakouts and momentum

### Fundamental Engine
- Fetches revenue, cash, debt, cash flow
- Calculates cash runway
- Computes data quality scores

### Dilution Engine
- Analyzes SEC filings for offerings
- Tracks share outstanding changes
- Detects ATM, shelf registrations, warrants

### NLP/AI Engine
- Classifies news articles
- Analyzes sentiment and materiality
- Detects catalysts

### Risk Engine
- Generates risk flags
- Computes data completeness
- Detects stale data

### Scoring Engine
- Computes deterministic base scores
- Applies risk penalties
- Generates explainable final scores

### Alert Engine
- Delivers alerts via multiple providers
- Implements cooldown and deduplication
- Supports Telegram, Discord, Email, Webhook

### Backtest Engine
- Simulates trades with slippage
- Computes performance metrics
- Supports walk-forward validation

## Data Flow

1. **Universe Scan**: Fetches all US stocks → applies filters → eligible symbols
2. **Data Collection**: Parallel data fetching (market data, fundamentals, SEC, news)
3. **Analysis**: Technical indicators, fundamental analysis, dilution detection
4. **Scoring**: Raw score computation → risk penalty → final score
5. **Ranking**: Sort by score → generate alerts
6. **Delivery**: Send alerts → display on dashboard

## Design Principles

- **Modularity**: Each component is independently replaceable
- **Provider Abstraction**: All external data sources use adapter interfaces
- **Deterministic Scoring**: No opaque ML scores; all calculations are auditable
- **Point-in-Time**: All data maintains temporal metadata to prevent look-ahead bias
- **Fail Gracefully**: Provider failures don't destroy the entire scanner
- **Security**: No secrets in code, input validation, prompt injection defense