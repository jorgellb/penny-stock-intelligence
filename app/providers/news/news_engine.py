"""
News ingestion and AI classification engine.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.domain.models import (
    CatalystCategory,
    ImpactLevel,
    NewsAnalysis,
    NewsArticle,
)
from app.providers import NewsProvider


@dataclass
class NewsResult:
    """Result of news processing."""

    articles: list[NewsArticle]
    analyses: list[NewsAnalysis]
    symbols_found: list[str]
    duplicates_removed: int
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


class NewsEngine:
    """News ingestion and processing engine."""

    def __init__(self, news_provider: NewsProvider | None = None):
        self.news_provider = news_provider
        self._article_hashes: set = set()

    async def ingest_news(
        self,
        symbols: list[str] | None = None,
        start: datetime | None = None,
        limit: int = 100,
    ) -> NewsResult:
        """Ingest news from provider."""
        if self.news_provider is None:
            return NewsResult(
                articles=[],
                analyses=[],
                symbols_found=[],
                duplicates_removed=0,
            )

        articles = await self.news_provider.get_news(
            symbols=symbols,
            start=start,
            limit=limit,
        )

        # Deduplicate
        unique_articles = []
        duplicates = 0
        for article in articles:
            content_hash = self._compute_hash(article)
            if content_hash and content_hash in self._article_hashes:
                duplicates += 1
                continue
            if content_hash:
                self._article_hashes.add(content_hash)
            article.content_hash = content_hash
            unique_articles.append(article)

        symbols_found = list(set(a.symbol for a in unique_articles))

        return NewsResult(
            articles=unique_articles,
            analyses=[],
            symbols_found=symbols_found,
            duplicates_removed=duplicates,
        )

    def _compute_hash(self, article: NewsArticle) -> str | None:
        """Compute hash for deduplication."""
        try:
            import hashlib

            content = f"{article.symbol}{article.headline}{article.published_at.isoformat()}"
            return hashlib.md5(content.encode()).hexdigest()
        except Exception:
            return None

    def filter_by_symbols(
        self, articles: list[NewsArticle], symbols: list[str]
    ) -> list[NewsArticle]:
        """Filter articles by symbol list."""
        symbol_set = set(symbols)
        return [
            a
            for a in articles
            if a.symbol in symbol_set or symbol_set.intersection(a.symbols_mentioned)
        ]

    def deduplicate(self, articles: list[NewsArticle]) -> list[NewsArticle]:
        """Remove duplicate articles."""
        seen = set()
        unique = []
        for article in articles:
            key = (article.symbol, article.headline[:50], article.published_at.isoformat())
            if key not in seen:
                seen.add(key)
                unique.append(article)
        return unique


class CatalystDetector:
    """Detect catalysts from news and filings."""

    CATALYST_KEYWORDS = {
        CatalystCategory.EARNINGS: ["earnings", "eps", "revenue beat", "quarterly results"],
        CatalystCategory.CONTRACT: ["contract", "agreement", "partnership deal", "signed"],
        CatalystCategory.CLINICAL_TRIAL: [
            "clinical trial",
            "fda approval",
            "phase 1",
            "phase 2",
            "phase 3",
        ],
        CatalystCategory.FDA: ["fda", "food and drug administration", "approval", "pdufa"],
        CatalystCategory.ACQUISITION: ["acquisition", "merger", "buyout", "tender offer"],
        CatalystCategory.FINANCING: [
            "offering",
            "at-the-market",
            "private placement",
            "shelf",
            "financing",
        ],
        CatalystCategory.REVERSE_SPLIT: ["reverse split", "stock split", "consolidation"],
        CatalystCategory.DELISTING: ["delisting", "compliance notice", "deficiency"],
        CatalystCategory.GOVERNMENT_CONTRACT: [
            "government contract",
            "federal award",
            "military contract",
        ],
        CatalystCategory.CUSTOMER_WIN: ["customer win", "new client", "major customer"],
        CatalystCategory.MANAGEMENT_CHANGE: ["ceo", "cfo", "ceo resignation", "board appointment"],
        CatalystCategory.GUIDANCE: ["guidance", "outlook", "forecast", "revenue guidance"],
    }

    async def detect(
        self,
        article: NewsArticle,
    ) -> dict[str, Any]:
        """Detect catalyst from article text."""
        text = f"{article.headline} {article.summary or ''} {article.body or ''}".lower()

        detected_categories = []
        for category, keywords in self.CATALYST_KEYWORDS.items():
            for keyword in keywords:
                if keyword.lower() in text:
                    detected_categories.append(category.value)
                    break

        # Determine strength
        strength = "weak"
        if len(detected_categories) >= 2:
            strength = "moderate"
        if len(detected_categories) >= 3:
            strength = "strong"

        # Determine impact
        impact = ImpactLevel.MEDIUM
        if any(
            c in ["FDA", "clinical_trial", "acquisition", "merger", "delisting"]
            for c in detected_categories
        ):
            impact = ImpactLevel.HIGH
        elif any(c in ["earnings", "guidance", "contract"] for c in detected_categories):
            impact = ImpactLevel.MEDIUM

        return {
            "categories": detected_categories,
            "strength": strength,
            "impact": impact.value,
            "confidence": min(0.5 + len(detected_categories) * 0.15, 0.95),
            "is_material": impact == ImpactLevel.HIGH,
        }
