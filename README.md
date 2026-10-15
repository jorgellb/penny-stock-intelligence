# Penny Stock Intelligence Engine

> **This software is an analytical research tool. Scores are ranking metrics, not probability forecasts. Live trading is disabled.**

A professional system that scans US penny stocks and micro-cap stocks, collects market data, fundamentals, SEC filings, and news, calculates quantitative indicators, detects catalysts and risks, analyzes text using AI, computes explainable scores, and generates high-quality alerts.

## What It Does

- **Scans** the universe of US penny stocks ($0.10 - $5.00) across NASDAQ, NYSE, and NYSE American
- **Filters** by liquidity, volume, spread, and float
- **Calculates** 30+ technical indicators (EMA, RSI, MACD, ATR, VWAP, RVOL, etc.)
- **Analyzes** fundamentals (revenue, cash, debt, cash runway)
- **Detects** dilution from SEC filings (offerings, ATM, warrants, convertible debt)
- **Classifies** news using AI (category, sentiment, materiality, impact)
- **Scores** stocks using a deterministic, explainable scoring system
- **Generates** alerts via Telegram, Discord, Email, and Webhooks
- **Backtests** strategies with configurable slippage and commissions
- **Displays** everything on a professional dashboard

## What It Does NOT Do

- **Does NOT** execute trades automatically
- **Does NOT** scrape Degiro or any broker interface
- **Does NOT** use unofficial APIs or reverse engineering
- **Does NOT** store broker credentials
- **Does NOT** assume scores represent probability of winning
- **Does NOT** hallucinate financial data

## Architecture

```
Universe → Liquidity Filter → Data Collection → Analysis → Scoring → Ranking → Alerts
```

Each component is modular, decoupled, and replaceable via provider interfaces.

## Quick Start

### Prerequisites

- Python 3.12+
- Docker and Docker Compose (recommended)

### Installation

```bash
# Clone the repository
git clone <repo-url>
cd penny-stock-intelligence

# Copy environment file
cp .env.example .env

# Edit .env with your API keys
nano .env

# Option 1: Using Docker (recommended)
docker compose up --build

# Option 2: Manual installation
pip install -e ".[dev,dashboard]"
make migrate
```

### Running

```bash
# Start all services
make docker-up

# Run scanner
make scan

# Run premarket scan
make scan-premarket

# Run intraday scan
make scan-intraday

# Analyze a specific symbol
make analyze SYMBOL=ABCD

# Historical bundle over symbols (mock or live yfinance)
python -m app.cli backtest --symbols ABCD,EFGH --days 120 --mock

# Refresh securities master (free Nasdaq Trader directory)
python -m app.cli sync

# Read-only Telegram commands (/status /events /paper /circuits)
python -m app.cli telegram

# Check health
make health

# Run tests
make test

# Run linter
make lint

# Run type checker
make typecheck

# Build documentation
```

### Accessing the Dashboard

Open http://localhost:8501 in your browser.

### API Documentation

Open http://localhost:8000/docs in your browser for OpenAPI documentation.

## Configuration

All settings are configurable via `config/settings.yaml` and `.env`:

```yaml
universe:
  min_price: 0.10
  max_price: 5.00
  exchanges:
    - NASDAQ
    - NYSE
    - AMEX

liquidity:
  min_avg_daily_volume: 500000
  min_daily_dollar_volume: 1000000
  max_spread_pct: 5.0

alerts:
  minimum_score: 70
  cooldown_minutes: 20
```

## Providers

### Market Data
- **Primary**: yfinance (free)
- **Fallback**: Alpha Vantage, Finnhub, Polygon.io

### AI/LLM
- **Primary**: OpenAI (gpt-4o-mini)
- **Fallback**: Anthropic

### Alerts
- Console
- Telegram
- Discord
- Email (SMTP)
- Webhook

### SEC Filings
- SEC EDGAR (official)

## Scoring

Scores are computed deterministically:

```
Base Score = momentum(20) + volume(20) + catalyst(20) + technical(15) + liquidity(10) + fundamentals(10) + data_quality(5)
Final Score = max(0, Base Score - Risk Penalties)
```

**Scores are ranking metrics, not probability forecasts.**

Each component is a composite 0-100 sub-score (ATR-normalized momentum,
log-scaled RVOL + float rotation, trend/breakout/RSI-regime/MACD technical,
dollar-volume liquidity). An unknown catalyst re-normalizes the score
instead of capping it at 80. See `docs/SCORING.md`.

## Trade Plans

Every BUY ships with a plan for manual execution: entry, structural stop
(VWAP / opening-range low / premarket high / day low, 3-12%), 1R/2R/3R
targets, reward:risk against the 20-day high, an A/B/C confluence grade and
a risk-based share size. BUYs more than one daily ATR above VWAP are
demoted ("no perseguir"). Paper positions follow the plan: stop,
break-even after T1, exit at T2.

## Dashboard (Night Tape)

Dark trading-terminal UI at http://localhost:8501:

- **Command** — floor KPIs, actionable signal cards with trade-plan ladder,
  paper positions, live tape; optional 30s auto-refresh.
- **Scanner** — run a monitor round over a list.
- **Ticker desk** — 5m intraday chart with VWAP, premarket/opening-range
  levels and plan lines; daily chart with EMA 9/20/50, Bollinger, RSI,
  MACD; score anatomy and sub-scores.
- **Backtest** — equity curve with drawdown, return distribution, average
  return by score band, trade log.
- Radar, Rankings, Watchlists, Journal (paper trades + alerts), Settings.

## Stock Lists + Realtime Monitor

Keep your own persistent stock lists and watch them in realtime. The
monitor emits deterministic **buy/sell signals for manual review**
(never recommendations) via console/Telegram/Discord.

```bash
# Add symbols to your list
curl -X POST "http://localhost:8000/api/v1/watchlists/biotech/symbols?symbol=ABCD"

# Single monitor pass
python -m app monitor --list biotech --once

# Realtime loop (Ctrl+C to stop)
python -m app monitor --list biotech
```

See `docs/MONITORING.md` for rules, thresholds and endpoints.

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Health check |
| `GET /api/v1/universe` | Batched eligibility scan (?limit, budget 2 req/symbol) |
| `GET /api/v1/scanner` | Ranking over live monitor evaluations |
| `GET /api/v1/scanner/premarket` | Premarket ranking (change % as gap proxy) |
| `GET /api/v1/scanner/intraday` | Intraday ranking + market session |
| `GET /api/v1/stocks/{symbol}` | Full stock analysis |
| `GET /api/v1/stocks/{symbol}/technicals` | Technical indicators |
| `GET /api/v1/stocks/{symbol}/fundamentals` | Fundamental data |
| `GET /api/v1/stocks/{symbol}/news` | News articles |
| `GET /api/v1/stocks/{symbol}/filings` | SEC filings |
| `GET /api/v1/stocks/{symbol}/risks` | Risk flags |
| `GET /api/v1/stocks/{symbol}/score` | Score with explanation |
| `GET /api/v1/stocks/{symbol}/history` | Daily OHLCV (today merged from intraday) |
| `GET /api/v1/stocks/{symbol}/intraday` | Latest session 5m bars + running VWAP |
| `POST /api/v1/backtest/run` | Historical bundle (next-open fills, equity curve, calibration) |
| `GET /api/v1/alerts` | Alert history |
| `GET /api/v1/watchlists` | Stock lists |
| `POST /api/v1/watchlists/{name}/symbols?symbol=` | Add to list |
| `GET /api/v1/monitor/status` | Monitor status |
| `GET /api/v1/monitor/events` | Recent buy/sell signals |
| `GET /api/v1/monitor/circuits` | Circuit-breaker audit trail |
| `GET /api/v1/monitor/config` | Current thresholds |
| `GET /api/v1/monitor/paper` | Live paper summary |
| `GET /api/v1/monitor/paper/trades` | Closed paper trades |
| `GET /api/v1/monitor/snapshots` | Evaluation history (features only) |
| `POST /api/v1/monitor/run?list_name=` | One monitor pass |

## Testing

```bash
# All tests
make test

# Unit tests
make test-unit

# Integration tests
make test-integration

# With coverage
make test-cov

# Linting
make lint
make lint-fix

# Type checking
make typecheck

# Formatting
make format
```

## Project Structure

```
penny-stock-intelligence/
├── app/
│   ├── api/           # FastAPI endpoints
│   ├── core/          # Database, logging, exceptions
│   ├── config/        # Configuration management
│   ├── domain/        # Domain models
│   ├── models/        # SQLAlchemy ORM models
│   ├── providers/     # Data providers (market, news, SEC, AI)
│   ├── scanners/      # Scanner pipeline
│   ├── indicators/    # Technical indicators
│   ├── scoring/       # Scoring engine, dilution, risk
│   ├── alerts/        # Alert providers
│   ├── backtesting/   # Backtest engine
│   └── jobs/          # Scheduled jobs
├── dashboard/         # Streamlit dashboard
├── tests/             # Unit and integration tests
├── docs/              # Documentation
├── migrations/        # Database migrations
├── config/            # Configuration files
├── docker/            # Docker files
└── scripts/           # Utility scripts
```

## API Keys

You need API keys for some providers:

| Provider | Purpose | Free Tier |
|----------|---------|-----------|
| [Alpha Vantage](https://www.alphavantage.co/) | Market data | 5 req/min |
| [Finnhub](https://finnhub.io/) | Market data, news | 60 req/min |
| [OpenAI](https://platform.openai.com/) | NLP classification | Pay per use |
| [Polygon.io](https://polygon.io/) | Market data | Generous free |

## Security

- All API keys via `.env` file (never committed)
- Input validation on all endpoints
- SQL injection prevention via SQLAlchemy ORM
- Prompt injection defense for AI processing
- Structured logging with secret redaction
- Content treated as data, never instructions

## Contributing

1. Create a feature branch
2. Add tests for new functionality
3. Run `make lint` and `make typecheck`
4. Update documentation
5. Submit a pull request

## License

MIT License

## Disclaimer

This software is for informational and research purposes only. It does not constitute financial advice. Past performance does not guarantee future results. Always do your own research before making investment decisions.

The authors are not responsible for any financial losses incurred from using this software.