"""Free US listing directory from Nasdaq Trader (no key, official files).

Sources (pipe-delimited, last line is a file-creation timestamp):
- https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt
  (NASDAQ; Exchange Q/G/S; has ETF + Test Issue columns)
- https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt
  (exchanges A=NYSE American, N=NYSE, P/PSE..., Z=...; has ETF + Test columns)

Symbology honesty: Nasdaq files use $ and . suffixes (warrants/units/
preferred, e.g. AAC$U). We keep the raw symbol AND a normalized tradable
guess ($ -> -, e.g. AAC-U, the yfinance convention) and flag warrants/
units/preferred by suffix so the universe filter can exclude them.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.domain.models import Exchange, Security

NASDAQ_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
_TIMEOUT = 20.0

#: `securities.name` is VARCHAR(200); Nasdaq depositary-share descriptions
#: can exceed that, so names are truncated at ingestion (suffix preserved
#: as-is, no silent word-boundary logic to keep the mapping auditable).
MAX_NAME_LEN = 200


def _clean_name(raw: str) -> str:
    return raw.strip()[:MAX_NAME_LEN]


@dataclass
class ListingRow:
    symbol_raw: str
    symbol: str
    name: str
    exchange: Exchange | None
    is_etf: bool = False
    is_test: bool = False
    is_warrant: bool = False
    is_unit: bool = False
    is_preferred: bool = False


def normalize_symbol(raw: str) -> str:
    """Nasdaq $ suffixes to the yfinance dash convention (AAC$U -> AAC-U)."""
    return raw.replace("$", "-").replace("/", "-").strip().upper()


def classify_suffix(raw: str) -> tuple[bool, bool, bool]:
    """(warrant, unit, preferred) heuristics from Nasdaq symbology."""
    up = raw.upper()
    if up.endswith(("W", "$W", "+")) or "$W" in up:
        return True, False, False
    if up.endswith(("U", "$U")) or "$U" in up:
        return False, True, False
    if "$" in up and not up.endswith(("$W", "$U")):
        return False, False, True
    return False, False, False


def _map_exchange(code: str, nasdaq_file: bool) -> Exchange | None:
    code = code.strip().upper()
    if nasdaq_file:
        return Exchange.NASDAQ if code in ("Q", "G", "S") else None
    return {"A": Exchange.AMEX, "N": Exchange.NYSE}.get(code)


def parse_nasdaq_file(text: str) -> list[ListingRow]:
    rows: list[ListingRow] = []
    for line in text.splitlines():
        if not line or line.startswith("Symbol|") or line.startswith("File Creation"):
            continue
        parts = line.split("|")
        if len(parts) < 8:
            continue
        raw, name, mktcat, test, _fin, _lot, etf, _next = parts[:8]
        w, u, p = classify_suffix(raw)
        rows.append(
            ListingRow(
                symbol_raw=raw.strip(),
                symbol=normalize_symbol(raw),
                name=_clean_name(name),
                exchange=_map_exchange(mktcat, True),
                is_etf=etf.strip().upper() == "Y",
                is_test=test.strip().upper() == "Y",
                is_warrant=w,
                is_unit=u,
                is_preferred=p,
            )
        )
    return [r for r in rows if r.exchange is not None]


def parse_other_file(text: str) -> list[ListingRow]:
    rows: list[ListingRow] = []
    for line in text.splitlines():
        if not line or line.startswith("ACT Symbol|") or line.startswith("File Creation"):
            continue
        parts = line.split("|")
        if len(parts) < 8:
            continue
        raw, name, exch, _cat, etf, _round, test, _next = parts[:8]
        w, u, p = classify_suffix(raw)
        rows.append(
            ListingRow(
                symbol_raw=raw.strip(),
                symbol=normalize_symbol(raw),
                name=_clean_name(name),
                exchange=_map_exchange(exch, False),
                is_etf=etf.strip().upper() == "Y",
                is_test=test.strip().upper() == "Y",
                is_warrant=w,
                is_unit=u,
                is_preferred=p,
            )
        )
    return [r for r in rows if r.exchange is not None]


async def fetch_listings(client: httpx.AsyncClient | None = None) -> list[ListingRow]:
    """Download + parse both directories (fail-soft per file)."""
    own = client is None
    client = client or httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        out: list[ListingRow] = []
        for url, parser in ((NASDAQ_URL, parse_nasdaq_file), (OTHER_URL, parse_other_file)):
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                out.extend(parser(resp.text))
            except Exception:
                continue
        return out
    finally:
        if own:
            await client.aclose()


def to_securities(
    rows: list[ListingRow],
    exclude_etfs: bool = True,
    exclude_warrants: bool = True,
    exclude_units: bool = True,
    exclude_preferred: bool = True,
    include_tests: bool = False,
) -> list[Security]:
    """Apply universe-type exclusions (test issues always dropped unless asked)."""
    out: list[Security] = []
    for r in rows:
        if r.is_test and not include_tests:
            continue
        if exclude_etfs and r.is_etf:
            continue
        if exclude_warrants and r.is_warrant:
            continue
        if exclude_units and r.is_unit:
            continue
        if exclude_preferred and r.is_preferred:
            continue
        assert r.exchange is not None
        out.append(
            Security(
                symbol=r.symbol,
                name=r.name,
                exchange=r.exchange,
                is_etf=r.is_etf,
                is_preferred=r.is_preferred,
                is_warrant=r.is_warrant,
                is_spac_unit=r.is_unit,
                is_active=True,
            )
        )
    return out
