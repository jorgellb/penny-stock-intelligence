"""CLI for Penny Stock Intelligence Engine.

Every command does real work and reports honestly: scan dispatches the
registered scheduler job, analyze evaluates one symbol through the live
monitor pipeline, health probes settings + database, backtest prints the
effective cost model. Nothing prints fake success.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime

SCAN_JOBS = {
    "premarket": "premarket_scan",
    "intraday": "intraday_scan",
    "daily": "sync_daily_history",
}


def scan_command(mode: str, symbol: str | None = None) -> int:
    """Dispatch the registered job for mode (or analyze one symbol)."""
    from app.jobs import run_job

    if symbol:
        return analyze_command(symbol, use_mock=False)
    job = SCAN_JOBS[mode]
    print(f"Running job '{job}' (mode {mode}) at {datetime.now(UTC).isoformat()}...")
    try:
        result = asyncio.run(run_job(job))
    except Exception as exc:
        print(f"Job '{job}' failed: {exc}")
        return 1
    if result.get("error"):
        print(f"Job '{job}' reported error: {result['error']}")
        return 1
    print(f"Job '{job}' completed: {result}")
    return 0


def analyze_command(symbol: str, use_mock: bool = False) -> int:
    """Evaluate one symbol through the monitor pipeline and print it."""
    from app.jobs.monitor import MonitorService

    sym = symbol.strip().upper()
    if not sym:
        print("Empty symbol.")
        return 1
    provider = None
    if use_mock:
        from app.providers.market_data import MockMarketDataProvider

        provider = MockMarketDataProvider()
    svc = MonitorService(market_data_provider=provider)
    try:
        event, details = asyncio.run(svc.evaluate_symbol(sym))
    except Exception as exc:
        print(f"Analysis of {sym} failed: {exc}")
        return 1
    print(f"[{event.action.upper()}] {event.symbol} @ ${event.price:.2f} (score {event.score})")
    print(
        f"change {details.get('change_pct')}% | rvol {details.get('rvol')}x "
        f"({details.get('rvol_source')}) | feed {details.get('feed_kind')} "
        f"{details.get('feed_lag_ms')}ms | vwap {details.get('vwap')} "
        f"({details.get('vwap_distance_pct')}%) | risk {details.get('risk_flags')}"
    )
    for r in event.reasons:
        print(f"  - {r}")
    print("Señal automática para revisión manual, no es recomendación.")
    return 0


def backtest_command(symbols: str | None = None, days: int = 120, use_mock: bool = False) -> int:
    """Cost model (no args) or historical rvol-momentum bundle over symbols."""
    from app.config import get_settings

    bt = get_settings().backtesting
    if not symbols:
        print("Execution-cost model (per side):")
        print(f"  commission: {bt.default_commission_pct * 100:.3f}%")
        print(f"  slippage:   {bt.default_slippage_pct * 100:.2f}%")
        print(
            f"  spread term: +{bt.default_spread_penalty_pct * 100:.2f}% "
            f"when spread > {bt.default_spread_threshold_pct:.1f}%"
        )
        print(f"  min liquidity: {bt.min_liquidity_for_execution} shares")
        print("Historical bundles: backtest --symbols AAA,BBB [--days N] [--mock].")
        return 0
    from app.backtesting import BacktestConfig
    from app.backtesting.history import BundleRule, fetch_series, run_bundle

    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not syms:
        print("Empty symbol list.")
        return 1
    provider = None
    if use_mock:
        from app.providers.market_data import MockMarketDataProvider

        provider = MockMarketDataProvider()
    series = asyncio.run(fetch_series(syms, days=days, provider=provider))
    if not series:
        print("No usable history fetched.")
        return 1
    result = run_bundle(
        series,
        rule=BundleRule(),
        costs=BacktestConfig(
            commission_pct=bt.default_commission_pct,
            slippage_pct=bt.default_slippage_pct,
            min_volume=bt.min_liquidity_for_execution,
            spread_penalty_threshold_pct=bt.default_spread_threshold_pct,
            spread_penalty_pct=bt.default_spread_penalty_pct,
        ),
    )
    m = result.metrics
    print(f"symbols: {sorted(series)} | skipped: {result.skipped or 'none'}")
    print(
        f"trades: {int(m.get('number_of_signals', 0))} "
        f"| win {m.get('win_rate', 0):.1f}% "
        f"| avg {m.get('average_return', 0):+.2f}% "
        f"| med {m.get('median_return', 0):+.2f}% "
        f"| pf {m.get('profit_factor', 0):.2f} "
        f"| dd {m.get('max_drawdown', 0):.2f}%"
    )
    means = result.walk_forward.get("mean", {})
    if means:
        print(
            f"walk-forward mean: win {means.get('win_rate', 0):.1f}% "
            f"| avg {means.get('average_return', 0):+.2f}% "
            f"over {len(result.walk_forward.get('folds', []))} folds"
        )
    else:
        print("walk-forward: insufficient trades (<4)")
    print("Informational only; past returns do not predict future ones.")
    return 0


def sync_command() -> int:
    """Refresh the securities master from Nasdaq Trader (real job)."""
    from app.jobs import run_job

    try:
        result = asyncio.run(run_job("sync_universe"))
    except Exception as exc:
        print(f"sync_universe failed: {exc}")
        return 1
    if result.get("error"):
        print(f"sync_universe error: {result['error']}")
        return 1
    print(f"Universe synced: {result.get('saved', 0)} securities.")
    return 0


def telegram_command() -> int:
    """Run the read-only Telegram command bot (needs token + chat id)."""
    from app.alerts.telegram_commands import TelegramCommander
    from app.config import get_settings

    s = get_settings()
    if not s.telegram_bot_token or not s.telegram_chat_id:
        print("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set; bot not started.")
        return 1
    print("Telegram commands listening (/status /events /paper /circuits /help). Ctrl+C to stop.")
    try:
        asyncio.run(TelegramCommander(s.telegram_bot_token, s.telegram_chat_id).run_forever())
    except KeyboardInterrupt:
        pass
    return 0


def health_command() -> int:
    """Probe settings + database connectivity. Exit code reflects result."""
    from sqlalchemy import text

    from app.config import get_settings
    from app.core.database import get_db_manager

    ok = True
    try:
        s = get_settings()
        print(f"settings: ok (env={s.environment} paper={s.paper_mode} live={s.live_trading})")
        if s.live_trading:
            print("WARNING: live_trading=true is not supported by this build")
            ok = False
    except Exception as exc:
        print(f"settings: FAIL ({exc})")
        return 1
    try:
        db = get_db_manager()

        async def _ping() -> None:
            async with db.session_factory() as session:
                await session.execute(text("SELECT 1"))

        asyncio.run(_ping())
        print("database: ok")
    except Exception as exc:
        print(f"database: FAIL ({exc})")
        ok = False
    print("Health: healthy" if ok else "Health: degraded")
    return 0 if ok else 1


def monitor_command(
    list_name: str, user_id: str, once: bool, interval: int | None, use_mock: bool
) -> None:
    """Monitor a stock list in realtime emitting buy/sell signals."""
    from app.core.database import get_db_manager
    from app.jobs.monitor import MonitorService

    async def _run() -> None:
        provider = None
        if use_mock:
            from app.providers.market_data import MockMarketDataProvider

            provider = MockMarketDataProvider()
        svc = MonitorService(market_data_provider=provider)
        db = get_db_manager()
        await db.create_tables()
        async with db.session() as session:
            from app.repositories import WatchlistRepository

            symbols = await WatchlistRepository(session).symbols(user_id, list_name)
        if not symbols:
            print(f"List '{list_name}' is empty. Add symbols first.")
            return
        if once:
            results = await svc.run_once(symbols)
            for e in results:
                print(f"[{e.action.upper()}] {e.symbol} @ ${e.price:.2f} (score {e.score})")
                for r in e.reasons:
                    print(f"  - {r}")
        else:
            print(f"Monitoring {symbols} every {interval or 60}s. Ctrl+C to stop.")
            await svc.loop_forever(user_id, list_name, interval)

    asyncio.run(_run())


def main() -> None:
    parser = argparse.ArgumentParser(description="Penny Stock Intelligence Engine")
    subparsers = parser.add_subparsers(dest="command")

    # Scan command
    scan_parser = subparsers.add_parser("scan", help="Run scanner job")
    scan_parser.add_argument(
        "--mode", default="intraday", choices=["premarket", "intraday", "daily"]
    )
    scan_parser.add_argument("--symbol", default=None, help="Analyze one symbol instead")

    # Analyze command
    analyze_parser = subparsers.add_parser("analyze", help="Analyze a symbol")
    analyze_parser.add_argument("symbol", help="Stock symbol")
    analyze_parser.add_argument("--mock", action="store_true", help="Use mock market data")

    # Backtest command
    backtest_parser = subparsers.add_parser("backtest", help="Costs or historical bundle")
    backtest_parser.add_argument("--symbols", default=None, help="Comma-separated symbols")
    backtest_parser.add_argument("--days", type=int, default=120, help="History window")
    backtest_parser.add_argument("--mock", action="store_true", help="Use mock market data")

    # Health command
    subparsers.add_parser("health", help="Check service health")

    # Sync command
    subparsers.add_parser("sync", help="Refresh securities master (Nasdaq Trader)")

    # Telegram command bot
    subparsers.add_parser("telegram", help="Run read-only Telegram commands")

    # Monitor command
    monitor_parser = subparsers.add_parser("monitor", help="Monitor a stock list in realtime")
    monitor_parser.add_argument("--list", default="default", help="List name to monitor")
    monitor_parser.add_argument("--user", default="default", help="User id")
    monitor_parser.add_argument("--once", action="store_true", help="Single pass and exit")
    monitor_parser.add_argument("--interval", type=int, default=None, help="Loop seconds")
    monitor_parser.add_argument("--mock", action="store_true", help="Use mock market data")

    args = parser.parse_args()

    code = 0
    if args.command == "scan":
        code = scan_command(args.mode, args.symbol)
    elif args.command == "analyze":
        code = analyze_command(args.symbol, args.mock)
    elif args.command == "backtest":
        code = backtest_command(args.symbols, args.days, args.mock)
    elif args.command == "health":
        code = health_command()
    elif args.command == "sync":
        code = sync_command()
    elif args.command == "telegram":
        code = telegram_command()
    elif args.command == "monitor":
        monitor_command(args.list, args.user, args.once, args.interval, args.mock)
    else:
        parser.print_help()
        code = 1
    sys.exit(code)


if __name__ == "__main__":
    main()
