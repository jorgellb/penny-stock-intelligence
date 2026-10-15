# Operations Documentation

## Running the System

### Docker Compose (Recommended)

```bash
# Local development (uses docker-compose.dev.yml defaults — change secrets in .env)
cp .env.example .env
make docker-up

# Production-like (requires POSTGRES_*, DATABASE_URL, API_KEY in .env — no insecure defaults)
make docker-up-prod

# View logs / stop
make docker-logs
make docker-down
```

### Manual Setup

```bash
# Install dependencies
pip install -e ".[dev,dashboard]"

# Copy config
cp .env.example .env

# Run migrations
make migrate

# Start backend
make dev

# Start dashboard (separate terminal)
make dashboard

# Start worker (separate terminal)
make worker
```

### Scheduled Jobs

Jobs run via APScheduler:

| Job | Schedule | Description |
|-----|----------|-------------|
| sync_universe | 6:00 AM Mon-Fri | Nasdaq Trader listings → securities (real) |
| sync_daily_history | 7:00 AM Mon-Fri | yfinance daily bars → daily_bars (real) |
| sync_fundamentals | 8:00 AM Mon-Fri | yfinance snapshots → fundamentals (real) |
| sync_filings | Every 30 min | 30-day SEC backfill over lists (real) |
| sync_news | Every 15 min | STUB — needs FINNHUB_API_KEY |
| premarket_scan | Every 5 min (4-9 AM) | Monitor round over all lists (real) |
| intraday_scan | Every 2 min (9-4 PM) | Monitor round over all lists (real) |
| risk_refresh | Hourly | SEC dilution-freeze refresh (real) |
| alert_dispatch | Every minute | NOOP by design — alerts send inline in monitor |
| data_cleanup | 2:00 AM daily | 90-day retention on alerts/snapshots/paper (real) |

### Manual Job Execution

```bash
# Run scanner
python -m app scan

# Run premarket scan
python -m app scan --mode premarket

# Run intraday scan
python -m app scan --mode intraday

# Analyze specific symbol
python -m app analyze ABCD
```

## Monitoring

### Health Checks

```bash
# Application health
curl http://localhost:8000/health

# Provider status
curl http://localhost:8000/api/v1/health
```

### Logs

Logs are structured JSON:

```json
{
  "event": "scanner_completed",
  "symbols_scanned": 1832,
  "eligible": 47,
  "alerts": 6,
  "duration_ms": 4231,
  "environment": "production",
  "app": "penny-stock-intelligence"
}
```

### Observed Metrics

- `symbols_scanned`: Total symbols processed
- `eligible_count`: Symbols passing filters
- `alerts_generated`: Alerts produced
- `duration_ms`: Scan duration
- `provider_latency`: Per-provider timing
- `cache_hit_rate`: Cache effectiveness
- `api_calls`: Total API calls
- `llm_calls`: Total AI calls
- `estimated_cost`: Provider costs

## Maintenance

### Database

```bash
# Create new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Check status
alembic current
```

### Data Cleanup

Regular cleanup removes:
- Old quote data (>7 days)
- Old intraday bars (>30 days)
- Processed news (>90 days)
- Old alerts (>1 year)

### Backups

- PostgreSQL: Use pg_dump or cloud snapshots
- Redis: RDB snapshots
- File storage: Regular backups

## Scaling

### Current Architecture

- Single backend instance
- Single worker instance
- PostgreSQL database
- Redis cache (optional)

### Scaling Options

1. **Multiple workers**: Add worker services
2. **Read replicas**: Add PostgreSQL replicas
3. **Redis cluster**: For larger cache needs
4. **Load balancer**: For API traffic

## Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| Database connection fails | Check .env DATABASE_URL |
| Provider not responding | Check API keys |
| Scanner too slow | Increase batch size |
| Alerts not sending | Check Telegram bot token |
| Data stale | Check provider health |

### Log Locations

- Application: `logs/app.log`
- Docker: `docker compose logs`
- Database: PostgreSQL logs