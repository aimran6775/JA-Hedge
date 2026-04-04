"""
Twitter/X Live Social Signals — Production-grade replacement.

Multiple free methods for real-time social sentiment:
  1. Bluesky public API (free, no auth, growing sports community)
  2. Google News RSS (real-time trending for any topic)
  3. RSSHub bridges for Twitter/X search feeds

Replaces the dead Nitter-based approach (Nitter shut down 2024).

Extracts:
  - Social momentum per Kalshi category
  - Sentiment spikes (breaking news, viral tweets)
  - Volume surges (unusual activity around a topic)
"""

from __future__ import annotations

import asyncio
import re
import time
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.intelligence.base import DataSource, DataSourceType, SourceHealth, SourceSignal
from app.logging_config import get_logger

log = get_logger("intelligence.twitter_live")

# ── Search queries per Kalshi category ────────────────────────────────────────

CATEGORY_QUERIES = {
    "politics": ["trump", "biden", "congress", "senate vote", "election", "executive order"],
    "economics": ["inflation rate", "fed rate decision", "jobs report", "recession", "GDP growth"],
    "crypto": ["bitcoin price", "ethereum", "crypto market", "BTC", "solana"],
    "weather": ["hurricane", "tornado warning", "wildfire", "severe weather alert"],
    "sports": ["NBA game", "NFL score", "MLB", "NHL", "UFC fight", "March Madness"],
    "tech": ["OpenAI", "NVIDIA stock", "AI regulation", "Apple", "Tesla stock"],
    "entertainment": ["box office", "streaming", "award show", "viral", "trending"],
}

# ── Bluesky public API (no auth needed for public search) ────────────────────

BLUESKY_SEARCH_URL = "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts"

# ── Google News RSS (reliable, real-time, no rate limit issues) ───────────────

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

# ── RSSHub bridges for Twitter/X (community-maintained, rotating) ─────────────

RSSHUB_INSTANCES = [
    "https://rsshub.app",
    "https://rsshub.rssforever.com",
]


@dataclass
class SocialPost:
    """A parsed social media post."""
    text: str
    author: str = ""
    likes: int = 0
    reposts: int = 0
    timestamp: float = 0.0
    category: str = ""
    sentiment: float = 0.0
    engagement: float = 0.0
    source_method: str = ""  # "bluesky", "google_news", "rsshub"


class TwitterLiveSource(DataSource):
    """
    Real-time social sentiment via free public endpoints.

    Priority chain:
      1. Bluesky public search API (most reliable, growing fast)
      2. Google News RSS (always works, great for breaking news)
      3. RSSHub Twitter bridges (best effort, may be down)
    """

    def __init__(
        self,
        poll_interval: float = 120.0,
        enabled: bool = True,
    ) -> None:
        self._poll_interval = poll_interval
        self._enabled = enabled
        self._client: httpx.AsyncClient | None = None

        # State
        self._post_cache: list[SocialPost] = []
        self._category_sentiment: dict[str, float] = {}
        self._category_volume: dict[str, int] = Counter()
        self._working_rsshub: str | None = None
        self._stats = {
            "fetches": 0, "errors": 0, "posts_parsed": 0,
            "bluesky_ok": 0, "google_ok": 0, "rsshub_ok": 0,
            "total_signals": 0,
        }

    @property
    def name(self) -> str:
        return "twitter_live"

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
            headers={"User-Agent": "Mozilla/5.0 (compatible; JA-Hedge/2.0)"},
            follow_redirects=True,
        )
        # Find a working RSSHub instance
        await self._find_working_rsshub()
        log.info("twitter_live_started",
                 rsshub=self._working_rsshub,
                 methods=["bluesky", "google_news", "rsshub"])

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _find_working_rsshub(self) -> None:
        """Probe RSSHub instances."""
        if not self._client:
            return
        for instance in RSSHUB_INSTANCES:
            try:
                resp = await self._client.get(f"{instance}/twitter/trending", timeout=8.0)
                if resp.status_code == 200:
                    self._working_rsshub = instance
                    return
            except Exception:
                continue
        log.debug("no_working_rsshub")

    # ── Main fetch ────────────────────────────────────────────────────

    async def fetch_signals(self, tickers: list[str] | None = None) -> list[SourceSignal]:
        if not self._client:
            return []

        signals: list[SourceSignal] = []
        self._stats["fetches"] += 1

        for category, queries in CATEGORY_QUERIES.items():
            posts: list[SocialPost] = []

            # Try each method in priority order
            for query in queries[:3]:  # Limit queries per category
                # Method 1: Bluesky
                bsky_posts = await self._search_bluesky(query, category)
                posts.extend(bsky_posts)

                # Method 2: Google News RSS
                gnews_posts = await self._search_google_news(query, category)
                posts.extend(gnews_posts)

                # Method 3: RSSHub Twitter bridge
                if self._working_rsshub:
                    rsshub_posts = await self._search_rsshub(query, category)
                    posts.extend(rsshub_posts)

                await asyncio.sleep(1.5)  # Rate limiting between queries

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

            # Confidence scales with volume and source diversity
            sources = set(p.source_method for p in posts)
            confidence = min(0.8, 0.15 + volume * 0.02 + len(sources) * 0.10)

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
                    "social_positive_ratio": round(
                        sum(1 for s in sentiments if s > 0) / len(sentiments), 3
                    ),
                    "source_diversity": len(sources),
                },
                raw_data={
                    "post_count": volume,
                    "top_posts": [
                        p.text[:200] for p in
                        sorted(posts, key=lambda p: p.engagement, reverse=True)[:5]
                    ],
                    "sources_used": list(sources),
                    "queries": queries[:3],
                },
            ))

        self._stats["total_signals"] += len(signals)
        return signals

    # ── Method 1: Bluesky Public API ──────────────────────────────────

    async def _search_bluesky(self, query: str, category: str) -> list[SocialPost]:
        """Search Bluesky's public API (no auth needed)."""
        if not self._client:
            return []

        posts: list[SocialPost] = []
        try:
            resp = await self._client.get(
                BLUESKY_SEARCH_URL,
                params={"q": query, "limit": 25, "sort": "latest"},
                timeout=10.0,
            )
            if resp.status_code != 200:
                return []

            data = resp.json()
            for item in data.get("posts", [])[:20]:
                record = item.get("record", {})
                text = record.get("text", "")
                if len(text) < 10:
                    continue

                # Engagement: likes + reposts
                like_count = item.get("likeCount", 0)
                repost_count = item.get("repostCount", 0)
                engagement = min(1.0, (like_count + repost_count * 2) / 500)

                sentiment = self._score_text(text)

                posts.append(SocialPost(
                    text=text[:500],
                    author=item.get("author", {}).get("handle", ""),
                    likes=like_count,
                    reposts=repost_count,
                    timestamp=time.time(),
                    category=category,
                    sentiment=sentiment,
                    engagement=engagement,
                    source_method="bluesky",
                ))

            self._stats["bluesky_ok"] += 1
            self._stats["posts_parsed"] += len(posts)

        except Exception as e:
            self._stats["errors"] += 1
            log.debug("bluesky_search_error", query=query, error=str(e))

        return posts

    # ── Method 2: Google News RSS ─────────────────────────────────────

    async def _search_google_news(self, query: str, category: str) -> list[SocialPost]:
        """Search Google News via RSS (always works, no auth)."""
        if not self._client:
            return []

        posts: list[SocialPost] = []
        try:
            url = GOOGLE_NEWS_RSS.format(query=query.replace(" ", "+"))
            resp = await self._client.get(url, timeout=10.0)
            if resp.status_code != 200:
                return []

            root = ET.fromstring(resp.text)
            channel = root.find("channel")
            if channel is None:
                return []

            for item in list(channel.findall("item"))[:15]:
                title = item.findtext("title", "")
                desc = item.findtext("description", "")
                source = item.findtext("source", "")
                text = f"{title}. {desc}".strip()

                if len(text) < 10:
                    continue

                sentiment = self._score_text(text)

                # News sources get baseline engagement
                engagement = 0.3 if source else 0.1

                posts.append(SocialPost(
                    text=text[:500],
                    author=source,
                    timestamp=time.time(),
                    category=category,
                    sentiment=sentiment,
                    engagement=engagement,
                    source_method="google_news",
                ))

            self._stats["google_ok"] += 1
            self._stats["posts_parsed"] += len(posts)

        except Exception as e:
            self._stats["errors"] += 1
            log.debug("google_news_error", query=query, error=str(e))

        return posts

    # ── Method 3: RSSHub Twitter Bridge ───────────────────────────────

    async def _search_rsshub(self, query: str, category: str) -> list[SocialPost]:
        """Search Twitter/X via RSSHub bridge (best effort)."""
        if not self._client or not self._working_rsshub:
            return []

        posts: list[SocialPost] = []
        try:
            url = f"{self._working_rsshub}/twitter/search/{query.replace(' ', '%20')}"
            resp = await self._client.get(url, timeout=12.0)

            if resp.status_code != 200:
                # Instance might be down, try to find another
                await self._find_working_rsshub()
                return []

            # Parse RSS/Atom feed
            root = ET.fromstring(resp.text)

            # Handle both RSS and Atom
            items = root.findall(".//item") or root.findall(
                ".//{http://www.w3.org/2005/Atom}entry"
            )

            for item in items[:15]:
                title = (
                    item.findtext("title", "")
                    or item.findtext("{http://www.w3.org/2005/Atom}title", "")
                )
                desc = (
                    item.findtext("description", "")
                    or item.findtext("{http://www.w3.org/2005/Atom}content", "")
                )
                text = re.sub(r"<[^>]+>", "", f"{title} {desc}").strip()

                if len(text) < 10:
                    continue

                sentiment = self._score_text(text)

                posts.append(SocialPost(
                    text=text[:500],
                    timestamp=time.time(),
                    category=category,
                    sentiment=sentiment,
                    engagement=0.2,
                    source_method="rsshub",
                ))

            self._stats["rsshub_ok"] += 1
            self._stats["posts_parsed"] += len(posts)

        except Exception as e:
            self._stats["errors"] += 1
            log.debug("rsshub_error", query=query, error=str(e))

        return posts

    # ── Sentiment Scoring ─────────────────────────────────────────────

    # Inline word sets (avoid circular import with news_sentiment)
    _POSITIVE = frozenset({
        "win", "winning", "victory", "surge", "rally", "bullish", "strong",
        "gain", "profit", "record", "high", "up", "beat", "success",
        "breakthrough", "boost", "soar", "rise", "growth", "improve",
        "positive", "optimistic", "outperform", "dominate", "lead",
        "crush", "blowout", "shutout", "ace", "clutch", "comeback",
        "hot", "streak", "unstoppable", "momentum", "favored", "lock",
    })
    _NEGATIVE = frozenset({
        "loss", "lose", "losing", "crash", "plunge", "bearish", "weak",
        "drop", "fall", "decline", "low", "down", "fail", "miss",
        "collapse", "risk", "threat", "crisis", "struggle", "concern",
        "negative", "pessimistic", "underperform", "upset", "injury",
        "injured", "suspend", "banned", "fine", "penalty", "fired",
        "eliminated", "choke", "bust", "cold", "slump",
    })

    @classmethod
    def _score_text(cls, text: str) -> float:
        """Keyword-based sentiment scoring."""
        words = set(re.findall(r"\b\w+\b", text.lower()))
        pos = len(words & cls._POSITIVE)
        neg = len(words & cls._NEGATIVE)
        total = pos + neg
        if total == 0:
            return 0.0
        return (pos - neg) / total

    # ── Dashboard helpers ─────────────────────────────────────────────

    def get_category_sentiment(self) -> dict[str, dict]:
        """Current sentiment by category for the dashboard."""
        return {
            cat: {
                "sentiment": round(self._category_sentiment.get(cat, 0.0), 4),
                "volume": self._category_volume.get(cat, 0),
            }
            for cat in CATEGORY_QUERIES
        }

    def health(self) -> SourceHealth:
        return SourceHealth(
            name=self.name,
            source_type=self.source_type,
            enabled=self._enabled,
            healthy=self._stats["fetches"] > 0 and self._stats["errors"] < self._stats["fetches"],
            total_fetches=self._stats["fetches"],
            total_errors=self._stats["errors"],
            total_signals=self._stats["total_signals"],
        )


# ── Backward compatibility alias ──────────────────────────────────────────────
# The old module exported SocialSignalSource; keep it so any stale imports work.
SocialSignalSource = TwitterLiveSource
