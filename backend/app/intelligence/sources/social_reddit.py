"""
Phase 23 — Reddit Social Signals (replaces dead Nitter/Twitter).

Monitors public Reddit via RSS/Atom feeds — no API key needed.
Reddit Atom feeds (r/{sub}/.rss) are the most reliable public access method.

Subreddits tracked per Kalshi category:
  crypto   : bitcoin, cryptocurrency, ethtrader, solana
  economics: wallstreetbets, stocks, investing, economics, finance
  politics : politics, PoliticalDiscussion, news
  sports   : sportsbook, nba, nfl, baseball, hockey
  weather  : weather, TropicalWeather

Extracts: sentiment (keyword-based), volume, engagement per category.
"""

from __future__ import annotations

import asyncio
import re
import time
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from typing import Any

import httpx

from app.intelligence.base import DataSource, DataSourceType, SourceHealth, SourceSignal
from app.logging_config import get_logger

log = get_logger("intelligence.social")

# ── subreddit → category mapping ──────────────────────────────────────
SUBREDDIT_MAP: dict[str, list[str]] = {
    "crypto":    ["bitcoin", "cryptocurrency", "ethtrader", "solana"],
    "economics": ["wallstreetbets", "stocks", "investing", "economics", "finance"],
    "politics":  ["politics", "PoliticalDiscussion", "news"],
    "sports":    ["sportsbook", "nba", "nfl", "baseball", "hockey"],
    "weather":   ["weather", "TropicalWeather"],
}

# ── simple word-list sentiment ────────────────────────────────────────
POSITIVE_WORDS = frozenset({
    "bullish", "surge", "rally", "soar", "boom", "moon", "profit",
    "gain", "up", "high", "record", "breakout", "strong", "buy",
    "win", "victory", "beat", "crush", "dominate", "growth",
    "recovery", "positive", "optimistic", "confident", "upgrade",
    "outperform", "exceed", "surprise", "momentum", "support",
})

NEGATIVE_WORDS = frozenset({
    "bearish", "crash", "dump", "tank", "plunge", "collapse", "loss",
    "drop", "down", "low", "fear", "sell", "panic", "recession",
    "lose", "defeat", "miss", "weak", "decline", "negative",
    "pessimistic", "downgrade", "underperform", "disappoint",
    "risk", "warning", "danger", "crisis", "default", "layoff",
})

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


class SocialSignalSource(DataSource):
    """Social media sentiment via Reddit public Atom/RSS feeds."""

    def __init__(
        self,
        poll_interval: float = 180.0,
        enabled: bool = True,
    ) -> None:
        self._poll_interval = poll_interval
        self._enabled = enabled
        self._client: httpx.AsyncClient | None = None

        self._category_sentiment: dict[str, float] = {}
        self._category_volume: dict[str, int] = Counter()
        self._stats = {
            "fetches": 0, "errors": 0, "posts_parsed": 0,
            "total_signals": 0, "subreddits_ok": 0, "subreddits_failed": 0,
        }

    # ── DataSource interface ──────────────────────────────────────────

    @property
    def name(self) -> str:
        return "social_reddit"

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
            timeout=httpx.Timeout(15.0),
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            },
            follow_redirects=True,
        )
        log.info("social_reddit_started")

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def fetch_signals(self, tickers: list[str] | None = None) -> list[SourceSignal]:
        if not self._client:
            return []

        signals: list[SourceSignal] = []
        self._stats["fetches"] += 1

        for category, subreddits in SUBREDDIT_MAP.items():
            try:
                posts = await self._fetch_category(subreddits, category)
                if not posts:
                    continue

                sentiments = [p["sentiment"] for p in posts]
                engagements = [p["score"] for p in posts]

                avg_sentiment = sum(sentiments) / len(sentiments)
                max_score = max(engagements) if engagements else 0
                volume = len(posts)

                self._category_sentiment[category] = avg_sentiment
                self._category_volume[category] = volume

                confidence = min(0.7, 0.15 + volume * 0.01)

                signals.append(SourceSignal(
                    source_name=self.name,
                    source_type=self.source_type,
                    ticker=f"social:{category}",
                    signal_value=avg_sentiment,
                    confidence=confidence,
                    edge_estimate=avg_sentiment * 0.02,
                    category=category,
                    headline=posts[0]["title"][:120] if posts else "",
                    features={
                        "social_sentiment": round(avg_sentiment, 4),
                        "social_volume": float(volume),
                        "social_max_engagement": float(max_score),
                        "social_sentiment_std": round(
                            (sum((s - avg_sentiment) ** 2 for s in sentiments) / len(sentiments)) ** 0.5, 4
                        ) if len(sentiments) > 1 else 0.0,
                        "social_positive_ratio": round(
                            sum(1 for s in sentiments if s > 0) / max(1, len(sentiments)), 3
                        ),
                    },
                    raw_data={
                        "post_count": volume,
                        "subreddits": subreddits,
                        "top_posts": [p["title"][:200] for p in
                                      sorted(posts, key=lambda p: p["score"], reverse=True)[:3]],
                    },
                ))
            except Exception as e:
                self._stats["errors"] += 1
                log.debug("reddit_category_error", category=category, error=str(e))

        self._stats["total_signals"] += len(signals)
        return signals

    # ── internals ─────────────────────────────────────────────────────

    async def _fetch_category(self, subreddits: list[str], category: str) -> list[dict]:
        """Fetch posts from multiple subreddits for a category."""
        all_posts: list[dict] = []

        for sub in subreddits:
            try:
                posts = await self._fetch_subreddit_rss(sub, category)
                if posts:
                    all_posts.extend(posts)
                    self._stats["subreddits_ok"] += 1
                else:
                    # RSS returned nothing, try JSON fallback
                    posts = await self._fetch_subreddit_json(sub, category)
                    if posts:
                        all_posts.extend(posts)
                        self._stats["subreddits_ok"] += 1
                    else:
                        self._stats["subreddits_failed"] += 1
            except Exception as exc:
                self._stats["subreddits_failed"] += 1
                log.debug("reddit_sub_error", sub=sub, error=str(exc)[:120])

            # Polite delay — Reddit rate-limits aggressive crawling
            await asyncio.sleep(2.0)

        return all_posts

    async def _fetch_subreddit_rss(self, subreddit: str, category: str) -> list[dict]:
        """Primary: Atom/RSS feed (most reliable, not rate-limited as aggressively)."""
        if not self._client:
            return []

        url = f"https://www.reddit.com/r/{subreddit}/.rss"
        resp = await self._client.get(url)

        if resp.status_code != 200:
            log.debug("reddit_rss_fail", sub=subreddit, status=resp.status_code)
            return []

        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError:
            return []

        entries = root.findall("atom:entry", ATOM_NS)
        posts: list[dict] = []
        now = time.time()

        for entry in entries:
            title_el = entry.find("atom:title", ATOM_NS)
            updated_el = entry.find("atom:updated", ATOM_NS)
            content_el = entry.find("atom:content", ATOM_NS)

            title = (title_el.text or "") if title_el is not None else ""
            if not title:
                continue

            # Parse ISO-8601 date
            created_utc = 0.0
            if updated_el is not None and updated_el.text:
                try:
                    dt = datetime.fromisoformat(updated_el.text.replace("Z", "+00:00"))
                    created_utc = dt.timestamp()
                except (ValueError, TypeError):
                    pass

            # Skip very old posts (> 72h)
            if created_utc > 0 and (now - created_utc) > 259200:
                continue

            # Extract text content (strip HTML tags)
            content_text = ""
            if content_el is not None and content_el.text:
                content_text = re.sub(r"<[^>]+>", " ", content_el.text)[:500]

            text = f"{title} {content_text}"
            sentiment = self._score_text(text)

            # RSS doesn't give score/comments, so estimate from position
            # (earlier entries = hotter = higher engagement)
            position_score = max(1, 100 - len(posts) * 4)

            posts.append({
                "title": title,
                "text": text,
                "score": position_score,
                "comments": 0,
                "sentiment": sentiment,
                "created": created_utc,
                "subreddit": subreddit,
                "category": category,
            })
            self._stats["posts_parsed"] += 1

        return posts

    async def _fetch_subreddit_json(self, subreddit: str, category: str) -> list[dict]:
        """Fallback: JSON endpoint (can get 403/429 under load)."""
        if not self._client:
            return []

        url = f"https://www.reddit.com/r/{subreddit}/hot.json"
        params = {"limit": "15", "raw_json": "1"}
        resp = await self._client.get(url, params=params)

        if resp.status_code != 200:
            return []

        ct = resp.headers.get("content-type", "")
        if "json" not in ct:
            return []

        try:
            data = resp.json()
        except Exception:
            return []

        children = data.get("data", {}).get("children", [])
        posts: list[dict] = []
        now = time.time()

        for child in children:
            post_data = child.get("data", {})
            if post_data.get("stickied"):
                continue

            title = post_data.get("title", "")
            selftext = post_data.get("selftext", "")[:500]
            score = post_data.get("score", 0)
            num_comments = post_data.get("num_comments", 0)
            created = post_data.get("created_utc", 0)

            if created > 0 and (now - created) > 259200:
                continue

            text = f"{title} {selftext}"
            sentiment = self._score_text(text)

            posts.append({
                "title": title,
                "text": text,
                "score": score,
                "comments": num_comments,
                "sentiment": sentiment,
                "created": created,
                "subreddit": subreddit,
                "category": category,
            })
            self._stats["posts_parsed"] += 1

        return posts

    @staticmethod
    def _score_text(text: str) -> float:
        """Simple keyword-based sentiment scoring."""
        words = set(re.findall(r"\b\w+\b", text.lower()))
        pos = len(words & POSITIVE_WORDS)
        neg = len(words & NEGATIVE_WORDS)
        total = pos + neg
        if total == 0:
            return 0.0
        return max(-1.0, min(1.0, (pos - neg) / total))

    def get_category_sentiment(self) -> dict[str, dict]:
        """Dashboard data."""
        return {
            cat: {
                "sentiment": round(self._category_sentiment.get(cat, 0.0), 4),
                "volume": self._category_volume.get(cat, 0),
            }
            for cat in SUBREDDIT_MAP
        }

    def health(self) -> SourceHealth:
        return SourceHealth(
            name=self.name,
            source_type=self.source_type,
            enabled=self._enabled,
            healthy=self._stats["subreddits_ok"] > 0 or self._stats["fetches"] == 0,
            total_fetches=self._stats["fetches"],
            total_errors=self._stats["errors"],
            total_signals=self._stats["total_signals"],
        )
