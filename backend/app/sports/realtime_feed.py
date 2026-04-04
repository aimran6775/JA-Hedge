"""
JA Hedge — Realtime Feed Client (replaces The Odds API).

Drop-in replacement for OddsClient that aggregates free data sources:
  - ESPN public scoreboard API (via intelligence hub's SportsOddsScraper)
  - Twitter/X social signals (via intelligence hub's TwitterLiveSource)
  - Sports RSS feeds (via intelligence hub's SportsRSSSource)
  - Reddit social sentiment (via intelligence hub)

Same interface as OddsClient so existing code (SportsFeatureEngine,
SportsDataCollector, scanner, routes) works without changes.

Key difference: this is a PASSIVE aggregator.  The intelligence hub
polls each source independently; RealtimeFeedClient just reads the
latest cached signals and converts them to GameOdds objects.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.logging_config import get_logger

log = get_logger("sports.realtime_feed")


# ── Data classes (same as old odds_client.py) ─────────────────────────────────

@dataclass
class BookmakerOdds:
    """Odds from a single source for one game."""
    bookmaker: str          # "espn_bet", "caesars", "twitter_consensus", etc.
    h2h_home: float = 0.0  # implied prob for home team
    h2h_away: float = 0.0  # implied prob for away team
    h2h_draw: float = 0.0  # draw implied prob (soccer)
    spread_home: float = 0.0
    spread_away: float = 0.0
    spread_point: float = 0.0
    total_over: float = 0.0
    total_under: float = 0.0
    total_point: float = 0.0
    last_update: str = ""


@dataclass
class GameOdds:
    """Aggregated odds for a single game across all sources."""
    game_id: str
    sport_key: str
    sport_title: str
    commence_time: str
    home_team: str
    away_team: str
    bookmakers: list[BookmakerOdds] = field(default_factory=list)

    # Computed consensus
    consensus_home_prob: float = 0.0
    consensus_away_prob: float = 0.0
    consensus_draw_prob: float = 0.0
    consensus_spread: float = 0.0
    consensus_total: float = 0.0

    # Source metadata
    fetched_at: float = 0.0
    source_count: int = 0          # how many sources contributed
    social_sentiment: float = 0.0  # social media sentiment (-1 to +1)
    news_sentiment: float = 0.0    # news RSS sentiment (-1 to +1)

    def compute_consensus(self) -> None:
        """Compute median consensus across all sources."""
        if not self.bookmakers:
            return

        home_probs = [b.h2h_home for b in self.bookmakers if b.h2h_home > 0]
        away_probs = [b.h2h_away for b in self.bookmakers if b.h2h_away > 0]
        draw_probs = [b.h2h_draw for b in self.bookmakers if b.h2h_draw > 0]
        spreads = [b.spread_point for b in self.bookmakers if b.spread_point != 0]
        totals = [b.total_point for b in self.bookmakers if b.total_point > 0]

        if home_probs:
            sorted_h = sorted(home_probs)
            self.consensus_home_prob = sorted_h[len(sorted_h) // 2]
        if away_probs:
            sorted_a = sorted(away_probs)
            self.consensus_away_prob = sorted_a[len(sorted_a) // 2]
        if draw_probs:
            sorted_d = sorted(draw_probs)
            self.consensus_draw_prob = sorted_d[len(sorted_d) // 2]
        if spreads:
            sorted_s = sorted(spreads)
            self.consensus_spread = sorted_s[len(sorted_s) // 2]
        if totals:
            sorted_t = sorted(totals)
            self.consensus_total = sorted_t[len(sorted_t) // 2]

        self.source_count = len(home_probs)


@dataclass
class GameScore:
    """Live score data for a game."""
    game_id: str
    sport_key: str
    sport_title: str
    commence_time: str
    home_team: str
    away_team: str
    home_score: int | None = None
    away_score: int | None = None
    is_completed: bool = False
    last_update: str = ""


class OddsCache:
    """In-memory cache of odds + scores with TTL."""

    def __init__(self, ttl_seconds: float = 300.0):
        self._odds: dict[str, GameOdds] = {}
        self._scores: dict[str, GameScore] = {}
        self._ttl = ttl_seconds

    def put_odds(self, game_id: str, odds: GameOdds) -> None:
        odds.fetched_at = time.time()
        self._odds[game_id] = odds

    def get_odds(self, game_id: str) -> GameOdds | None:
        cached = self._odds.get(game_id)
        if cached and (time.time() - cached.fetched_at) < self._ttl:
            return cached
        return None

    def get_all_odds(self) -> list[GameOdds]:
        now = time.time()
        return [o for o in self._odds.values() if (now - o.fetched_at) < self._ttl]

    def put_score(self, game_id: str, score: GameScore) -> None:
        self._scores[game_id] = score

    def get_score(self, game_id: str) -> GameScore | None:
        return self._scores.get(game_id)

    def get_all_scores(self) -> list[GameScore]:
        return list(self._scores.values())

    def clear(self) -> None:
        self._odds.clear()
        self._scores.clear()

    def stats(self) -> dict[str, Any]:
        return {
            "cached_odds": len(self._odds),
            "cached_scores": len(self._scores),
            "ttl_seconds": self._ttl,
        }


# ── ESPN direct score fetcher (no API key needed) ────────────────────────────

ESPN_SCORE_URLS = {
    "basketball_nba": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
    "football_nfl": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
    "baseball_mlb": "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard",
    "hockey_nhl": "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard",
    "basketball_ncaab": "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard",
}

# Mapping from Odds API sport keys to ESPN sport keys
SPORT_KEY_MAP = {
    "basketball_nba": "basketball_nba",
    "americanfootball_nfl": "football_nfl",
    "baseball_mlb": "baseball_mlb",
    "icehockey_nhl": "hockey_nhl",
    "basketball_ncaab": "basketball_ncaab",
    "football_nfl": "football_nfl",
    "hockey_nhl": "hockey_nhl",
}


class RealtimeFeedClient:
    """
    Realtime data aggregator — drop-in replacement for OddsClient.

    Instead of calling The Odds API (paid, quota-limited), this client:
      1. Reads ESPN odds from the intelligence hub (SportsOddsScraper)
      2. Reads social sentiment from Twitter/Reddit sources
      3. Reads sports news from RSS sources
      4. Fetches live scores directly from ESPN (free, no key)
      5. Computes a multi-source consensus probability

    Provides the same interface as OddsClient so existing code works
    unchanged (SportsFeatureEngine, SportsDataCollector, etc.).
    """

    def __init__(self, cache_ttl: float = 300.0):
        self._client: httpx.AsyncClient | None = None
        self._hub = None  # DataSourceHub, set after intelligence init
        self.cache = OddsCache(ttl_seconds=cache_ttl)
        self._last_fetch: dict[str, float] = {}
        self._refresh_interval = 30.0  # seconds between hub reads
        self._refresh_task: asyncio.Task | None = None

        # Compatibility fields (collector.py reads these)
        self._requests_remaining = 999999  # unlimited (free sources)
        self._requests_used = 0

        # Stats
        self._stats = {
            "hub_reads": 0,
            "espn_score_fetches": 0,
            "games_cached": 0,
            "consensus_computed": 0,
            "social_signals_used": 0,
            "rss_signals_used": 0,
        }

    async def start(self) -> None:
        """Initialize HTTP client and start background refresh."""
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/125.0.0.0 Safari/537.36",
                "Accept": "application/json",
            },
            follow_redirects=True,
        )
        # Start background task that reads from intelligence hub
        self._refresh_task = asyncio.create_task(
            self._refresh_loop(), name="realtime_feed_refresh"
        )
        log.info("realtime_feed_started", sources=["espn", "twitter", "rss", "reddit"])

    async def stop(self) -> None:
        """Shut down."""
        if self._refresh_task and not self._refresh_task.done():
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass
        if self._client:
            await self._client.aclose()
            self._client = None
        log.info("realtime_feed_stopped")

    def set_hub(self, hub) -> None:
        """Inject intelligence hub reference (called from main.py after hub init)."""
        self._hub = hub
        log.info("realtime_feed_hub_connected")

    @property
    def is_available(self) -> bool:
        """True if we have any data sources feeding us."""
        return self._hub is not None or self.cache.stats()["cached_odds"] > 0

    @property
    def rate_budget_ok(self) -> bool:
        """Always True — free sources have no rate budget."""
        return True

    # ── Background refresh loop ───────────────────────────────────────

    async def _refresh_loop(self) -> None:
        """Periodically read from intelligence hub and update cache."""
        try:
            while True:
                try:
                    self._sync_from_hub()
                except Exception as e:
                    log.debug("hub_sync_error", error=str(e))
                await asyncio.sleep(self._refresh_interval)
        except asyncio.CancelledError:
            return

    def _sync_from_hub(self) -> None:
        """Read latest signals from intelligence hub → update GameOdds cache."""
        if not self._hub:
            return

        self._stats["hub_reads"] += 1
        all_signals = self._hub.get_all_signals()

        # ── 1. ESPN odds signals ──────────────────────────────────
        espn_signals = all_signals.get("sports_odds_scraper", {})
        for ticker, sig in espn_signals.items():
            raw = sig.raw_data or {}
            feat = sig.features or {}

            home_team = raw.get("home_team", "")
            away_team = raw.get("away_team", "")
            sport = raw.get("sport", sig.category or "")

            if not home_team or not away_team:
                continue

            game_id = self._make_game_id(home_team, away_team, sport)
            existing = self.cache.get_odds(game_id)

            if existing is None:
                existing = GameOdds(
                    game_id=game_id,
                    sport_key=sport,
                    sport_title=sport.replace("_", " ").title(),
                    commence_time="",
                    home_team=home_team,
                    away_team=away_team,
                )

            # Add ESPN bookmaker data
            home_prob = feat.get("vegas_home_prob", 0)
            away_prob = feat.get("vegas_away_prob", 0)
            num_books = feat.get("num_books", 0)

            if home_prob > 0:
                # Get individual source names if available
                sources = raw.get("sources", [])
                # Clear old ESPN entries and re-add
                existing.bookmakers = [
                    b for b in existing.bookmakers
                    if b.bookmaker not in ("espn", "caesars", "espn_bet", "betmgm")
                ]
                for source_name in (sources or ["espn"]):
                    existing.bookmakers.append(BookmakerOdds(
                        bookmaker=source_name,
                        h2h_home=home_prob,
                        h2h_away=away_prob,
                        last_update=str(int(sig.timestamp)),
                    ))

            # ── 2. Social sentiment enrichment ────────────────────
            social_sig = self._find_social_signal(home_team, away_team, all_signals)
            if social_sig is not None:
                existing.social_sentiment = social_sig
                self._stats["social_signals_used"] += 1

            # ── 3. News/RSS sentiment enrichment ──────────────────
            news_sig = self._find_news_signal(home_team, away_team, all_signals)
            if news_sig is not None:
                existing.news_sentiment = news_sig
                self._stats["rss_signals_used"] += 1

            # Compute consensus and cache
            existing.compute_consensus()
            self.cache.put_odds(game_id, existing)
            self._stats["consensus_computed"] += 1

        self._stats["games_cached"] = self.cache.stats()["cached_odds"]

    def _find_social_signal(
        self, home: str, away: str, all_signals: dict
    ) -> float | None:
        """Find social sentiment signal matching this game from Twitter/Reddit."""
        home_lower = home.lower()
        away_lower = away.lower()

        for source_name in ("twitter_live", "social_twitter", "social_reddit"):
            signals = all_signals.get(source_name, {})
            for ticker, sig in signals.items():
                # Category-level sports match
                if sig.category == "sports" and sig.signal_value != 0:
                    # Check if any team name appears in the headline or raw text
                    text = (sig.headline or "").lower()
                    raw_posts = sig.raw_data.get("top_posts", [])
                    all_text = text + " " + " ".join(
                        str(p).lower() for p in raw_posts[:5]
                    )
                    if (
                        any(w in all_text for w in home_lower.split()[-1:])
                        or any(w in all_text for w in away_lower.split()[-1:])
                    ):
                        return sig.signal_value

        return None

    def _find_news_signal(
        self, home: str, away: str, all_signals: dict
    ) -> float | None:
        """Find news/RSS sentiment matching this game."""
        home_lower = home.lower()
        away_lower = away.lower()

        for source_name in ("sports_rss", "news_sentiment"):
            signals = all_signals.get(source_name, {})
            for ticker, sig in signals.items():
                text = (sig.headline or "").lower()
                if (
                    any(w in text for w in home_lower.split()[-1:])
                    or any(w in text for w in away_lower.split()[-1:])
                ):
                    return sig.signal_value

        return None

    @staticmethod
    def _make_game_id(home: str, away: str, sport: str) -> str:
        """Consistent game ID from team names."""
        h = re.sub(r"[^a-z]", "", home.lower())
        a = re.sub(r"[^a-z]", "", away.lower())
        return f"{sport}:{a}@{h}"

    # ── Public API (same interface as OddsClient) ─────────────────────

    async def fetch_odds(
        self,
        sport_key: str,
        *,
        regions: str = "us",
        markets: str = "h2h,spreads,totals",
        force: bool = False,
    ) -> list[GameOdds]:
        """
        Return cached odds for a sport.

        Unlike OddsClient, this doesn't make API calls — it reads from
        the intelligence hub cache which is updated by background polling.
        """
        self._sync_from_hub()  # Force a fresh read
        self._last_fetch[sport_key] = time.time()

        # Map sport key and filter
        espn_key = SPORT_KEY_MAP.get(sport_key, sport_key)
        return [
            o for o in self.cache.get_all_odds()
            if o.sport_key == espn_key or o.sport_key == sport_key
        ]

    async def fetch_scores(
        self,
        sport_key: str,
        *,
        days_from: int = 1,
    ) -> list[GameScore]:
        """Fetch live scores directly from ESPN (free, no key needed)."""
        if not self._client:
            return []

        espn_key = SPORT_KEY_MAP.get(sport_key, sport_key)
        url = ESPN_SCORE_URLS.get(espn_key)
        if not url:
            return []

        try:
            resp = await self._client.get(url)
            self._stats["espn_score_fetches"] += 1

            if resp.status_code != 200:
                return []

            data = resp.json()
            scores = []

            for event in data.get("events", []):
                comps = event.get("competitions", [])
                if not comps:
                    continue
                comp = comps[0]
                competitors = comp.get("competitors", [])
                if len(competitors) < 2:
                    continue

                home_team = away_team = ""
                home_score = away_score = None
                for c in competitors:
                    team = c.get("team", {})
                    name = team.get("displayName", team.get("name", ""))
                    score_val = c.get("score")
                    if c.get("homeAway") == "home":
                        home_team = name
                        home_score = int(score_val) if score_val is not None else None
                    else:
                        away_team = name
                        away_score = int(score_val) if score_val is not None else None

                status = comp.get("status", {})
                is_completed = status.get("type", {}).get("completed", False)

                score = GameScore(
                    game_id=event.get("id", ""),
                    sport_key=espn_key,
                    sport_title=event.get("shortName", sport_key),
                    commence_time=event.get("date", ""),
                    home_team=home_team,
                    away_team=away_team,
                    home_score=home_score,
                    away_score=away_score,
                    is_completed=is_completed,
                    last_update=status.get("displayClock", ""),
                )
                scores.append(score)
                self.cache.put_score(score.game_id, score)

            return scores

        except Exception as e:
            log.debug("espn_score_fetch_error", sport=sport_key, error=str(e))
            return []

    def find_game_odds(self, home_team: str, away_team: str) -> GameOdds | None:
        """
        Find cached odds for a game by team names.
        Uses fuzzy matching (case-insensitive, partial).
        """
        home_lower = home_team.lower().strip()
        away_lower = away_team.lower().strip()

        if len(home_lower) < 2 and len(away_lower) < 2:
            return None

        best: GameOdds | None = None
        best_score = 0

        for odds in self.cache.get_all_odds():
            oh = odds.home_team.lower()
            oa = odds.away_team.lower()
            score = 0

            # Exact match
            if home_lower and away_lower and home_lower == oh and away_lower == oa:
                return odds

            # Both teams — partial match
            if home_lower and away_lower:
                home_match = (len(home_lower) >= 3 and home_lower in oh) or (len(oh) >= 3 and oh in home_lower)
                away_match = (len(away_lower) >= 3 and away_lower in oa) or (len(oa) >= 3 and oa in away_lower)
                if home_match and away_match:
                    score = 10
            elif home_lower and len(home_lower) >= 4:
                if home_lower in oh or oh in home_lower:
                    score = 5
            elif away_lower and len(away_lower) >= 4:
                if away_lower in oa or oa in away_lower:
                    score = 5

            if score > best_score:
                best_score = score
                best = odds

        return best

    def find_game_odds_by_event(self, event_ticker: str) -> GameOdds | None:
        """Find cached odds by parsing team codes from Kalshi event_ticker."""
        if not event_ticker:
            return None

        ticker_upper = event_ticker.upper()
        m = re.search(r'\d{1,2}[A-Z]{3}\d{1,2}([A-Z]{2,4})([A-Z]{2,4})$', ticker_upper)
        if not m:
            return None

        code1 = m.group(1).lower()
        code2 = m.group(2).lower()

        if len(code1) < 2 or len(code2) < 2:
            return None

        for odds in self.cache.get_all_odds():
            oh = odds.home_team.lower()
            oa = odds.away_team.lower()
            c1_in = code1 in oh or code1 in oa
            c2_in = code2 in oh or code2 in oa
            if c1_in and c2_in:
                return odds

        return None

    def stats(self) -> dict[str, Any]:
        """Stats compatible with the old OddsClient interface."""
        return {
            "available": self.is_available,
            "source": "realtime_feed",
            "method": "free_multi_source",
            "requests_used": self._stats["hub_reads"],
            "requests_remaining": 999999,  # unlimited
            "hub_connected": self._hub is not None,
            "cache": self.cache.stats(),
            "sources_active": {
                "espn": True,
                "twitter": bool(self._hub and "twitter_live" in (self._hub._sources if self._hub else {})),
                "sports_rss": bool(self._hub and "sports_rss" in (self._hub._sources if self._hub else {})),
                "reddit": bool(self._hub and "social_reddit" in (self._hub._sources if self._hub else {})),
            },
            "stats": dict(self._stats),
        }
