# Implementation Plan (obligatory first step, plan section 89)

## 1. Requirements digest
Scanner + analysis + deterministic scoring + alerts for US penny/micro-cap.
DEGIRO = manual execution only. No auto-trading, no scraping, no credentials.

## 2. Environment / repo
Greenfield in `/home/jorge/Documentos/Juego/penny-stock-intelligence`.
Python 3.12+ target, FastAPI + SQLAlchemy async + PostgreSQL + Redis optional.

## 3. Architecture
Modular monolith: universe -> liquidity -> providers -> technical/fundamental/dilution/NLP -> risk -> scoring -> ranking -> dashboard/alerts.
All externals behind Protocol adapters.

## 4. Dependencies
Core: fastapi, uvicorn, pydantic v2, sqlalchemy, alembic, asyncpg, httpx, tenacity, pandas/polars, numpy, apscheduler, structlog, pyyaml.
Market: yfinance primary; alpha_vantage/finnhub/polygon optional.
AI: openai primary, anthropic fallback; JSON-only, prompt-injection guard.
Alerts: console/telegram/discord/email/webhook.

## 5. Keys required
Optional for MVP boot: none (mocks + yfinance unauthenticated + SEC public).
Production value: ALPHA_VANTAGE_API_KEY, FINNHUB_API_KEY, OPENAI_API_KEY, TELEGRAM_BOT_TOKEN/CHAT_ID, DISCORD_WEBHOOK_URL, SMTP_*, WEBHOOK_URL.

## 6. Provider selection
- market_data primary yfinance (free), fallback alpha_vantage.
- fundamentals primary yfinance.
- news primary finnhub, fallback alpha_vantage.
- sec primary sec_edgar (data.sec.gov official JSON).
- ai primary openai gpt-4o-mini.

## 7. Phases executed
1 foundation/config/logging/db/domain/provider interfaces
2 market data + universe + indicators + RVOL
3 scanner gap/premarket/intraday
4 fundamentals/cash-runway
5 filings/dilution/corporate-actions
6 news/AI/catalyst
7 risk/score/explainability
8 alerts/cooldown + broker DisabledBrokerAdapter
9 API/dashboard
10 backtest point-in-time
11 tests/security/docs/operations

Decision: proceed to MVP without waiting for approval per plan.
