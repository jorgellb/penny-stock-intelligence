# Data Providers Documentation

## Overview

All data providers implement interfaces defined in `app/providers`. Providers are configured via `config/settings.yaml` and can be swapped without changing business logic.

## Provider Architecture

```
Business Logic
      │
      ▼
┌─────────────────────────────┐
│  Provider Interface (ABC)   │
└──────┬──────┬──────┬───────┘
       │      │      │      │
       ▼      ▼      ▼      ▼
   Market  Fund.  News  SEC  AI
   Data    Data   Data  Data  Provider
   Provider Provider Provider      │
       │      │      │            │
       ▼      ▼      ▼            ▼
   yfinance  yfinance finnhub sec_edgar openai
   alpha_v   alpha_v alpha_v    SEC_EDGAR anthropic
   polygon   polygon
```

## Market Data Providers

### yfinance (Primary)
- **Free**: Yes
- **Rate Limit**: ~60 req/min
- **Data**: Quotes, daily bars, history
- **Coverage**: US stocks
- **Reliability**: Good for basic data

### Alpha Vantage
- **Free**: Yes (limited)
- **Rate Limit**: 5 req/min, 500/day
- **Data**: Intraday, daily, fundamentals
- **Coverage**: US stocks
- **Reliability**: Good

### Finnhub
- **Free**: Yes (limited)
- **Rate Limit**: 60 req/min
- **Data**: Real-time quotes, news, fundamentals
- **Coverage**: US stocks
- **Reliability**: Good

### Polygon.io
- **Free**: Generous tier
- **Rate Limit**: High
- **Data**: Full market data, websockets
- **Coverage**: US stocks
- **Reliability**: Excellent

### Twelve Data
- **Free**: Yes (limited)
- **Rate Limit**: Varies
- **Data**: Comprehensive market data
- **Coverage**: Global
- **Reliability**: Good

## SEC Filing Provider

### SEC EDGAR (Official)
- **Free**: Yes (official source)
- **Rate Limit**: Per-IP limit
- **Data**: All SEC filings, corporate actions
- **Coverage**: US public companies
- **Reliability**: Primary source

## AI Providers

### OpenAI
- **Model**: gpt-4o-mini (default)
- **Use**: News classification, filing analysis
- **Prompt Injection Defense**: Explicit instructions
- **Output**: Structured JSON via Pydantic

### Anthropic
- **Model**: Claude (fallback)
- **Use**: Same as OpenAI
- **Prompt Injection Defense**: Explicit instructions

## Provider Interface Pattern

```python
class MarketDataProvider(Protocol):
    async def get_quote(self, symbol: str) -> Quote: ...
    async def get_daily_bars(self, symbol: str, ...) -> List[DailyBar]: ...
    async def get_universe(self, ...) -> List[Security]: ...
    @property
    def name(self) -> DataProvider: ...
    @property
    def rate_limit_per_minute(self) -> int: ...
    async def health_check(self) -> bool: ...
```

## Rate Limiting

All providers implement:
- Centralized rate limiting
- Exponential backoff retries
- Request timeouts
- Circuit breaker (optional)
- Request counting and metrics

## Caching

Provider data is cached:
- Quotes: 5 seconds
- Daily bars: 1 hour
- Fundamentals: 1 hour
- Filings: 1 hour
- News: 5 minutes
- Metadata: Days

## Adding a New Provider

1. Create a new class implementing the Protocol
2. Add configuration to `config/settings.yaml`
3. Add API key to `.env.example`
4. Implement `health_check()` and `get_quote()` at minimum
5. Add unit tests with mock data
6. Document the provider in `docs/DATA_PROVIDERS.md`