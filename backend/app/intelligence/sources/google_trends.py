"""
Phase 24 \u2014 Google Trends via public RSS feed.

The old /trends/api/dailytrends and /trends/api/realtimetrends
endpoints now return 404. Google replaced them with a Trending
RSS feed that returns XML with today's trending searches.

RSS URL: https://trends.google.com/trending/rss?geo=US
Returns ~20 trending topics with title and approximate traffic.

No API key needed.
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from app.intelligence.base import DataSource, DataSourceType, SourceHealth, SourceSignal
from app.logging_config import get_logger

log = get_logger("intelligence.trends")

# Queries mapped to Kalshi market categories (for keyword matching)
TREND_QUERIES = {
    "politics": ["trump", "biden", "congress", "vote", "government shutdown",
                 "election", "senate", "house", "supreme court", "republican", "democrat"],
    "economics": ["inflation", "recession", "fed rate", "stock market",
                  "unemployment", "gdp", "jobs report", "interest rate", "tariff"],
    "crypto": ["bitcoin", "crypto", "ethereum", "bitcoin etf", "solana", "dogecoin"],
    "weather": ["hurricane", "tornado", "blizzard", "heat wave", "flood",
                "wildfire", "earthquake", "storm", "weather"],
    "sports": ["nba", "nfl", "mlb", "nhl", "ufc", "ncaa", "championship",
               "playoffs", "world series", "super bowl"],
}

# Google Trends RSS (public, no key)
TRENDS_RSS_URL = "https://trends.google.com/trending/rss?geo=US"

# Namespace for the Atom feed
HT_NS = {"ht": "https://trends.google.com/trending/rss"}


class GoogleTrendsSource(DataSource):
    """
    Google Trends search interest data for market sentiment analysis.

    Uses the public RSS feed to get today's trending searches,
    categorises them by Kalshi market type, and emits signals.
    """

    def __init__(
        self,
        poll_interval: float = 600.0,
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
                              "Chrome/125.0.0.0 Safari/537.36",
            },
            follow_redirects=True,
        )
        log.info("google_trends_started", source="rss")

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def fetch_signals(self, tickers: list[str] | None = None) -> list[SourceSignal]:
        if not self._client:
            return []

        signals: list[SourceSignal] = []

        try:
            trending = await self._fetch_trending_rss()
            if trending:
                signals.extend(trending)
        except Exception as e:
            self._stats["errors"] += 1
            log.debug("trends_rss_error", error=str(e))

        self._stats["total_signals"] += len(signals)
        return signals

    async def _fetch_trending_rss(self) -> list[SourceSignal]:
        """Fetch Google Trending RSS feed and parse into signals."""
        if not self._client:
            return []

        signals: list[SourceSignal] = []

        try:
            resp = await self._client.get(TRENDS_RSS_URL)
            self._stats["fetches"] += 1

            if resp.status_code != 200:
                self._stats["errors"] += 1
                log.debug("trends_rss_http_error", status=resp.status_code)
                return []

            root = ET.fromstring(resp.text)

            # RSS 2.0: channel/item
            channel = root.find("channel")
            if channel is None:
                return []

            items = channel.findall("item")

            for item in items[:25]:
                title_el = item.find("title")
                if title_el is None or not title_el.text:
                    continue
                query = title_el.text.strip()

                # Approximate traffic from ht:approx_traffic
                traffic_el = item.find("ht:approx_traffic", HT_NS)
                traffic_str = traffic_el.text.strip() if traffic_el is not None and traffic_el.text else "0"
                traffic_num = self._parse_traffic(traffic_str)

                # Description may contain related news
                desc_el = item.find("description")
                description = desc_el.text.strip() if desc_el is not None and desc_el.text else ""

                # Categorise
                category = self._categorize_query(query + " " + description)

                # Simple sentiment from description keywords
                sentiment = self._simple_sentiment(description)

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
                    confidence=min(0.6, 0.2 + traffic_num / 500_000),
                    category=category or "general",
                    headline=f"Trending: {query}" + (f" ({traffic_str})" if traffic_str != "0" else ""),
                    features={
                        "trend_traffic": traffic_num,
                        "trend_sentiment": round(sentiment, 4),
                        "trend_category_match": 1.0 if category else 0.0,
                    },
                    raw_data={
                        "query": query,
                        "traffic": traffic_str,
                        "description": description[:200],
                    },
                ))
                self._stats["queries_resolved"] += 1

        except ET.ParseError as e:
            self._stats["errors"] += 1
            log.debug("trends_rss_parse_error", error=str(e))
        except Exception as e:
            self._stats["errors"] += 1
            log.debug("trends_rss_error", error=str(e))

        return signals

    @staticmethod
    def _parse_traffic(traffic_str: str) -> float:
        """Parse traffic like '200K+' or '1M+' to numeric."""
        s = traffic_str.replace("+", "").replace(",", "").strip()
        multiplier = 1
        if s.endswith("K"):
            multiplier = 1_000
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
        return ""

    @staticmethod
    def _simple_sentiment(text: str) -> float:
        """Quick keyword-based sentiment score (-1 to +1)."""
        if not text:
            return 0.0
        t = text.lower()
        pos = sum(1 for w in ["win", "surge", "rise", "gain", "record", "boost", "rally"]
                  if w in t)
        neg = sum(1 for w in ["crash", "fall", "drop", "loss", "fear", "crisis", "decline", "kill"]
                  if w in t)
        total = pos + neg
        if total == 0:
            return 0.0
        return (pos - neg) / total

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
