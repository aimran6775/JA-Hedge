"""
JA Hedge — The Odds API Client (Phase S2).

Async client for The Odds API v4:
  - Fetches live odds from 10+ US bookmakers (DraftKings, FanDuel, BetMGM…)
  - Fetches live scores / game state
  - Computes consensus (median) line across all books
  - Caches results to respect rate limits (500 req/mo free tier)

Docs: https://the-odds-api.com/liveapi/guides/v4/
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.logging_config import get_logger

log = get_logger("sports.odds_client")

BASE_URL = "https://api.the-odds-api.com/v4"


@dataclass
class BookmakerOdds:
    """Odds from a single bookmaker for one game."""
    bookmaker: str          # "draftkings", "fanduel", etc.
    h2h_home: float = 0.0  # moneyline implied prob for home team
    h2h_away: float = 0.0  # moneyline implied prob for away team
    h2h_draw: float = 0.0  # draw implied prob (soccer)
    spread_home: float = 0.0
    spread_away: float = 0.0
    spread_point: float = 0.0  # the spread line (e.g., -6.5)
    total_over: float = 0.0
    total_under: float = 0.0
    total_point: float = 0.0   # the total line (e.g., 220.5)
    last_update: str = ""


@dataclass
class GameOdds:
    """Aggregated odds for a single game across all bookmakers."""
    game_id: str
    sport_key: str          # "basketball_nba"
    sport_title: str        # "NBA"
    commence_time: str      # ISO 8601
    home_team: str
    away_team: str
    bookmakers: list[BookmakerOdds] = field(default_factory=list)
    
    # Computed consensus
    consensus_home_prob: float = 0.0
    consensus_away_prob: float = 0.0
    consensus_draw_prob: float = 0.0
    consensus_spread: float = 0.0
    consensus_total: float = 0.0
    
    # Cache metadata
    fetched_at: float = 0.0
    
    def compute_consensus(self) -> None:
        """Compute median consensus across all bookmakers."""
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


def _american_to_prob(american: int) -> float:
    """Convert American odds to implied probability."""
    if american > 0:
        return 100.0 / (american + 100.0)
    elif american < 0:
        return abs(american) / (abs(american) + 100.0)
    return 0.5


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


class OddsClient:
    """
    Async client for The Odds API v4.
    
    Free tier: 500 requests/month
    Strategy: cache aggressively, only fetch when needed
    """
    
    def __init__(self, api_key: str = "", cache_ttl: float = 300.0):
        self._api_key = api_key
        self._client: httpx.AsyncClient | None = None
        self.cache = OddsCache(ttl_seconds=cache_ttl)
        self._requests_used = 0
        self._requests_remaining = 500
        self._last_fetch: dict[str, float] = {}  # sport_key -> timestamp
        self._min_fetch_interval = 120.0  # minimum 2 minutes between fetches per sport
    
    async def start(self) -> None:
        """Initialize HTTP client."""
        if not self._api_key:
            log.warning("odds_client_no_api_key", hint="Set THE_ODDS_API_KEY in .env for Vegas odds")
            return
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=15.0,
            headers={"Accept": "application/json"},
        )
        log.info("odds_client_started")
    
    async def stop(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
    
    @property
    def is_available(self) -> bool:
        return bool(self._api_key) and self._client is not None
    
    async def fetch_odds(
        self,
        sport_key: str,
        *,
        regions: str = "us",
        markets: str = "h2h,spreads,totals",
        force: bool = False,
    ) -> list[GameOdds]:
        """
        Fetch odds for a sport from The Odds API.
        
        Rate-limited: skips if fetched recently.
        """
        if not self.is_available:
            return self.cache.get_all_odds()
        
        # Rate limit per sport
        last = self._last_fetch.get(sport_key, 0)
        if not force and (time.time() - last) < self._min_fetch_interval:
            return self.cache.get_all_odds()
        
        try:
            resp = await self._client.get(
                f"/sports/{sport_key}/odds",
                params={
                    "apiKey": self._api_key,
                    "regions": regions,
                    "markets": markets,
                    "oddsFormat": "american",
                },
            )
            
            # Track rate limits from headers
            self._requests_remaining = int(resp.headers.get("x-requests-remaining", 500))
            self._requests_used = int(resp.headers.get("x-requests-used", 0))
            
            if resp.status_code != 200:
                log.warning("odds_fetch_failed", sport=sport_key, status=resp.status_code)
                return self.cache.get_all_odds()
            
            self._last_fetch[sport_key] = time.time()
            
            data = resp.json()
            games = self._parse_odds_response(data, sport_key)
            
            for game in games:
                game.compute_consensus()
                self.cache.put_odds(game.game_id, game)
            
            log.info(
                "odds_fetched",
                sport=sport_key,
                games=len(games),
                remaining=self._requests_remaining,
            )
            return games
            
        except Exception as e:
            log.error("odds_fetch_error", sport=sport_key, error=str(e))
            return self.cache.get_all_odds()
    
    async def fetch_scores(
        self,
        sport_key: str,
        *,
        days_from: int = 1,
    ) -> list[GameScore]:
        """Fetch live scores for a sport."""
        if not self.is_available:
            return []
        
        try:
            resp = await self._client.get(
                f"/sports/{sport_key}/scores",
                params={
                    "apiKey": self._api_key,
                    "daysFrom": days_from,
                },
            )
            
            self._requests_remaining = int(resp.headers.get("x-requests-remaining", 500))
            
            if resp.status_code != 200:
                return []
            
            data = resp.json()
            scores = []
            
            for game in data:
                score = GameScore(
                    game_id=game.get("id", ""),
                    sport_key=sport_key,
                    sport_title=game.get("sport_title", ""),
                    commence_time=game.get("commence_time", ""),
                    home_team=game.get("home_team", ""),
                    away_team=game.get("away_team", ""),
                    is_completed=game.get("completed", False),
                    last_update=game.get("last_update", ""),
                )
                
                # Parse scores
                for s in game.get("scores", []) or []:
                    if s.get("name") == score.home_team:
                        score.home_score = int(s.get("score", 0)) if s.get("score") is not None else None
                    elif s.get("name") == score.away_team:
                        score.away_score = int(s.get("score", 0)) if s.get("score") is not None else None
                
                scores.append(score)
                self.cache.put_score(score.game_id, score)
            
            log.info("scores_fetched", sport=sport_key, games=len(scores))
            return scores
            
        except Exception as e:
            log.error("scores_fetch_error", sport=sport_key, error=str(e))
            return []
    
    def _parse_odds_response(self, data: list[dict], sport_key: str) -> list[GameOdds]:
        """Parse The Odds API response into GameOdds objects."""
        games = []
        
        for event in data:
            game = GameOdds(
                game_id=event.get("id", ""),
                sport_key=sport_key,
                sport_title=event.get("sport_title", ""),
                commence_time=event.get("commence_time", ""),
                home_team=event.get("home_team", ""),
                away_team=event.get("away_team", ""),
            )
            
            for bm in event.get("bookmakers", []):
                book = BookmakerOdds(
                    bookmaker=bm.get("key", ""),
                    last_update=bm.get("last_update", ""),
                )
                
                for market in bm.get("markets", []):
                    mkey = market.get("key", "")
                    outcomes = market.get("outcomes", [])
                    
                    if mkey == "h2h":
                        for oc in outcomes:
                            name = oc.get("name", "")
                            price = oc.get("price", 0)
                            prob = _american_to_prob(price)
                            if name == game.home_team:
                                book.h2h_home = prob
                            elif name == game.away_team:
                                book.h2h_away = prob
                            elif name.lower() == "draw":
                                book.h2h_draw = prob
                    
                    elif mkey == "spreads":
                        for oc in outcomes:
                            name = oc.get("name", "")
                            price = oc.get("price", 0)
                            point = oc.get("point", 0)
                            prob = _american_to_prob(price)
                            if name == game.home_team:
                                book.spread_home = prob
                                book.spread_point = point
                            elif name == game.away_team:
                                book.spread_away = prob
                    
                    elif mkey == "totals":
                        for oc in outcomes:
                            name = oc.get("name", "").lower()
                            price = oc.get("price", 0)
                            point = oc.get("point", 0)
                            prob = _american_to_prob(price)
                            if name == "over":
                                book.total_over = prob
                                book.total_point = point
                            elif name == "under":
                                book.total_under = prob
                
                game.bookmakers.append(book)
            
            games.append(game)
        
        return games
    
    def find_game_odds(self, home_team: str, away_team: str) -> GameOdds | None:
        """
        Find cached odds for a game by team names.
        Uses fuzzy matching (case-insensitive, partial).
        """
        home_lower = home_team.lower().strip()
        away_lower = away_team.lower().strip()
        
        for odds in self.cache.get_all_odds():
            oh = odds.home_team.lower()
            oa = odds.away_team.lower()
            
            # Exact match
            if home_lower == oh and away_lower == oa:
                return odds
            
            # Partial match (team name contains search term)
            if (home_lower in oh or oh in home_lower) and \
               (away_lower in oa or oa in away_lower):
                return odds
        
        return None
    
    def stats(self) -> dict[str, Any]:
        return {
            "available": self.is_available,
            "requests_used": self._requests_used,
            "requests_remaining": self._requests_remaining,
            "cache": self.cache.stats(),
            "sports_tracked": list(self._last_fetch.keys()),
        }
