"""Unit: Nasdaq Trader listing directory (offline fixtures, no network)."""

import httpx
import pytest

from app.domain.models import Exchange
from app.providers.market_data.nasdaq_listings import (
    classify_suffix,
    fetch_listings,
    normalize_symbol,
    parse_nasdaq_file,
    parse_other_file,
    to_securities,
)

NASDAQ_SAMPLE = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N
ZZZT|Nasdaq Test Stock|Q|Y|N|100|N|N
QQQ|Invesco QQQ Trust|G|N|N|100|Y|N
AAC$U|AAC Unit|Q|N|N|100|N|N
BRK$A|Berkshire Hathaway Inc.|Q|N|N|100|N|N
File Creation Time: 09212026 00:00
"""

OTHER_SAMPLE = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
AA|Alcoa Corporation Common Stock|N|AA|N|100|N|AA
SPY|SPDR S&P 500 ETF|P|SP|Y|100|N|SPY
TTT|Test Issue Other|N|TTT|N|100|Y|TTT
File Creation Time: 09212026 00:00
"""


def test_normalize_and_suffixes() -> None:
    assert normalize_symbol("AAC$U") == "AAC-U"
    assert classify_suffix("AAC$U") == (False, True, False)
    assert classify_suffix("XYZW") == (True, False, False)
    assert classify_suffix("BRK$A") == (False, False, True)
    assert classify_suffix("AAPL") == (False, False, False)


def test_parse_nasdaq() -> None:
    rows = parse_nasdaq_file(NASDAQ_SAMPLE)
    by_sym = {r.symbol: r for r in rows}
    assert by_sym["AAPL"].exchange == Exchange.NASDAQ and not by_sym["AAPL"].is_etf
    assert by_sym["ZZZT"].is_test is True
    assert by_sym["QQQ"].is_etf is True
    assert by_sym["AAC-U"].is_unit is True


def test_parse_other() -> None:
    rows = parse_other_file(OTHER_SAMPLE)
    by_sym = {r.symbol: r for r in rows}
    assert by_sym["AA"].exchange == Exchange.NYSE
    assert "SPY" not in by_sym  # P (non NYSE/AMEX) dropped
    assert by_sym["TTT"].is_test is True


def test_to_securities_exclusions() -> None:
    rows = parse_nasdaq_file(NASDAQ_SAMPLE)
    secs = to_securities(rows)
    syms = [s.symbol for s in secs]
    assert syms == ["AAPL"]  # tests/ETF/units/preferred out by default
    keep_all = to_securities(
        rows,
        exclude_etfs=False,
        exclude_warrants=False,
        exclude_units=False,
        exclude_preferred=False,
        include_tests=True,
    )
    assert len(keep_all) == 5


@pytest.mark.asyncio
async def test_fetch_listings_offline() -> None:
    def _h(request: httpx.Request) -> httpx.Response:
        if "nasdaqlisted" in str(request.url):
            return httpx.Response(200, text=NASDAQ_SAMPLE)
        return httpx.Response(200, text=OTHER_SAMPLE)

    client = httpx.AsyncClient(transport=httpx.MockTransport(_h))
    rows = await fetch_listings(client)
    assert len(rows) == 5 + 2
    assert {r.exchange for r in rows} <= {Exchange.NASDAQ, Exchange.NYSE}


@pytest.mark.asyncio
async def test_fetch_listings_fail_soft() -> None:
    def _boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    client = httpx.AsyncClient(transport=httpx.MockTransport(_boom))
    assert await fetch_listings(client) == []


def test_long_name_truncated_to_varchar() -> None:
    """Regression: WTFCN-style depositary names must not break the sync."""
    long_name = "Wintrust Financial Corporation - " + "Depositary Shares " * 20
    sample = (
        "Symbol|Security Name|Market Category|Test Issue|Financial Status|"
        "Round Lot Size|ETF|NextShares\n"
        f"WTFCN|{long_name}|Q|N|N|100|N|N\n"
        "File Creation Time: 09212026 00:00\n"
    )
    rows = parse_nasdaq_file(sample)
    assert len(rows) == 1
    assert len(rows[0].name) <= 200
    assert rows[0].name == long_name.strip()[:200]
