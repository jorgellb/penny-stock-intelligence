"""Unit: CLI commands do real work and report honestly."""

import pytest

import app.cli as cli


def test_scan_dispatches_registered_job(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    calls: list[str] = []

    async def _fake(name: str) -> dict:  # type: ignore[no-untyped-def]
        calls.append(name)
        return {"job": name}

    import app.jobs as jobs

    monkeypatch.setattr(jobs, "run_job", _fake)
    assert cli.scan_command("premarket") == 0
    assert calls == ["premarket_scan"]
    assert cli.scan_command("intraday") == 0
    assert calls[-1] == "intraday_scan"
    assert cli.scan_command("daily") == 0
    assert calls[-1] == "sync_daily_history"
    out = capsys.readouterr().out
    assert "completed" in out


def test_scan_reports_job_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.jobs as jobs

    async def _boom(name: str) -> dict:  # type: ignore[no-untyped-def]
        raise RuntimeError("down")

    monkeypatch.setattr(jobs, "run_job", _boom)
    assert cli.scan_command("intraday") == 1


def test_sync_command_reports_saved(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    import app.jobs as jobs

    async def _ok(name: str) -> dict:  # type: ignore[no-untyped-def]
        assert name == "sync_universe"
        return {"job": name, "saved": 6194}

    monkeypatch.setattr(jobs, "run_job", _ok)
    assert cli.sync_command() == 0
    assert "6194" in capsys.readouterr().out


def test_telegram_command_needs_token(capsys) -> None:
    assert cli.telegram_command() == 1
    assert "not set" in capsys.readouterr().out


def test_parse_cron_five_fields() -> None:
    from app.jobs import parse_cron

    assert parse_cron("*/5 4-9 * * 1-5") == {
        "minute": "*/5",
        "hour": "4-9",
        "day": "*",
        "month": "*",
        "day_of_week": "1-5",
    }
    assert parse_cron("0 2 * * *")["day_of_week"] == "*"
    with pytest.raises(ValueError):
        parse_cron("*/5 4-9")


def test_run_job_unknown() -> None:
    import asyncio as _aio

    from app.jobs import run_job

    with pytest.raises(ValueError):
        _aio.run(run_job("nope"))


def test_analyze_with_mock_returns_zero(capsys) -> None:
    assert cli.analyze_command("abcd", use_mock=True) == 0
    out = capsys.readouterr().out
    assert "ABCD" in out
    assert "no es recomendación" in out


def test_analyze_rejects_empty_symbol() -> None:
    assert cli.analyze_command("   ", use_mock=True) == 1


def test_backtest_prints_effective_costs(capsys) -> None:
    assert cli.backtest_command() == 0
    out = capsys.readouterr().out
    assert "commission" in out and "slippage" in out and "spread term" in out


def test_backtest_bundle_with_mock(capsys) -> None:
    assert cli.backtest_command("ABCD,EFGH", days=60, use_mock=True) == 0
    out = capsys.readouterr().out
    assert "symbols:" in out and "Informational only" in out


def test_health_reports_db_failure(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    import app.cli as cli_mod

    class _DB:
        def session_factory(self):  # type: ignore[no-untyped-def]
            class _S:
                async def __aenter__(self):  # type: ignore[no-untyped-def]
                    return self

                async def __aexit__(self, *a):  # type: ignore[no-untyped-def]
                    return False

                async def execute(self, *a, **k):  # type: ignore[no-untyped-def]
                    raise ConnectionError("no postgres here")

            return _S()

    import app.core.database as db_mod

    monkeypatch.setattr(db_mod, "get_db_manager", lambda: _DB())
    # cli imports get_db_manager from app.core.database at call time
    assert cli_mod.health_command() == 1
    assert "FAIL" in capsys.readouterr().out
