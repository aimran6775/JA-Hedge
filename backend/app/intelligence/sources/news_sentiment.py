"""
Phase 3 — News Sentiment Engine.

Aggregates news from free sources and extracts sentiment signals:
  • GDELT Project (free, no key) — global event monitoring
  • NewsAPI.org (free tier: 100 req/day)
  • RSS feeds from major outlets (AP, Reuters, BBC — unlimited)

Sentiment is computed via keyword-rule scoring (fast, no ML dependency)
with an option to upgrade to a transformer model later.
"""

from __future__ import annotations

import asyncio
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.intelligence.base import DataSource, DataSourceType, SourceHealth, SourceSignal
from app.logging_config import get_logger

log = get_logger("intelligence.news")

# ── Sentiment keyword dictionaries ───────────────────────────────────────────

POSITIVE_WORDS = frozenset({
    "surge", "surges", "soars", "rally", "rallies", "boom", "booming",
    "win", "wins", "winning", "victory", "beat", "beats", "passes",
    "approved", "signed", "agreement", "deal", "record", "strong",
    "growth", "growing", "increase", "rises", "rising", "gain",
    "gains", "bullish", "optimistic", "success", "successful",
    "upgrade", "breakthrough", "exceeded", "surpassed", "positive",
    "recover", "recovery", "momentum", "confident", "unanimous",
})

NEGATIVE_WORDS = frozenset({
    "crash", "crashes", "plunge", "plunges", "drop", "drops", "falling",
    "decline", "declines", "loss", "losses", "lose", "loses", "defeat",
    "fail", "fails", "failure", "crisis", "warning", "risk", "fears",
    "concern", "concerns", "weak", "weakening", "bearish", "recession",
    "inflation", "shutdown", "collapse", "slump", "downturn", "threat",
    "reject", "rejected", "veto", "scandal", "investigation", "indicted",
    "layoffs", "bankruptcy", "default", "sanctions", "war", "conflict",
})

# Kalshi category keyword mappings for ticker matching
CATEGORY_KEYWORDS = {
    "politics": ["trump", "biden", "congress", "senate", "house", "election",
                  "democrat", "republican", "gop", "vote", "impeach", "bill",
                  "executive order", "president", "governor", "legislation"],
    "economics": ["fed", "federal reserve", "inflation", "gdp", "jobs",
                   "unemployment", "interest rate", "cpi", "recession",
                   "treasury", "debt ceiling", "tariff", "trade war"],
    "crypto": ["bitcoin", "btc", "ethereum", "eth", "crypto", "cryptocurrency",
               "blockchain", "defi", "nft", "sec crypto", "coinbase", "binance"],
    "weather": ["hurricane", "tornado", "earthquake", "flood", "wildfire",
                "storm", "blizzard", "drought", "heatwave", "climate"],
    "sports": ["nba", "nfl", "mlb", "nhl", "ncaa", "ufc", "boxing",
               "playoffs", "championship", "super bowl", "world series"],
    "tech": ["ai", "artificial intelligence", "openai", "chatgpt", "meta",
             "apple", "google", "microsoft", "nvidia", "semiconductor"],
}

# RSS feeds — free, no API key required (verified working April 2026)
RSS_FEEDS = {
    # Major news (politics, economics, general)
    "bbc_world": "http://feeds.bbci.co.uk/news/world/rss.xml",
    "bbc_business": "http://feeds.bbci.co.uk/news/business/rss.xml",
    "cnbc_economy": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258",
    "nyt_politics": "https://rss.nytimes.com/services/xml/rss/nyt/Politics.xml",
    "nyt_home": "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
    "cnn_politics": "http://rss.cnn.com/rss/cnn_allpolitics.rss",
    "wsj_world": "https://feeds.a.dj.com/rss/RSSWorldNews.xml",
    "guardian_world": "https://www.theguardian.com/world/rss",
    "guardian_biz": "https://www.theguardian.com/uk/business/rss",
    "npr_news": "https://feeds.npr.org/1001/rss.xml",
    # Finance / markets
    "yahoo_finance": "https://finance.yahoo.com/news/rssindex",
    "marketwatch": "http://feeds.marketwatch.com/marketwatch/topstories/",
    # Crypto
    "coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    # Sports
    "espn_top": "https://www.espn.com/espn/rss/news",
}


@dataclass
class NewsArticle:
    """Parsed news article with sentiment."""
    title: str
    source: str
    url: str = ""
    published: float = 0.0
    category: str = ""
    sentiment: float = 0.0  # -1.0 to +1.0
    relevance: float = 0.0  # 0.0 to 1.0


class NewsSentimentEngine(DataSource):
    """
    Multi-source news aggregator with rule-based sentiment scoring.
    """

    def __init__(
        self,
        newsapi_key: str = "",
        poll_interval: float = 120.0,
        enabled: bool = True,
    ) -> None:
        self._newsapi_key = newsapi_key
        self._poll_interval = poll_interval
        self._enabled = enabled
        self._client: httpx.AsyncClient | None = None

        # Caches
        self._article_cache: list[NewsArticle] = []
        self._seen_urls: set[str] = set()
        self._stats = {
            "rss_fetches": 0, "rss_errors": 0, "rss_articles": 0,
            "gdelt_fetches": 0, "gdelt_errors": 0, "gdelt_articles": 0,
            "newsapi_fetches": 0, "newsapi_errors": 0, "newsapi_articles": 0,
            "total_signals": 0,
        }

    @property
    def name(self) -> str:
        return "news_sentiment"

    @property
    def source_type(self) -> DataSourceType:
        return DataSourceType.NEWS

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def poll_interval_seconds(self) -> float:
        return self._poll_interval

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(20.0),
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            },
            follow_redirects=True,
        )
        log.info("news_sentiment_started", has_newsapi=bool(self._newsapi_key))

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def fetch_signals(self, tickers: list[str] | None = None) -> list[SourceSignal]:
        if not self._client:
            return []

        # Fetch from all sources concurrently
        async def _noop():
            return []

        results = await asyncio.gather(
            self._fetch_rss(),
            self._fetch_gdelt(),
            self._fetch_newsapi() if self._newsapi_key else _noop(),
            return_exceptions=True,
        )

        articles: list[NewsArticle] = []
        for r in results:
            if isinstance(r, list):
                articles.extend(r)

        # Deduplicate
        new_articles = []
        for art in articles:
            key = art.url or art.title
            if key not in self._seen_urls:
                self._seen_urls.add(key)
                new_articles.append(art)

        # Keep cache bounded
        self._article_cache.extend(new_articles)
        if len(self._article_cache) > 5000:
            self._article_cache = self._article_cache[-3000:]
        if len(self._seen_urls) > 10000:
            self._seen_urls = set(list(self._seen_urls)[-5000:])

        # Generate signals per category
        signals = self._articles_to_signals(new_articles)
        self._stats["total_signals"] += len(signals)
        return signals

    # ── RSS Feeds ─────────────────────────────────────────────────────

    async def _fetch_rss(self) -> list[NewsArticle]:
        """Fetch and parse RSS feeds."""
        if not self._client:
            return []

        articles: list[NewsArticle] = []

        for feed_name, url in RSS_FEEDS.items():
            try:
                resp = await self._client.get(url)
                self._stats["rss_fetches"] += 1

                if resp.status_code != 200:
                    self._stats["rss_errors"] += 1
                    continue

                parsed = self._parse_rss(resp.text, feed_name)
                articles.extend(parsed)
                self._stats["rss_articles"] += len(parsed)

            except Exception as e:
                self._stats["rss_errors"] += 1
                log.debug("rss_error", feed=feed_name, error=str(e))

        return articles

    def _parse_rss(self, xml_text: str, source: str) -> list[NewsArticle]:
        """Parse RSS XML into NewsArticle objects."""
        articles: list[NewsArticle] = []
        try:
            root = ET.fromstring(xml_text)
            # Handle both RSS 2.0 and Atom
            items = root.findall(".//item")
            if not items:
                items = root.findall(".//{http://www.w3.org/2005/Atom}entry")

            for item in items[:30]:  # Cap per feed
                title_el = item.find("title")
                if title_el is None:
                    title_el = item.find("{http://www.w3.org/2005/Atom}title")
                link_el = item.find("link")
                if link_el is None:
                    link_el = item.find("{http://www.w3.org/2005/Atom}link")
                title = (title_el.text or "").strip() if title_el is not None else ""
                url = ""
                if link_el is not None:
                    url = link_el.text or link_el.get("href", "") or ""

                if not title:
                    continue

                sentiment = self._score_sentiment(title)
                category = self._categorize(title)

                articles.append(NewsArticle(
                    title=title,
                    source=source,
                    url=url.strip(),
                    published=time.time(),
                    category=category,
                    sentiment=sentiment,
                    relevance=0.5 if category else 0.2,
                ))
        except ET.ParseError:
            pass

        return articles

    # ── GDELT ─────────────────────────────────────────────────────────

    async def _fetch_gdelt(self) -> list[NewsArticle]:
        """Fetch latest events from GDELT GKG (Global Knowledge Graph)."""
        if not self._client:
            return []

        articles: list[NewsArticle] = []

        try:
            # GDELT DOC API — free, no key
            url = "https://api.gdeltproject.org/api/v2/doc/doc"
            params = {
                "query": "economy OR markets OR election OR crypto OR bitcoin OR weather extreme",
                "mode": "ArtList",
                "maxrecords": "50",
                "format": "json",
                "timespan": "4h",
            }
            resp = await self._client.get(url, params=params)
            self._stats["gdelt_fetches"] += 1

            if resp.status_code != 200:
                self._stats["gdelt_errors"] += 1
                return []

            data = resp.json()
            for art in data.get("articles", [])[:30]:
                title = art.get("title", "")
                url_str = art.get("url", "")
                tone = art.get("tone", 0)  # GDELT tone score

                # GDELT tone: negative values = negative sentiment
                sentiment = max(-1.0, min(1.0, tone / 10.0))
                category = self._categorize(title)

                articles.append(NewsArticle(
                    title=title,
                    source="gdelt",
                    url=url_str,
                    published=time.time(),
                    category=category,
                    sentiment=sentiment,
                    relevance=0.4 if category else 0.1,
                ))
                self._stats["gdelt_articles"] += 1

        except Exception as e:
            self._stats["gdelt_errors"] += 1
            log.debug("gdelt_error", error=str(e))

        return articles

    # ── NewsAPI ───────────────────────────────────────────────────────

    async def _fetch_newsapi(self) -> list[NewsArticle]:
        """Fetch from NewsAPI.org (100 req/day free tier)."""
        if not self._client or not self._newsapi_key:
            return []

        articles: list[NewsArticle] = []

        try:
            url = "https://newsapi.org/v2/top-headlines"
            params = {
                "country": "us",
                "pageSize": "50",
                "apiKey": self._newsapi_key,
            }
            resp = await self._client.get(url, params=params)
            self._stats["newsapi_fetches"] += 1

            if resp.status_code != 200:
                self._stats["newsapi_errors"] += 1
                return []

            data = resp.json()
            for art in data.get("articles", []):
                title = art.get("title", "")
                url_str = art.get("url", "")
                source_name = art.get("source", {}).get("name", "newsapi")

                sentiment = self._score_sentiment(title)
                category = self._categorize(title)

                articles.append(NewsArticle(
                    title=title,
                    source=f"newsapi:{source_name}",
                    url=url_str,
                    published=time.time(),
                    category=category,
                    sentiment=sentiment,
                    relevance=0.6 if category else 0.3,
                ))
                self._stats["newsapi_articles"] += 1

        except Exception as e:
            self._stats["newsapi_errors"] += 1
            log.debug("newsapi_error", error=str(e))

        return articles

    # ── Sentiment Scoring ─────────────────────────────────────────────

    @staticmethod
    def _score_sentiment(text: str) -> float:
        """Rule-based sentiment scoring. Returns -1.0 to +1.0."""
        words = set(re.findall(r'\b\w+\b', text.lower()))
        pos = len(words & POSITIVE_WORDS)
        neg = len(words & NEGATIVE_WORDS)
        total = pos + neg
        if total == 0:
            return 0.0
        return (pos - neg) / total

    @staticmethod
    def _categorize(text: str) -> str:
        """Categorise text by Kalshi market categories."""
        text_lower = text.lower()
        best_cat = ""
        best_score = 0
        for cat, keywords in CATEGORY_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > best_score:
                best_score = score
                best_cat = cat
        return best_cat

    # ── Signal Generation ─────────────────────────────────────────────

    def _articles_to_signals(self, articles: list[NewsArticle]) -> list[SourceSignal]:
        """Convert recent articles into per-category sentiment signals."""
        # Group by category
        by_cat: dict[str, list[NewsArticle]] = {}
        for art in articles:
            if art.category:
                by_cat.setdefault(art.category, []).append(art)

        signals: list[SourceSignal] = []
        for category, arts in by_cat.items():
            if not arts:
                continue

            # Weighted average sentiment (more relevant = more weight)
            total_weight = sum(a.relevance for a in arts)
            if total_weight <= 0:
                continue

            avg_sent = sum(a.sentiment * a.relevance for a in arts) / total_weight
            confidence = min(0.8, 0.3 + len(arts) * 0.05)

            top_headlines = [a.title for a in sorted(arts, key=lambda a: abs(a.sentiment), reverse=True)[:3]]

            signals.append(SourceSignal(
                source_name=self.name,
                source_type=self.source_type,
                ticker=f"news:{category}",  # category-level signal
                signal_value=avg_sent,
                confidence=confidence,
                edge_estimate=avg_sent * 0.03,  # conservative edge mapping
                category=category,
                headline=top_headlines[0] if top_headlines else "",
                features={
                    "news_sentiment": round(avg_sent, 4),
                    "news_volume": len(arts),
                    "news_positive_ratio": round(sum(1 for a in arts if a.sentiment > 0) / len(arts), 3),
                    "news_negative_ratio": round(sum(1 for a in arts if a.sentiment < 0) / len(arts), 3),
                    "news_max_sentiment": round(max(a.sentiment for a in arts), 4),
                    "news_min_sentiment": round(min(a.sentiment for a in arts), 4),
                },
                raw_data={
                    "article_count": len(arts),
                    "top_headlines": top_headlines,
                    "sources": list(set(a.source for a in arts)),
                },
            ))

        return signals

    def get_recent_articles(self, category: str = "", limit: int = 50) -> list[dict]:
        """Get recent articles for the dashboard."""
        arts = self._article_cache
        if category:
            arts = [a for a in arts if a.category == category]
        arts = sorted(arts, key=lambda a: a.published, reverse=True)[:limit]
        return [
            {
                "title": a.title,
                "source": a.source,
                "url": a.url,
                "category": a.category,
                "sentiment": round(a.sentiment, 3),
                "relevance": round(a.relevance, 2),
                "age_minutes": round((time.time() - a.published) / 60, 1),
            }
            for a in arts
        ]

    def health(self) -> SourceHealth:
        total_fetches = self._stats["rss_fetches"] + self._stats["gdelt_fetches"] + self._stats["newsapi_fetches"]
        total_errors = self._stats["rss_errors"] + self._stats["gdelt_errors"] + self._stats["newsapi_errors"]
        return SourceHealth(
            name=self.name,
            source_type=self.source_type,
            enabled=self._enabled,
            healthy=total_errors < total_fetches + 1,
            total_fetches=total_fetches,
            total_errors=total_errors,
            total_signals=self._stats["total_signals"],
        )
