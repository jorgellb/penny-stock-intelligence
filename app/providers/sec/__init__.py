"""SEC EDGAR provider (official source, httpx, no scraping of brokers)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import List, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.domain.models import CorporateAction, DataProvider, Filing, FilingType


class SecEdgarProvider:
    BASE = "https://data.sec.gov"

    @property
    def name(self) -> DataProvider:
        return DataProvider.SEC_EDGAR

    @property
    def rate_limit_per_minute(self) -> int:
        return 10

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(
                    "https://www.sec.gov/files/company_tickers.json", headers=self._headers()
                )
                return r.status_code == 200
        except Exception:
            return False

    def _headers(self) -> dict:
        try:
            ua = get_settings().sec_edgar_user_agent
        except Exception:
            ua = "PennyStockIntelligence/0.1"
        return {"User-Agent": ua, "Accept": "application/json"}

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=8))
    async def get_filings(
        self,
        symbol: str,
        filing_types: list[str] | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 50,
    ) -> list[Filing]:
        # MVP: resolve CIK then fetch submissions JSON. Fail-soft -> [].
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                t = await c.get(
                    "https://www.sec.gov/files/company_tickers.json", headers=self._headers()
                )
                t.raise_for_status()
                universe = t.json()
                cik = None
                for _, v in universe.items():
                    if str(v.get("ticker", "")).upper() == symbol.upper():
                        cik = str(v["cik_str"]).zfill(10)
                        break
                if not cik:
                    return []
                u = f"{self.BASE}/submissions/CIK{cik}.json"
                r = await c.get(u, headers=self._headers())
                r.raise_for_status()
                data = r.json()
                recent = data.get("filings", {}).get("recent", {})
                out: list[Filing] = []
                n = min(len(recent.get("accessionNumber", [])), limit)
                for i in range(n):
                    ftype = recent["form"][i]
                    if filing_types and ftype not in filing_types:
                        continue
                    filing_date = datetime.fromisoformat(recent["filingDate"][i]).replace(
                        tzinfo=UTC
                    )
                    if start and filing_date < start:
                        continue
                    if end and filing_date > end:
                        continue
                    try:
                        ftenum = FilingType(ftype)
                    except ValueError:
                        ftenum = FilingType.OTHER
                    out.append(
                        Filing(
                            symbol=symbol,
                            cik=cik,
                            accession_number=recent["accessionNumber"][i],
                            filing_type=ftenum,
                            filing_date=filing_date,
                            accepted_at=filing_date,
                            url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={symbol}&type={ftype}",
                            primary_document=recent["primaryDocument"][i],
                            provider=DataProvider.SEC_EDGAR,
                        )
                    )
                return out
        except Exception:
            return []

    async def get_filing_content(self, filing: Filing) -> str:
        return ""

    async def get_recent_filings(
        self,
        symbols: list[str] | None = None,
        filing_types: list[str] | None = None,
        hours: int = 24,
    ) -> list[Filing]:
        out: list[Filing] = []
        start = datetime.now(UTC) - timedelta(hours=hours)
        for s in symbols or []:
            out.extend(await self.get_filings(s, filing_types=filing_types, start=start))
        return out

    async def get_corporate_actions(
        self, symbol: str, start: datetime | None = None
    ) -> list[CorporateAction]:
        return []
