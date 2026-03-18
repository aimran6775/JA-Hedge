"""
Phase 12 — Google Trends Integration.

Uses the unofficial pytrends-style API (or direct Google Trends endpoints)
to get search interest data for topics related to Kalshi markets.

Search interest is a leading indicator: public attention spikes
before events resolve. High search volume + extreme Kalshi prices
= strong signal.

No API key needed — uses Google's public Trends endpoint.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.intelligence.base import DataSource, DataSourceType, SourceHealth, SourceSignal
from app.logging_config import get_logger

log = get_logger("intelligence.trends")

# Queries mapped to Kalshi market categories
TREND_QUERIES = {
    "politics": ["trump news", "biden news", "congress vote", "government shutdown", "election 2026"],
    "economics": ["inflation rate", "recession", "fed rate decision", "stock market crash", "unemployment"],
    "crypto": ["bitcoin price", "crypto crash", "ethereum", "bitcoin etf"],
    "weather": ["hurricane tracker", "tornado warning", "blizzard", "heat wave"],
    "sports": ["nba scores", "nfl scores", "mlb scores", "ufc fight"],
}

# Google Trends API endpoint (public, no key)
TRENDS_API = "https://trends.google.com/trends/api"


class GoogleTrendsSource(DataSource):
    """
    Google Trends search interest data for market sentiment analysis.
    """

    def __init__(
        self,
        poll_interval: float = 600.0,  # Every 10 minutes
        enabled: bool = True,
    ) -> None:
        self._poll_interval = poll_interval
        self._enabled = enabled
        self._client: httpx.AsyncClient | None = None

        self._trends_cache: dict[str, dict[str, Any]] = {}
        self._stats = {
            "fetches": 0, "errors": 0, "queries_resolved": 0, "total_signals": 0,
        }

    @property
    def name(self) -> str:
        return "google_trends"

    @property
    def source_type(self) -> DataSourceType:
        return DataSourceType.TRENDS

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
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/120.0.0.0 Safari/537.36",
            },
            follow_redirects=True,
        )
        log.info("google_trends_started")

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def fetch_signals(self, tickers: list[str] | None = None) -> list[SourceSignal]:
        if not self._client:
            return []

        signals: list[SourceSignal] = []

        # Fetch daily search trends (public endpoint)
        try:
            trending = await self._fetch_daily_trends()
            if trending:
                signals.extend(trending)
        except Exception as e:
            self._stats["errors"] += 1
            log.debug("trends_daily_error", error=str(e))

        # Fetch real-time trending searches
        try:
            realtime = await self._fetch_realtime_trends()
            if realtime:
                signals.extend(realtime)
        except Exception as e:
            self._stats["errors"] += 1
            log.debug("trends_realtime_error", error=str(e))

        self._stats["total_signals"] += len(signals)
        return signals

    async def _fetch_daily_trends(self) -> list[SourceSignal]:
        """Fetch Google's daily trending searches."""
        if not self._client:
            return []

        signals: list[SourceSignal] = []

        try:
            url = f"{TRENDS_API}/dailytrends"
            params = {"hl": "en-US", "geo": "US", "ed": "", "ns": "15"}
            resp = await self._client.get(url, params=params)
            self._stats["fetches"] += 1

            if resp.status_code != 200:
                self._stats["errors"] += 1
                return []

            # Google prepends ")]}',\n" to prevent XSSI
            text = resp.text
            if text.startswith(")]}'"):
                text = text[5:]

            import json
            data = json.loads(text)

            trending_days = data.get("default", {}).get("trendingSearchesDays", [])
            for day in trending_days[:1]:  # Just today
                for search in day.get("trendingSearches", [])[:20]:
                    title_data = search.get("title", {})
                    query = title_data.get("query", "")
                    traffic = search.get("formattedTraffic", "0")
                    articles = search.get("articles", [])

                    if not query:
                        continue

                    # Parse traffic volume
                    traffic_num = self._parse_traffic(traffic)

                    # Categorise
                    category = self._categorize_query(query)

                    # Get article sentiment
                    sentiment = 0.0
                    headline = ""
                    if articles:
                        headline = articles[0].get("title", "")
                        from app.intelligence.sources.news_sentiment import NewsSentimentEngine
                        sentiment = NewsSentimentEngine._score_sentiment(
                            " ".join(a.get("title", "") for a in articles[:3])
                        )

                    self._trends_cache[query.lower()] = {
                        "query": query,
                        "traffic": traffic_num,
                        "category": category,
                        "sentiment": sentiment,
                        "timestamp": time.time(),
                    }

                    signals.append(SourceSignal(
                        source_name=self.name,
                        source_type=self.source_type,
                        ticker=f"trends:{category or 'general'}:{query.lower().replace(' ', '_')[:30]}",
                        signal_value=sentiment,
                        confidence=min(0.6, 0.2 + traffic_num / 500000),
                        category=category or "general",
                        headline=headline or f"Trending: {query}",
                        features={
                            "trend_traffic": traffic_num,
                            "trend_sentiment": round(sentiment, 4),
                            "trend_category_match": 1.0 if category else 0.0,
                        },
                        raw_data={
                            "query": query,
                            "traffic": traffic,
                            "article_count": len(articles),
                        },
                    ))
                    self._stats["queries_resolved"] += 1

        except Exception as e:
            self._stats["errors"] += 1
            log.debug("daily_trends_error", error=str(e))

        return signals

    async def _fetch_realtime_trends(self) -> list[SourceSignal]:
        """Fetch real-time trending stories from Google Trends."""
        if not self._client:
            return []

        signals: list[SourceSignal] = []

        try:
            url = f"{TRENDS_API}/realtimetrends"
            params = {"hl": "en-US", "geo": "US", "cat": "all", "fi": "0", "fs": "0", "ri": "300", "rs": "20"}
            resp = await self._client.get(url, params=params)
            self._stats["fetches"] += 1

            if resp.status_code != 200:
                return []

            text = resp.text
            if text.startswith(")]}'"):
                text = text[5:]

            import json
            data = json.loads(text)

            stories = data.get("storySummaries", {}).get("trendingStories", [])
            for story in stories[:15]:
                title = story.get("title", "")
                entity_names = [e.get("title", "") for e in story.get("entityNames", [])]
                articles = story.get("articles", [])

                if not title:
                    continue

                full_text = title + " " + " ".join(entity_names)
                category = self._categorize_query(full_text)

                from app.intelligence.sources.news_sentiment import NewsSentimentEngine
                sentiment = NewsSentimentEngine._score_sentiment(
                    " ".join(a.get("articleTitle", "") for a in articles[:3])
                )

                signals.append(SourceSignal(
                    source_name=self.name,
                    source_type=self.source_type,
                    ticker=f"trends:realtime:{category or 'general'}",
                    signal_value=sentiment,
                    confidence=0.50,
                    category=category or "general",
                    headline=title[:200],
                    features={
                        "realtime_trend": 1.0,
                        "trend_article_count": len(articles),
                        "trend_entity_count": len(entity_names),
                    },
                    raw_data={"title": title, "entities": entity_names[:5]},
                ))

        except Exception as e:
            self._stats["errors"] += 1
            log.debug("realtime_trends_error", error=str(e))

        return signals

    @staticmethod
    def _parse_traffic(traffic_str: str) -> float:
        """Parse traffic like '200K+' or '1M+' to numeric."""
        s = traffic_str.replace("+", "").replace(",", "").strip()
        multiplier = 1
        if s.endswith("K"):
            multiplier = 1000
            s = s[:-1]
        elif s.endswith("M"):
            multiplier = 1_000_000
            s = s[:-1]
        try:
            return float(s) * multiplier
        except ValueError:
            return 0

    @staticmethod
    def _categorize_query(query: str) -> str:
        """Categorise a search query by Kalshi market type."""
        q = query.lower()
        for cat, keywords in TREND_QUERIES.items():
            for kw in keywords:
                if kw.lower() in q:
                    return cat
        # Fallback keyword checks
        if any(w in q for w in ["trump", "biden", "congress", "election", "vote"]):
            return "politics"
        if any(w in q for w in ["bitcoin", "crypto", "ethereum"]):
            return "crypto"
        if any(w in q for w in ["nba", "nfl", "mlb", "nhl", "ufc"]):
            return "sports"
        if any(w in q for w in ["hurricane", "tornado", "flood", "fire"]):
            return "weather"
        return ""

    def get_trending(self, limit: int = 20) -> list[dict]:
        """Get current trending topics for dashboard."""
        items = sorted(
            self._trends_cache.values(),
            key=lambda x: x.get("traffic", 0),
            reverse=True,
        )[:limit]
        return items

    def health(self) -> SourceHealth:
        return SourceHealth(
            name=self.name,
            source_type=self.source_type,
            enabled=self._enabled,
            healthy=self._stats["errors"] < self._stats["fetches"] + 1,
            total_fetches=self._stats["fetches"],
            total_errors=self._stats["errors"],
            total_signals=self._stats["total_signals"],
        )
