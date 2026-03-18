"""
Phase 4 — Twitter/X Social Signals.

Monitors public social media sentiment via free, no-auth methods:
  • Nitter instances (public Twitter frontend, no API key)
  • RSS bridges for trending topics
  • Public Twitter embed endpoints

Extracts social momentum, sentiment spikes, and volume surges
for all Kalshi market categories.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.intelligence.base import DataSource, DataSourceType, SourceHealth, SourceSignal
from app.logging_config import get_logger

log = get_logger("intelligence.social")

# Search queries mapped to Kalshi categories
SOCIAL_QUERIES = {
    "politics": ["trump", "biden", "congress", "senate vote", "executive order"],
    "economics": ["inflation", "fed rate", "jobs report", "recession", "GDP"],
    "crypto": ["bitcoin", "ethereum", "crypto", "btc price"],
    "weather": ["hurricane", "tornado warning", "wildfire", "severe weather"],
    "sports": ["NBA", "NFL", "MLB", "NHL", "UFC"],
    "tech": ["OpenAI", "NVIDIA", "AI regulation"],
}

# Nitter instances (rotating, some may be down)
NITTER_INSTANCES = [
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.woodland.cafe",
]


@dataclass
class SocialPost:
    """A parsed social media post."""
    text: str
    author: str = ""
    likes: int = 0
    retweets: int = 0
    timestamp: float = 0.0
    category: str = ""
    sentiment: float = 0.0
    engagement: float = 0.0  # normalised engagement score


class SocialSignalSource(DataSource):
    """
    Social media sentiment monitor using free public endpoints.
    """

    def __init__(
        self,
        poll_interval: float = 180.0,
        enabled: bool = True,
    ) -> None:
        self._poll_interval = poll_interval
        self._enabled = enabled
        self._client: httpx.AsyncClient | None = None
        self._working_nitter: str | None = None

        # State
        self._post_cache: list[SocialPost] = []
        self._category_sentiment: dict[str, float] = {}
        self._category_volume: dict[str, int] = Counter()
        self._stats = {
            "fetches": 0, "errors": 0, "posts_parsed": 0,
            "total_signals": 0,
        }

    @property
    def name(self) -> str:
        return "social_twitter"

    @property
    def source_type(self) -> DataSourceType:
        return DataSourceType.SOCIAL

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def poll_interval_seconds(self) -> float:
        return self._poll_interval

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(20.0),
            headers={"User-Agent": "Mozilla/5.0 (compatible; JA-Hedge/1.0)"},
            follow_redirects=True,
        )
        # Find a working Nitter instance
        await self._find_working_nitter()
        log.info("social_signal_started", nitter=self._working_nitter)

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _find_working_nitter(self) -> None:
        """Probe Nitter instances to find one that's up."""
        if not self._client:
            return

        for instance in NITTER_INSTANCES:
            try:
                resp = await self._client.get(f"{instance}/search?q=test", timeout=10.0)
                if resp.status_code == 200:
                    self._working_nitter = instance
                    return
            except Exception:
                continue

        log.warning("no_working_nitter", tried=len(NITTER_INSTANCES))

    async def fetch_signals(self, tickers: list[str] | None = None) -> list[SourceSignal]:
        if not self._client:
            return []

        signals: list[SourceSignal] = []

        for category, queries in SOCIAL_QUERIES.items():
            posts = await self._search_social(queries, category)
            if not posts:
                continue

            # Compute category-level sentiment
            sentiments = [p.sentiment for p in posts]
            engagements = [p.engagement for p in posts]

            avg_sentiment = sum(sentiments) / len(sentiments)
            max_engagement = max(engagements) if engagements else 0
            volume = len(posts)

            self._category_sentiment[category] = avg_sentiment
            self._category_volume[category] = volume

            confidence = min(0.7, 0.2 + volume * 0.02)

            signals.append(SourceSignal(
                source_name=self.name,
                source_type=self.source_type,
                ticker=f"social:{category}",
                signal_value=avg_sentiment,
                confidence=confidence,
                edge_estimate=avg_sentiment * 0.02,
                category=category,
                headline=posts[0].text[:120] if posts else "",
                features={
                    "social_sentiment": round(avg_sentiment, 4),
                    "social_volume": volume,
                    "social_max_engagement": round(max_engagement, 2),
                    "social_sentiment_std": round(
                        (sum((s - avg_sentiment) ** 2 for s in sentiments) / len(sentiments)) ** 0.5, 4
                    ) if len(sentiments) > 1 else 0.0,
                    "social_positive_ratio": round(sum(1 for s in sentiments if s > 0) / len(sentiments), 3),
                },
                raw_data={
                    "post_count": volume,
                    "top_posts": [p.text[:200] for p in sorted(posts, key=lambda p: p.engagement, reverse=True)[:3]],
                    "queries": queries,
                },
            ))

        self._stats["total_signals"] += len(signals)
        return signals

    async def _search_social(self, queries: list[str], category: str) -> list[SocialPost]:
        """Search for posts matching queries via available methods."""
        posts: list[SocialPost] = []

        # Method 1: Try Nitter search
        if self._working_nitter:
            for query in queries[:2]:  # Limit queries per category
                try:
                    nitter_posts = await self._search_nitter(query, category)
                    posts.extend(nitter_posts)
                    await asyncio.sleep(2)  # Be polite
                except Exception as e:
                    self._stats["errors"] += 1
                    log.debug("nitter_search_error", query=query, error=str(e))

        self._stats["fetches"] += 1
        self._post_cache.extend(posts)
        if len(self._post_cache) > 5000:
            self._post_cache = self._post_cache[-3000:]

        return posts

    async def _search_nitter(self, query: str, category: str) -> list[SocialPost]:
        """Search Nitter (Twitter frontend) for recent posts."""
        if not self._client or not self._working_nitter:
            return []

        posts: list[SocialPost] = []

        try:
            url = f"{self._working_nitter}/search"
            params = {"f": "tweets", "q": query}
            resp = await self._client.get(url, params=params)

            if resp.status_code != 200:
                # Try to find another working instance
                await self._find_working_nitter()
                return []

            html = resp.text
            posts = self._parse_nitter_html(html, category)
            self._stats["posts_parsed"] += len(posts)

        except Exception as e:
            self._stats["errors"] += 1
            log.debug("nitter_error", error=str(e))

        return posts

    def _parse_nitter_html(self, html: str, category: str) -> list[SocialPost]:
        """Parse Nitter HTML search results into SocialPost objects."""
        posts: list[SocialPost] = []

        # Extract tweet text blocks (Nitter uses .tweet-content class)
        tweet_pattern = re.compile(
            r'class="tweet-content[^"]*"[^>]*>(.*?)</div>',
            re.DOTALL,
        )
        stat_pattern = re.compile(
            r'class="tweet-stat[^"]*"[^>]*>.*?(\d[\d,]*)',
            re.DOTALL,
        )

        texts = tweet_pattern.findall(html)
        stats = stat_pattern.findall(html)

        for i, raw_text in enumerate(texts[:20]):
            # Strip HTML tags
            clean = re.sub(r'<[^>]+>', '', raw_text).strip()
            if len(clean) < 10:
                continue

            # Get engagement (likes/retweets approximation)
            engagement = 0.0
            stat_idx = i * 4  # Nitter shows 4 stats per tweet
            if stat_idx < len(stats):
                try:
                    val = int(stats[stat_idx].replace(",", ""))
                    engagement = min(1.0, val / 1000)
                except ValueError:
                    pass

            sentiment = self._score_post(clean)

            posts.append(SocialPost(
                text=clean[:500],
                timestamp=time.time(),
                category=category,
                sentiment=sentiment,
                engagement=engagement,
            ))

        return posts

    @staticmethod
    def _score_post(text: str) -> float:
        """Simple sentiment scoring for a social post."""
        from app.intelligence.sources.news_sentiment import POSITIVE_WORDS, NEGATIVE_WORDS
        words = set(re.findall(r'\b\w+\b', text.lower()))
        pos = len(words & POSITIVE_WORDS)
        neg = len(words & NEGATIVE_WORDS)
        total = pos + neg
        if total == 0:
            return 0.0
        return (pos - neg) / total

    def get_category_sentiment(self) -> dict[str, dict]:
        """Get current sentiment by category for the dashboard."""
        return {
            cat: {
                "sentiment": round(self._category_sentiment.get(cat, 0.0), 4),
                "volume": self._category_volume.get(cat, 0),
            }
            for cat in SOCIAL_QUERIES
        }

    def health(self) -> SourceHealth:
        return SourceHealth(
            name=self.name,
            source_type=self.source_type,
            enabled=self._enabled,
            healthy=self._working_nitter is not None,
            total_fetches=self._stats["fetches"],
            total_errors=self._stats["errors"],
            total_signals=self._stats["total_signals"],
        )
