"""
Sports RSS Feed Aggregator — Real-time sports news signals.

Monitors 15+ sports RSS feeds for:
  - Breaking news (injuries, trades, lineup changes)
  - Expert predictions and analysis
  - Score updates and game recaps
  - Betting-angle coverage

All feeds are free, no API keys needed, and very reliable.
This source runs alongside the ESPN SportsOddsScraper and
TwitterLiveSource to provide a third pillar of real-time data.
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

log = get_logger("intelligence.sports_rss")

# ── Sports RSS Feeds ──────────────────────────────────────────────────────────

SPORTS_FEEDS = {
    # General sports
    "espn_top": "https://www.espn.com/espn/rss/news",
    "espn_nba": "https://www.espn.com/espn/rss/nba/news",
    "espn_nfl": "https://www.espn.com/espn/rss/nfl/news",
    "espn_mlb": "https://www.espn.com/espn/rss/mlb/news",
    "espn_nhl": "https://www.espn.com/espn/rss/nhl/news",

    # Yahoo Sports
    "yahoo_sports": "https://sports.yahoo.com/rss/",
    "yahoo_nba": "https://sports.yahoo.com/nba/rss/",
    "yahoo_nfl": "https://sports.yahoo.com/nfl/rss/",

    # CBS Sports
    "cbs_nba": "https://www.cbssports.com/rss/headlines/nba/",
    "cbs_nfl": "https://www.cbssports.com/rss/headlines/nfl/",
    "cbs_mlb": "https://www.cbssports.com/rss/headlines/mlb/",

    # Bleacher Report (via RSS)
    "bleacher_nba": "https://bleacherreport.com/articles/feed?tag_id=19",
    "bleacher_nfl": "https://bleacherreport.com/articles/feed?tag_id=16",

    # BBC Sport
    "bbc_sport": "https://feeds.bbci.co.uk/sport/rss.xml",

    # Injury / transaction feeds
    "rotoworld": "https://www.nbcsports.com/edge/rss/player-news",
}

# Map feed names to sport categories
FEED_SPORT_MAP = {
    "espn_nba": "basketball_nba",
    "espn_nfl": "football_nfl",
    "espn_mlb": "baseball_mlb",
    "espn_nhl": "hockey_nhl",
    "yahoo_nba": "basketball_nba",
    "yahoo_nfl": "football_nfl",
    "cbs_nba": "basketball_nba",
    "cbs_nfl": "football_nfl",
    "cbs_mlb": "baseball_mlb",
    "bleacher_nba": "basketball_nba",
    "bleacher_nfl": "football_nfl",
}

# Keywords that indicate high-impact news (injuries, trades, etc.)
HIGH_IMPACT_KEYWORDS = frozenset({
    "injury", "injured", "out", "doubtful", "questionable", "ruled out",
    "trade", "traded", "waived", "signed", "released", "suspended",
    "starting lineup", "benched", "rest", "load management",
    "upset", "comeback", "blowout", "overtime", "buzzer beater",
    "record", "historic", "milestone", "breaking",
})


@dataclass
class RSSArticle:
    """A parsed RSS article."""
    title: str
    description: str = ""
    link: str = ""
    source_feed: str = ""
    sport: str = ""
    timestamp: float = 0.0
    sentiment: float = 0.0
    impact_score: float = 0.0
    teams_mentioned: list[str] = field(default_factory=list)


class SportsRSSSource(DataSource):
    """
    Sports news aggregator via RSS feeds.

    Polls 15+ sports RSS feeds and produces sentiment signals
    per sport category. High-impact news (injuries, trades)
    gets boosted signal confidence.
    """

    def __init__(
        self,
        poll_interval: float = 90.0,
        enabled: bool = True,
    ) -> None:
        self._poll_interval = poll_interval
        self._enabled = enabled
        self._client: httpx.AsyncClient | None = None

        # State
        self._article_cache: dict[str, RSSArticle] = {}  # link → article (dedup)
        self._sport_sentiment: dict[str, float] = {}
        self._sport_volume: dict[str, int] = Counter()
        self._stats = {
            "fetches": 0, "errors": 0, "articles_parsed": 0,
            "feeds_ok": 0, "feeds_failed": 0,
            "total_signals": 0,
        }

    @property
    def name(self) -> str:
        return "sports_rss"

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
            timeout=httpx.Timeout(15.0),
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/125.0.0.0 Safari/537.36",
                "Accept": "application/rss+xml, application/xml, text/xml, */*",
            },
            follow_redirects=True,
        )
        log.info("sports_rss_started", feeds=len(SPORTS_FEEDS))

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ── Main fetch ────────────────────────────────────────────────────

    async def fetch_signals(self, tickers: list[str] | None = None) -> list[SourceSignal]:
        if not self._client:
            return []

        self._stats["fetches"] += 1

        # Fetch all feeds concurrently (with semaphore to limit)
        sem = asyncio.Semaphore(5)

        async def _fetch_one(name: str, url: str) -> list[RSSArticle]:
            async with sem:
                return await self._fetch_feed(name, url)

        tasks = [_fetch_one(name, url) for name, url in SPORTS_FEEDS.items()]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_articles: list[RSSArticle] = []
        for res in results:
            if isinstance(res, list):
                all_articles.extend(res)
            elif isinstance(res, Exception):
                log.debug("rss_feed_error", error=str(res))

        if not all_articles:
            return []

        # Group by sport category
        sport_articles: dict[str, list[RSSArticle]] = {}
        for article in all_articles:
            sport = article.sport or "general"
            sport_articles.setdefault(sport, []).append(article)

        # Generate signals per sport
        signals: list[SourceSignal] = []

        for sport, articles in sport_articles.items():
            sentiments = [a.sentiment for a in articles]
            impacts = [a.impact_score for a in articles]
            volume = len(articles)

            avg_sentiment = sum(sentiments) / len(sentiments)
            max_impact = max(impacts) if impacts else 0
            high_impact_count = sum(1 for i in impacts if i > 0.5)

            self._sport_sentiment[sport] = avg_sentiment
            self._sport_volume[sport] = volume

            # Confidence boosted by volume and impact
            confidence = min(0.85, 0.20 + volume * 0.03 + high_impact_count * 0.05)

            signals.append(SourceSignal(
                source_name=self.name,
                source_type=self.source_type,
                ticker=f"sports_rss:{sport}",
                signal_value=avg_sentiment,
                confidence=confidence,
                edge_estimate=avg_sentiment * max_impact * 0.03,
                category=sport,
                headline=articles[0].title[:120] if articles else "",
                features={
                    "rss_sentiment": round(avg_sentiment, 4),
                    "rss_volume": volume,
                    "rss_max_impact": round(max_impact, 3),
                    "rss_high_impact_count": high_impact_count,
                    "rss_sentiment_std": round(
                        (sum((s - avg_sentiment) ** 2 for s in sentiments) / max(1, len(sentiments))) ** 0.5, 4
                    ),
                },
                raw_data={
                    "article_count": volume,
                    "top_headlines": [
                        a.title[:200] for a in
                        sorted(articles, key=lambda a: a.impact_score, reverse=True)[:5]
                    ],
                    "teams_mentioned": list(set(
                        t for a in articles for t in a.teams_mentioned
                    ))[:20],
                    "sport": sport,
                },
            ))

        self._stats["total_signals"] += len(signals)
        return signals

    # ── Feed fetching ─────────────────────────────────────────────────

    async def _fetch_feed(self, feed_name: str, url: str) -> list[RSSArticle]:
        """Fetch and parse a single RSS feed."""
        if not self._client:
            return []

        articles: list[RSSArticle] = []
        sport = FEED_SPORT_MAP.get(feed_name, "general")

        try:
            resp = await self._client.get(url, timeout=12.0)
            if resp.status_code != 200:
                self._stats["feeds_failed"] += 1
                return []

            self._stats["feeds_ok"] += 1
            root = ET.fromstring(resp.text)

            # Handle RSS 2.0
            items = root.findall(".//item")
            # Handle Atom
            if not items:
                items = root.findall(".//{http://www.w3.org/2005/Atom}entry")

            for item in items[:20]:
                title = (
                    item.findtext("title", "")
                    or item.findtext("{http://www.w3.org/2005/Atom}title", "")
                ).strip()
                desc = (
                    item.findtext("description", "")
                    or item.findtext("{http://www.w3.org/2005/Atom}summary", "")
                    or item.findtext("{http://www.w3.org/2005/Atom}content", "")
                )
                link = (
                    item.findtext("link", "")
                    or (item.find("{http://www.w3.org/2005/Atom}link") or {}).get("href", "")
                )

                # Strip HTML from description
                desc = re.sub(r"<[^>]+>", "", desc).strip()

                if not title or len(title) < 5:
                    continue

                # Dedup by link
                if link and link in self._article_cache:
                    continue

                text = f"{title}. {desc}"
                sentiment = self._score_article(text)
                impact = self._compute_impact(text)
                teams = self._extract_teams(text)

                article = RSSArticle(
                    title=title,
                    description=desc[:500],
                    link=link,
                    source_feed=feed_name,
                    sport=sport,
                    timestamp=time.time(),
                    sentiment=sentiment,
                    impact_score=impact,
                    teams_mentioned=teams,
                )
                articles.append(article)

                if link:
                    self._article_cache[link] = article

            self._stats["articles_parsed"] += len(articles)

        except ET.ParseError:
            self._stats["feeds_failed"] += 1
            log.debug("rss_parse_error", feed=feed_name)
        except Exception as e:
            self._stats["feeds_failed"] += 1
            log.debug("rss_fetch_error", feed=feed_name, error=str(e))

        # Trim cache (keep last 2000 articles)
        if len(self._article_cache) > 2000:
            sorted_items = sorted(
                self._article_cache.items(),
                key=lambda x: x[1].timestamp,
            )
            self._article_cache = dict(sorted_items[-1500:])

        return articles

    # ── Sentiment & Impact Scoring ────────────────────────────────────

    _POSITIVE = frozenset({
        "win", "winning", "victory", "strong", "dominat", "lead",
        "beat", "crush", "surge", "rally", "comeback", "clutch",
        "breakout", "record", "star", "mvp", "elite", "unstoppable",
        "hot", "streak", "momentum", "confident", "favored",
        "return", "cleared", "healthy", "upgraded", "probable",
    })
    _NEGATIVE = frozenset({
        "loss", "lose", "losing", "injury", "injured", "out",
        "doubtful", "questionable", "ruled", "suspend", "miss",
        "struggle", "slump", "cold", "bust", "choke", "collapse",
        "upset", "underdog", "concern", "risk", "decline",
        "trade", "waive", "release", "fire", "bench", "demote",
        "rest", "load", "management", "downgrade",
    })

    @classmethod
    def _score_article(cls, text: str) -> float:
        """Keyword-based sentiment scoring for sports articles."""
        words = set(re.findall(r"\b\w+\b", text.lower()))
        pos = len(words & cls._POSITIVE)
        neg = len(words & cls._NEGATIVE)
        total = pos + neg
        if total == 0:
            return 0.0
        return (pos - neg) / total

    @staticmethod
    def _compute_impact(text: str) -> float:
        """Score how impactful this news is for betting/prediction."""
        text_lower = text.lower()
        score = 0.0

        for keyword in HIGH_IMPACT_KEYWORDS:
            if keyword in text_lower:
                score += 0.15

        # Cap at 1.0
        return min(1.0, score)

    @staticmethod
    def _extract_teams(text: str) -> list[str]:
        """Extract team names mentioned in text (NBA/NFL/MLB/NHL)."""
        # Common team names / cities
        nba_teams = {
            "lakers", "celtics", "warriors", "nets", "bucks", "76ers",
            "heat", "suns", "nuggets", "mavericks", "cavaliers", "knicks",
            "thunder", "timberwolves", "clippers", "grizzlies", "pacers",
            "hawks", "bulls", "rockets", "pelicans", "kings", "magic",
            "raptors", "pistons", "hornets", "wizards", "jazz", "blazers",
            "spurs",
        }
        nfl_teams = {
            "chiefs", "eagles", "49ers", "cowboys", "bills", "ravens",
            "dolphins", "lions", "packers", "steelers", "bengals", "vikings",
            "chargers", "jaguars", "texans", "broncos", "jets", "saints",
            "seahawks", "giants", "falcons", "rams", "panthers", "bears",
            "buccaneers", "raiders", "colts", "titans", "commanders", "browns",
            "patriots", "cardinals",
        }
        all_teams = nba_teams | nfl_teams

        text_lower = text.lower()
        found = []
        for team in all_teams:
            if team in text_lower:
                found.append(team)

        return found[:10]

    # ── Health ────────────────────────────────────────────────────────

    def health(self) -> SourceHealth:
        return SourceHealth(
            name=self.name,
            source_type=self.source_type,
            enabled=self._enabled,
            healthy=self._stats["feeds_ok"] > 0,
            total_fetches=self._stats["fetches"],
            total_errors=self._stats["feeds_failed"],
            total_signals=self._stats["total_signals"],
        )
