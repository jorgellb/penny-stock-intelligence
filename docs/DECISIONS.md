# Decision Log

## ADR-001: Database Choice - PostgreSQL + asyncpg

**Date**: 2025-01-15
**Status**: Accepted

**Rationale**: PostgreSQL provides:
- Reliable ACID transactions
- JSON support for flexible fields
- Excellent async support via asyncpg
- Well-documented with SQLAlchemy 2.0
- Free and open-source
- Production-proven for financial applications

**Alternatives considered**:
- SQLite: Not suitable for concurrent access
- MongoDB: No relational integrity
- MySQL: Less JSON support

## ADR-002: Market Data Abstraction

**Date**: 2025-01-15
**Status**: Accepted

**Rationale**: Protocol-based interfaces allow swapping providers:
- yfinance for free tier
- Alpha Vantage/Finnhub/Polygon for production
- Mock providers for testing
- No provider lock-in

## ADR-003: Scoring Model - Deterministic Rules

**Date**: 2025-01-15
**Status**: Accepted

**Rationale**:
- Deterministic scores are auditable and reproducible
- Configurable weights allow user customization
- Risk penalties are explicit and explainable
- No opaque ML black boxes
- Scores represent model match, not probability

**Alternatives considered**:
- ML-based scoring: Not explainable, requires training data
- Hybrid models: Too complex for MVP

## ADR-004: LLM Structured Output

**Date**: 2025-01-15
**Status**: Accepted

**Rationale**: 
- LLM used only for NLP (news classification)
- Never for quantitative calculations
- Structured JSON output via Pydantic
- Prompt injection defense in all prompts
- Confidence scores required

## ADR-005: Frontend - Streamlit MVP

**Date**: 2025-01-15
**Status**: Accepted

**Rationale**:
- Streamlit is faster to implement than React
- Business logic stays in FastAPI (decoupled)
- Can be replaced with React later
- Streamlit is sufficient for MVP dashboard

## ADR-006: Background Jobs - APScheduler

**Date**: 2025-01-15
**Status**: Accepted

**Rationale**:
- Simple scheduler for periodic tasks
- No need for Celery complexity in MVP
- Can upgrade to Celery later
- Works well with FastAPI

## ADR-007: Data Format - Pydantic Models

**Date**: 2025-01-15
**Status**: Accepted

**Rationale**:
- Pydantic v2 provides validation and serialization
- Type safety with Python type hints
- FastAPI integrates natively with Pydantic
- JSON serialization built-in

## ADR-008: Project Structure - Modular Monolith

**Date**: 2025-01-15
**Status**: Accepted

**Rationale**:
- Single repository for simplicity
- Modular structure allows extraction later
- No microservices overhead for MVP
- Easy to split into services later

## ADR-009: Testing Strategy

**Date**: 2025-01-15
**Status**: Accepted

**Rationale**:
- Unit tests for all indicator functions
- Mock providers for integration tests
- Synthetic data for test fixtures
- No dependency on real API calls in tests
- pytest with pytest-asyncio for async tests

## ADR-010: Cache Strategy

**Date**: 2025-01-15
**Status**: Accepted

**Rationale**:
- Redis for caching (optional but recommended)
- In-memory cache as fallback
- Different TTLs per data type
- Provider-specific cache policies
- Hash-based content deduplication
## ADR-011: Persistent Lists + Deterministic Buy/Sell Monitor

**Date**: 2026-09-20
**Status**: Accepted

**Rationale**:
- Lists live in PostgreSQL (`WatchlistItems` + `list_name`), not memory,
  so the monitor and API share state across restarts.
- Buy/sell signals are pure rule functions over score/RVOL/VWAP/spread/
  risk flags with per-state transitions; fully explainable via `reasons[]`.
- Monitor loop is async with semaphore-limited concurrency; one symbol
  failing never kills a round; AlertEngine cooldown/dedup prevents spam.
- Signals are labeled for human review, never recommendations, consistent
  with "scores are ranking metrics, not forecasts".

## ADR-012: NASDAQ/NYSE Microstructure Stack

**Date**: 2026-09-21
**Status**: Accepted (implemented)

**Rationale**:
- `HaltGuardian` state machine instead of a bare flag: LULD halts need
  freeze + post-resume cooldown + score decay, not just a penalty.
- `DilutionFreeze` blocks BUYs (not just penalizes): offerings destroy
  more capital than any entry edge can recover.
- `DollarRuleTracker` encodes Nasdaq bid-price compliance (90/150 days).
- `ShortSqueezeGate` is a hard veto because this project has no short
  side; squeezes only annotate momentum-long events.
- Donchian/RVOL/catalyst as a pure gate function: testable without
  market data, reusable by any future strategy layer.
- `PositionSizer` fractional-risk over ATR with volume/float/dollar caps;
  Kelly rejected as allocator (fat tails).
- Order templates are LIMIT-only by construction (`MarketOrderForbiddenError`).
- `FeedAdapter` SIP-first: honest about retail latency vs HFT.

## ADR-013: Round Gates Wired Into the Live Monitor

**Date**: 2026-09-21
**Status**: Accepted (implemented)

**Rationale**:
- `classify_regime` + `correlation_filter` + `CircuitBreaker` existed as
  a tested library but `MonitorService.run_once` ignored all three, so
  the documented protections (§3.1/§3.2/§4.2) were dead code in live
  operation.
- `run_once` is now two-phase: per-symbol evaluation (fail-soft), then
  round gates that only ever demote BUY → HOLD with an explicit reason;
  SELLs (exits) are never blocked.
- Portfolio kill uses round-median change as a paper proxy (documented
  limitation: no live equity curve yet); symbol veto (24h) and halt
  counting are exact. Thresholds live in `monitor:` /
  `circuit:` config, exposed via `GET /monitor/status`.
- 6 new integration tests pin CHOP demotion, HALT_STORM blockade,
  clone-dropping, symbol trip, veto freeze, and status shape.

## ADR-014: SIP Feed Wired Into the Monitor

**Date**: 2026-09-21
**Status**: Accepted (implemented)

**Rationale**:
- `SipFeed`/`DirectFeed` existed but the monitor used the raw provider,
  so retail SIP latency was invisible and `DirectFeed` could be assumed
  silently.
- The monitor now wraps its provider at first use (`feed.kind`, default
  `sip`): per-fetch lag via `SipFeed.last_lag_ms`, lag over budget marks
  the symbol STALE (no signals, explicit reason), and `direct` without
  entitlement falls back to SIP with a logged + surfaced warning.
- 4 new integration tests: default SIP path, slow-feed STALE blockade,
  direct-without-entitlement fallback, unknown-kind fallback.

## ADR-015: Circuit Events Persisted

**Date**: 2026-09-21
**Status**: Accepted (implemented)

**Rationale**:
- Breaker trips lived only in `CircuitBreaker.events` (memory): a
  restart erased the kill-switch/veto audit trail.
- New `circuit_events` table + `CircuitEventRepository.save_batch` /
  `recent`; `run_once` persists only the trips generated in that round
  (fail-soft, like alerts). Served via `GET /monitor/circuits`
  (`?level=symbol|strategy|portfolio`). App startup uses
  `create_tables`, so fresh deploys pick it up; no alembic versions
  exist yet in this repo (pre-existing gap), first baseline should
  include it.
- Smoke-tested the full loop against sqlite:
  `DATABASE_URL=sqlite+aiosqlite:////tmp/smoke.db python -m app monitor
  --list smoke --once --mock` → regime computed, signals evaluated.
  Note: sqlite URLs need 4 slashes for absolute paths (3 = relative).

## ADR-016: Backtest Spread Term

**Date**: 2026-09-21
**Status**: Accepted (implemented)

**Rationale**:
- The engine modelled a flat 1% slippage, understating the cost of
  crossing wide spreads — the dominant cost in sub-$5 stocks (§5 of the
  NASDAQ adaptation doc).
- `apply_costs` gains an optional `spread_pct`: above
  `spread_penalty_threshold_pct` (3%) a flat `spread_penalty_pct` (1%)
  per side is added. `None` (unknown spread) keeps legacy behavior —
  no invented penalty. Thresholds configurable via `backtesting:`.
- 5 new unit tests pin legacy behavior, threshold edge, both sides,
  roundtrip growth, and custom params.

## ADR-017: No Fake Demos (CLI + Dashboard Honesty)

**Date**: 2026-09-21
**Status**: Accepted (implemented)

**Rationale**:
- `scan`/`analyze`/`backtest`/CLI-`health` printed success without doing
  anything; the dashboard showed hardcoded zeros with buttons that faked
  actions. The spec bans demo-falsa explicitly.
- CLI now: `scan` dispatches the registered job (`run_job`) and reports
  its real result/error; `analyze` runs the monitor pipeline for one
  symbol (live or `--mock`); `health` probes settings + DB with exit
  codes; `backtest` prints the effective cost model from settings.
- Dashboard reads only real endpoints (`health`, `monitor/*`,
  `watchlists`) via a streamlit-free `dashboard/api_client.py`
  (httpx, unit-tested with MockTransport); backend down → explicit
  offline banner, never zero-filled tables. 6 CLI + 5 client tests.

## ADR-018: Real Stock Endpoints, Alembic Baseline, Walk-Forward, Critical Kill-Switch

**Date**: 2026-09-21
**Status**: Accepted (implemented)

**Rationale**:
- `/stocks/*` and `/scanner/*` returned empty stubs. Now: every stock
  endpoint evaluates through `MonitorService.evaluate_symbol` (live;
  503 with reason when the provider fails), fundamentals via free
  yfinance with timeout + honest null, news/filings from real caches
  with "not configured" notes. `/universe` returns an honest 501
  (no listing-vendor bundle) pointing at watchlists + monitor/run.
  Scanner rankings read monitor state (score/rvol/vwap filters) plus
  the real market session. 4 endpoint tests.
- Alembic had no versions dir: `migrations/env.py` now prefers
  `DATABASE_URL` (async→sync driver mapping) and the autogenerated
  `initial baseline` (21 tables incl. `circuit_events`) was verified
  with upgrade → downgrade → upgrade on sqlite.
- `app.backtesting` gains `walk_forward_splits/report` (expanding
  window, max-train-date < min-test-date asserted in tests) and
  `calibrate_by_score` (informational bands, never win probability).
  6 new unit tests.
- Kill-switch now edge-triggers `AlertEngine.send_critical` (bypasses
  cooldown/dedup, all providers incl. Telegram) once per transition;
  tested to fire exactly once across two killed rounds.

## ADR-019: Paper Portfolio Feeds the Circuit Breakers

**Date**: 2026-09-21
**Status**: Accepted (implemented)

**Rationale**:
- Symbol/portfolio breakers ran on round change % as a loss proxy even
  when the monitor held real (paper) positions with exact cost basis.
- `PaperTracker` (one position/symbol, no pyramiding, all-in costs with
  measured spread, ET day rollover) mirrors final post-gate actions;
  MtM updates every round without opening/closing. Breakers prefer
  position `unrealized_pct` and paper `daily_pnl_pct`, falling back to
  the round proxy only with no paper history. Demoted BUYs never open.
- Surfaced in `status.paper` and as `paper: abre/cierra` event reasons.
  6 unit + 3 integration tests (open/close, position-PnL trip, status).

## ADR-020: Paper Trades Persisted

**Date**: 2026-09-21
**Status**: Accepted (implemented)

**Rationale**:
- Closed paper trades lived only in `PaperTracker.closed` (memory):
  restarts erased the realized-PnL audit trail.
- New `paper_trades` table (2nd migration, autogenerated against a
  baseline-upgraded DB so the revision contains only the delta;
  upgrade→downgrade→upgrade verified on sqlite) +
  `PaperTradeRepository` + `GET /monitor/paper/trades` (filter by
  symbol) +   `GET /monitor/paper` (live summary). `run_once` persists
  each round's closes fail-soft. 4 new integration tests.

## ADR-025: Round Snapshots + Config Fingerprint

**Date**: 2026-09-21
**Status**: Accepted (implemented)

**Rationale**:
- §70 requires history ("what happened after this setup") and §64
  requires config versioning; neither was wired.
- New `monitor_snapshots` table (3rd migration, delta-only, cycle
  verified) + `MonitorSnapshotRepository` + per-round `scanner_runs`
  summary rows, all persisted fail-soft in `run_once`. Served via
  `GET /monitor/snapshots`. `config_fingerprint()` (sha256 over the
  scoring-relevant sections) is stored per row. Future returns are
  never written to this table by construction. 3 integration tests +
  fingerprint stability/sensitivity test.

## ADR-021: Historical Bundle End-to-End

**Date**: 2026-09-21
**Status**: Accepted (implemented)

**Rationale**:
- The engine had costs/metrics/walk-forward but no runnable bundle, so
  calibration stayed theoretical and `/backtest/*` were stubs.
- `app/backtesting/history.py`: rvol+momentum rule over daily bars with
  stop, all-in costs, one position/symbol, strictly point-in-time;
  wired to `backtest --symbols --days [--mock]` and
  `POST /backtest/run` (rule params as query args). `GET /backtest`
  and `GET /backtest/{id}` are honest (not persisted → note/404).
- No invented scores (`score_at_entry=0`): the bundle is the baseline a
  future scored strategy must beat. 8 unit + 1 endpoint test.

## ADR-022: Free Universe Listings (Nasdaq Trader)

**Date**: 2026-09-21
**Status**: Accepted (implemented)

**Rationale**:
- `get_universe` was a stub/NotImplemented and `sync_universe` a
  timestamp: the market-wide listing source was missing.
- `app/providers/market_data/nasdaq_listings.py` fetches the two free
  official Nasdaq Trader directories (nasdaqlisted + otherlisted, no
  key), parses pipe format with correct column indices, maps Q/G/S→
  NASDAQ and A/N→AMEX/NYSE, normalizes `$` symbology (AAC$U→AAC-U) and
  flags warrants/units/preferred/ETF/test issues. `to_securities`
  applies the configured universe exclusions.
- `sync_universe` persists to `securities` (upsert, idempotent).
  Verified live: 8,871 rows → 6,194 securities; `python -m app.cli sync`
  wired. 6 unit (offline fixtures) + 2 integration tests.

## ADR-030: Scheduler Jobs Get Isolated Event Loops

**Date**: 2026-10-15
**Status**: Accepted (implemented)

**Rationale**:
- `run_scheduler` ran every job via `asyncio.run(run_job(...))`: each
  APScheduler worker thread created a fresh loop while the singleton
  async engine kept pooled asyncpg connections from the previous loop.
  Jobs failed at random with "attached to a different loop" / "Event
  loop is closed" once a stale pooled connection was reused.
- `_run_job_isolated` now disposes the database engine inside the job's
  own loop before it closes; the next run builds a fresh pool on its own
  loop. No behavior change for single-loop contexts (API/tests).
- Regression test: two consecutive isolated runs (sqlite) both complete
  and leave `engine is None` after each. Verified live in the worker:
  consecutive `intraday_scan` + `radar` runs complete with no loop errors.

## ADR-029: Open Paper Positions Survive Restarts

**Date**: 2026-09-21
**Status**: Accepted (implemented)

**Rationale**:
- Closes persisted but opens lived in memory: a restart silently
  dropped positions (and their cost basis for breaker PnL).
- New `paper_positions` table (4th migration, delta + cycle verified):
  upsert on open, delete on close, lazy load once per service lifetime
  before the round gates (fail-soft everywhere). Tested: open →
  fresh service restores → SELL closes the original entry and clears
  the row. 1 repo + 1 restart test.

## ADR-028: Dashboard Backtest + Honest Scheduler Cron

**Date**: 2026-09-21
**Status**: Accepted (implemented)

**Rationale**:
- The dashboard Backtest page was an informational stub while
  `POST /backtest/run` is real: the page now runs it (symbols + days)
  and renders metrics/trades/walk-forward/skipped. Client extended +
  2 MockTransport tests.
- `run_scheduler` parsed only minute/hour and hardcoded `mon-fri`,
  silently misscheduling jobs (e.g. daily cleanup ran weekdays only
  despite `* *` in config). `parse_cron` now uses all 5 fields and
  raises on malformed input; config is the single source of truth.

## ADR-026: Keyless Jobs Do Real Work

**Date**: 2026-09-21
**Status**: Accepted (implemented)

**Rationale**:
- 7 scheduler jobs returned bare timestamps; the scheduler looked alive
  while doing nothing.
- Now real without keys: `sync_daily_history` (yfinance bars →
  `daily_bars`, idempotent per symbol+date), `sync_fundamentals`
  (yfinance → `fundamentals` snapshots), `premarket/intraday_scan`
  (monitor `run_once` over the union of all lists), `risk_refresh`
  (SEC freeze via `sync_lists`), `data_cleanup` (90-day retention on
  alerts/snapshots/paper). `sync_news` and `alert_dispatch` return
  honest noop (key missing / inline dispatch by design).
- Fixed a real sqlite hazard found by tests: concurrent writers raced,
  so jobs fetch concurrently but persist sequentially in one session.
- 5 integration tests (sqlite + stub providers).

## ADR-027: Filings Backfill Consolidates sync_filings

**Date**: 2026-09-21
**Status**: Accepted (implemented)

**Rationale**:
- `sync_filings` (30-min slot) was a timestamp while `sync_filings_fast`
  did the real 48h poll: two names, one worker.
- `sync_lists(hours, job)` now tunes the shared cache window per caller:
  fast job keeps 48h, `sync_filings` runs a 720h backfill over the same
  watchlists. Test pins the window reaching the provider, the job label,
  and per-symbol filtering. Also fixed a cross-test pollution trap: the
  singleton filings cache must start cold in tests.

## ADR-024: Batched Universe Scan (replaces /universe 501)

**Date**: 2026-09-21
**Status**: Accepted (implemented)

**Rationale**:
- `GET /universe` returned an honest 501; the master existed but no
  on-demand eligibility path did.
- `app/scanners/universe_scan.py`: candidates from master (deterministic
  order) → quote + latest daily volume per symbol, semaphore-limited,
  fail-soft, hard request budget (2 req/symbol, `limit` default 200 max
  2000 — no silent 12k-call scans). Missing quotes excluded as
  `no_quote`; unknown volumes annotated, never assumed. Fixed a real
  `str(Exchange)` bug (`"Exchange.NASDAQ"` never matched the filter).
- 3 integration tests (filters, budget cap, endpoint).

## ADR-023: Read-Only Telegram Commands

**Date**: 2026-09-21
**Status**: Accepted (implemented)

**Rationale**:
- Telegram was send-only ("permitir comandos futuros" in the spec).
- `app/alerts/telegram_commands.py` long-polls Bot API with httpx (no
  new dependency): /status /events [N] /paper /circuits /help, pure
  builder functions + `dispatch`, chat-restricted to TELEGRAM_CHAT_ID
  (strangers ignored). Read-only by construction: no order path exists
  in this build. `python -m app.cli telegram`; exits 1 without token.
  4 unit tests (builders, dispatch, poll loop with MockTransport).
