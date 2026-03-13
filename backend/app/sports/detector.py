"""
JA Hedge — Sports Market Detection & Classification (Phase S1).

Parses Kalshi tickers/titles to identify:
  - Sport type (NBA, NFL, MLB, NHL, NCAAB, MLS, Tennis, Soccer, etc.)
  - Market type (spread, total, moneyline / game winner)
  - Game date/time
  - Teams involved
  - Whether a game is live (in-progress)

Ticker anatomy:
  kxnbagame-26mar11cleorl  →  NBA game, Mar 26, 11:00, CLE vs ORL
  kxncaambgame-26mar11misstex → NCAAB March Madness, MISS vs TEX
  kxnhlgame-26mar11mtlott → NHL, MTL vs OTT
  kxatpmatch-26mar10djodra → ATP Tennis, Djokovic vs Draper
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.kalshi.models import Market
from app.logging_config import get_logger

log = get_logger("sports.detector")


# ── Sport Registry ─────────────────────────────────────────────────────────

@dataclass
class SportConfig:
    """Configuration for a recognized sport."""
    sport_id: str           # e.g., "nba"
    sport_name: str         # e.g., "NBA Basketball"
    series_prefixes: list[str]  # Kalshi series_ticker prefixes
    odds_api_keys: list[str]    # The Odds API sport keys
    periods: int = 4        # Game periods (4 quarters, 3 periods, 9 innings...)
    has_clock: bool = True  # Whether periods have a running clock
    has_overtime: bool = True
    avg_game_duration_min: int = 150
    home_advantage: float = 0.03  # Historical home team win% boost
    typical_total: float = 220.0  # Typical over/under line


SPORT_REGISTRY: dict[str, SportConfig] = {
    "nba": SportConfig(
        sport_id="nba",
        sport_name="NBA Basketball",
        series_prefixes=["kxnbagame", "kxnbaplayer", "kxnbafirstbasket",
                        "kxnbapoints", "kxnbarebounds", "kxnbaassists", "kxnba"],
        odds_api_keys=["basketball_nba"],
        periods=4, has_clock=True, has_overtime=True,
        avg_game_duration_min=150,
        home_advantage=0.035,
        typical_total=224.0,
    ),
    "ncaab": SportConfig(
        sport_id="ncaab",
        sport_name="NCAA Basketball",
        series_prefixes=["kxncaambgame", "kxncaamb1h", "kxncaamb",
                        "kxncaabgame", "kxncaab", "kxmarchm"],
        odds_api_keys=["basketball_ncaab"],
        periods=2, has_clock=True, has_overtime=True,
        avg_game_duration_min=130,
        home_advantage=0.04,
        typical_total=145.0,
    ),
    "nfl": SportConfig(
        sport_id="nfl",
        sport_name="NFL Football",
        series_prefixes=["kxnflgame", "kxnflplayer", "kxnfltd",
                        "kxnflpassing", "kxnflrushing", "kxnfl"],
        odds_api_keys=["americanfootball_nfl"],
        periods=4, has_clock=True, has_overtime=True,
        avg_game_duration_min=195,
        home_advantage=0.03,
        typical_total=46.0,
    ),
    "mlb": SportConfig(
        sport_id="mlb",
        sport_name="MLB Baseball",
        series_prefixes=["kxmlbgame", "kxmlbplayer", "kxmlbhr",
                        "kxmlbstrikeout", "kxmlb"],
        odds_api_keys=["baseball_mlb"],
        periods=9, has_clock=False, has_overtime=True,
        avg_game_duration_min=180,
        home_advantage=0.025,
        typical_total=8.5,
    ),
    "nhl": SportConfig(
        sport_id="nhl",
        sport_name="NHL Hockey",
        series_prefixes=["kxnhlgame", "kxnhlfirstgoal", "kxnhlplayer",
                        "kxnhlpoints", "kxnhlgoal", "kxnhl",
                        "kxshlgame", "kxshl"],  # SHL = Swedish Hockey League
        odds_api_keys=["icehockey_nhl"],
        periods=3, has_clock=True, has_overtime=True,
        avg_game_duration_min=150,
        home_advantage=0.03,
        typical_total=6.0,
    ),
    "mls": SportConfig(
        sport_id="mls",
        sport_name="MLS Soccer",
        series_prefixes=["kxmlsgame", "kxmls"],
        odds_api_keys=["soccer_usa_mls"],
        periods=2, has_clock=True, has_overtime=False,
        avg_game_duration_min=105,
        home_advantage=0.04,
        typical_total=2.8,
    ),
    "tennis": SportConfig(
        sport_id="tennis",
        sport_name="ATP Tennis",
        series_prefixes=["kxatpmatch", "kxwtamatch", "kxtennis"],
        odds_api_keys=["tennis_atp_french_open", "tennis_atp_us_open"],
        periods=5, has_clock=False, has_overtime=False,
        avg_game_duration_min=120,
        home_advantage=0.0,
        typical_total=22.0,  # total games
    ),
    "soccer": SportConfig(
        sport_id="soccer",
        sport_name="Soccer (International)",
        series_prefixes=["kxconcacafccupgame", "kxworldcupgame", "kxuefagame",
                        "kxeplgame", "kxlaligagame", "kxsoccer"],
        odds_api_keys=["soccer_epl", "soccer_uefa_champs_league"],
        periods=2, has_clock=True, has_overtime=False,
        avg_game_duration_min=105,
        home_advantage=0.04,
        typical_total=2.5,
    ),
    "wbc": SportConfig(
        sport_id="wbc",
        sport_name="World Baseball Classic",
        series_prefixes=["kxwbcgame", "kxwbc"],
        odds_api_keys=["baseball_mlb"],  # closest match
        periods=9, has_clock=False, has_overtime=True,
        avg_game_duration_min=180,
        home_advantage=0.02,
        typical_total=8.0,
    ),
}


# ── Market Type Detection ─────────────────────────────────────────────────

class MarketType:
    SPREAD = "spread"
    TOTAL = "total"
    MONEYLINE = "moneyline"
    PROP = "prop"
    FUTURES = "futures"
    UNKNOWN = "unknown"


# ── Parsed Sports Market ──────────────────────────────────────────────────

@dataclass
class SportsMarketInfo:
    """Fully parsed sports market metadata."""
    is_sports: bool = False
    sport_id: str = ""                  # "nba", "nfl", etc.
    sport_config: SportConfig | None = None
    market_type: str = MarketType.UNKNOWN   # "spread", "total", "moneyline"
    
    # Game info
    event_ticker: str = ""
    series_ticker: str = ""
    ticker: str = ""
    
    # Teams
    home_team: str = ""
    away_team: str = ""
    
    # Timing
    game_date: str = ""                 # "2025-03-26"
    is_live: bool = False               # game currently in progress
    
    # Spread/Total specifics
    spread_value: float | None = None   # e.g., -6.5
    total_value: float | None = None    # e.g., 220.5
    spread_team: str = ""               # which team the spread applies to


# ── The Detector ──────────────────────────────────────────────────────────

class SportsDetector:
    """
    Detects and classifies sports markets from Kalshi metadata.
    
    This is the gatekeeper — if this says a market is not sports,
    Frankenstein won't trade it.
    """
    
    # Title patterns for market type detection
    _SPREAD_PATTERNS = [
        re.compile(r"(spread|handicap|cover|pts?\s*[\+\-])", re.IGNORECASE),
        re.compile(r"(win\s+by|margin)", re.IGNORECASE),
        re.compile(r"[\+\-]\d+\.?\d*\s*(pts?|points?)", re.IGNORECASE),
    ]
    _TOTAL_PATTERNS = [
        re.compile(r"(over|under|total|o/u|combined\s+score)", re.IGNORECASE),
        re.compile(r"(more|fewer)\s+than\s+\d+", re.IGNORECASE),
    ]
    _MONEYLINE_PATTERNS = [
        re.compile(r"\b(win|beat|defeat|advance)\b", re.IGNORECASE),
        re.compile(r"(winner|champion)", re.IGNORECASE),
        re.compile(r"\bwill\s+.+?\s+win\b", re.IGNORECASE),
    ]
    
    # Sports title keywords (backup detection when series_ticker is missing)
    _SPORT_TITLE_KEYWORDS = {
        "nba": ["nba", "basketball", "lakers", "celtics", "warriors", "nets", "bucks", "76ers",
                "knicks", "heat", "bulls", "cavaliers", "mavericks", "nuggets", "suns",
                "clippers", "rockets", "hawks", "pistons", "pacers", "thunder", "grizzlies",
                "pelicans", "hornets", "wizards", "blazers", "timberwolves", "kings", "spurs", "magic", "raptors", "jazz"],
        "ncaab": ["ncaab", "ncaa", "march madness", "final four", "sweet 16", "elite eight",
                  "first half winner", "1st half", "first half", "college basketball"],
        "nfl": ["nfl", "chiefs", "eagles", "49ers", "cowboys", "ravens", "bills",
                "bengals", "lions", "dolphins", "patriots", "steelers", "packers",
                "chargers", "rams", "seahawks", "bears", "vikings", "saints", "falcons",
                "buccaneers", "broncos", "colts", "commanders",
                "titans", "jaguars", "texans", "raiders", "super bowl", "touchdown"],
        "mlb": ["mlb", "baseball", "yankees", "dodgers", "braves", "astros", "mets", "phillies",
                "padres", "cubs", "orioles", "twins", "mariners", "red sox",
                "rays", "guardians", "diamondbacks", "brewers", "blue jays",
                "white sox", "reds", "pirates", "tigers", "royals", "rockies", "nationals",
                "marlins", "athletics", "home run", "strikeout", "inning"],
        "nhl": ["nhl", "hockey", "maple leafs", "bruins", "oilers",
                "avalanche", "hurricanes", "devils", "lightning",
                "penguins", "islanders", "canucks", "senators", "flames",
                "flyers", "kraken", "predators", "blue jackets", "capitals",
                "ducks", "blackhawks", "sabres", "red wings", "sharks", "canadiens",
                "goalscorer", "first goal", "shl"],
        "tennis": ["tennis", "atp", "wta", "djokovic", "nadal", "federer", "alcaraz", "sinner",
                   "medvedev", "zverev", "rublev", "tsitsipas", "ruud", "fritz", "tiafoe",
                   "swiatek", "sabalenka", "gauff", "grand slam", "wimbledon", "us open",
                   "french open", "australian open", "set", "match point"],
        "soccer": ["soccer", "premier league", "la liga", "bundesliga", "serie a",
                   "champions league", "concacaf", "fifa", "world cup", "penalty kick",
                   "red card", "yellow card"],
    }
    
    def __init__(self) -> None:
        self._cache: dict[str, SportsMarketInfo] = {}
        self._stats = {
            "total_detected": 0,
            "by_sport": {},
            "by_market_type": {},
        }
    
    def detect(self, market: Market) -> SportsMarketInfo:
        """
        Detect if a market is a sports market and classify it.
        
        Uses (in order of priority):
          1. series_ticker matching against SPORT_REGISTRY
          2. Title keyword matching
          3. Category hint from Kalshi metadata
        """
        # Check cache first
        if market.ticker in self._cache:
            return self._cache[market.ticker]
        
        info = SportsMarketInfo(
            ticker=market.ticker,
            event_ticker=market.event_ticker,
            series_ticker=market.series_ticker or "",
        )
        
        # Method 1: prefix matching against series_ticker, ticker, AND event_ticker
        # (series_ticker is often empty on Kalshi, so ticker/event is critical)
        candidates = [
            (market.series_ticker or "").lower(),
            (market.ticker or "").lower(),
            (market.event_ticker or "").lower(),
        ]
        # Build a sorted prefix list (longest first → most specific wins)
        _prefix_map: list[tuple[str, str, SportConfig]] = []
        for sport_id, config in SPORT_REGISTRY.items():
            for prefix in config.series_prefixes:
                _prefix_map.append((prefix.lower(), sport_id, config))
        _prefix_map.sort(key=lambda x: len(x[0]), reverse=True)
        
        for prefix, sport_id, config in _prefix_map:
            for candidate in candidates:
                if candidate.startswith(prefix):
                    info.is_sports = True
                    info.sport_id = sport_id
                    info.sport_config = config
                    break
            if info.is_sports:
                break
        
        # Method 2: Title keyword matching (backup)
        if not info.is_sports:
            title = (market.title or "").lower()
            category = (market.category or "").lower()
            
            # Check Kalshi category field
            if "sport" in category:
                info.is_sports = True
                # Try to detect specific sport from title
                for sport_id, keywords in self._SPORT_TITLE_KEYWORDS.items():
                    if any(kw in title for kw in keywords):
                        info.sport_id = sport_id
                        info.sport_config = SPORT_REGISTRY.get(sport_id)
                        break
                if not info.sport_id:
                    info.sport_id = "unknown_sport"
            else:
                # Pure title matching
                for sport_id, keywords in self._SPORT_TITLE_KEYWORDS.items():
                    if any(kw in title for kw in keywords):
                        info.is_sports = True
                        info.sport_id = sport_id
                        info.sport_config = SPORT_REGISTRY.get(sport_id)
                        break
        
        if not info.is_sports:
            self._cache[market.ticker] = info
            return info
        
        # Detect market type
        info.market_type = self._detect_market_type(market)
        
        # Parse teams from title
        info.home_team, info.away_team = self._parse_teams(market)
        
        # Detect if live
        info.is_live = self._is_game_live(market)
        
        # Parse spread/total values from title
        self._parse_line_values(market, info)
        
        # Update stats
        self._stats["total_detected"] += 1
        self._stats["by_sport"][info.sport_id] = self._stats["by_sport"].get(info.sport_id, 0) + 1
        self._stats["by_market_type"][info.market_type] = self._stats["by_market_type"].get(info.market_type, 0) + 1
        
        # Cache
        self._cache[market.ticker] = info
        return info
    
    def is_sports_market(self, market: Market) -> bool:
        """Quick check: is this market sports?"""
        return self.detect(market).is_sports
    
    def filter_sports(self, markets: list[Market]) -> list[Market]:
        """Filter a list of markets to only sports markets."""
        return [m for m in markets if self.is_sports_market(m)]
    
    def get_sport_markets_by_event(self, markets: list[Market]) -> dict[str, list[Market]]:
        """Group sports markets by event_ticker (game)."""
        groups: dict[str, list[Market]] = {}
        for m in markets:
            info = self.detect(m)
            if info.is_sports:
                groups.setdefault(m.event_ticker, []).append(m)
        return groups
    
    def _detect_market_type(self, market: Market) -> str:
        """Detect if this is a spread, total, moneyline, or prop market."""
        title = (market.title or "").lower()
        subtitle = (market.subtitle or "").lower()
        combined = f"{title} {subtitle}"
        ticker = (market.ticker or "").lower()
        
        # Prop market detection (player props, first goalscorer, etc.)
        prop_indicators = [
            "firstgoal", "firstbasket", "player", "points", "rebounds",
            "assists", "strikeout", "passing", "rushing", "td", "hr",
        ]
        if any(ind in ticker for ind in prop_indicators):
            return MarketType.PROP
        prop_title_patterns = [
            r"(first\s+goal|goalscorer|first\s+basket|first\s+touchdown)",
            r"\b\w+\s+\w+\s*:\s*(over|under)\s+\d+",
            r"(points|rebounds|assists|strikeouts?|touchdowns?|yards|goals?)\s*[\>\<\:\(]",
            r"(points|rebounds|assists|strikeouts?|touchdowns?|yards|goals?)\s+(over|under)",
            r"\b\d+\+\s+(points|rebounds|assists|goals|strikeouts)",
        ]
        for pat in prop_title_patterns:
            if re.search(pat, combined, re.IGNORECASE):
                return MarketType.PROP
        
        for pattern in self._SPREAD_PATTERNS:
            if pattern.search(combined):
                return MarketType.SPREAD
        
        for pattern in self._TOTAL_PATTERNS:
            if pattern.search(combined):
                return MarketType.TOTAL
        
        for pattern in self._MONEYLINE_PATTERNS:
            if pattern.search(combined):
                return MarketType.MONEYLINE
        
        # "Winner?" in title → moneyline
        if re.search(r"winner\??", combined, re.IGNORECASE):
            return MarketType.MONEYLINE
        
        # If it contains "vs" or "at" with team names, likely moneyline
        if re.search(r"\bvs\.?\b|\bat\b", combined, re.IGNORECASE):
            return MarketType.MONEYLINE
        
        # FIX #5: 'game' in ticker without other hints -> moneyline
        if "game" in ticker:
            return MarketType.MONEYLINE
        
        return MarketType.UNKNOWN
    
    def _parse_teams(self, market: Market) -> tuple[str, str]:
        """Extract team names from market title."""
        title = market.title or ""
        
        # Pattern: "Team A vs Team B" or "Team A at Team B"
        match = re.search(r"(.+?)\s+(?:vs\.?|at|@)\s+(.+?)(?:\s*[\-\:]|$)", title, re.IGNORECASE)
        if match:
            return match.group(2).strip(), match.group(1).strip()  # home, away
        
        # Pattern: "Will X win?" or "X to win"
        match = re.search(r"(?:Will\s+)?(.+?)\s+(?:win|beat|defeat)", title, re.IGNORECASE)
        if match:
            return match.group(1).strip(), ""
        
        return "", ""
    
    def _is_game_live(self, market: Market) -> bool:
        """Detect if the game is currently in progress."""
        # Check if market is past commence time but not settled
        if market.open_time and market.close_time:
            now = datetime.now(timezone.utc)
            if market.open_time <= now and market.status.value in ("active", "open"):
                # If close_time is in the future and market is actively trading
                # Check expiration_time too
                if market.expiration_time:
                    hours_left = (market.expiration_time - now).total_seconds() / 3600
                    # Sports games typically have short expiry windows
                    if hours_left < 6:
                        return True
        
        # Check title for "LIVE" indicator
        title = (market.title or "").upper()
        if "LIVE" in title or "IN-GAME" in title or "IN GAME" in title:
            return True
        
        return False
    
    def _parse_line_values(self, market: Market, info: SportsMarketInfo) -> None:
        """Parse spread and total values from market title/subtitle."""
        title = market.title or ""
        subtitle = market.subtitle or ""
        combined = f"{title} {subtitle}"
        
        # Parse spread: "-6.5", "+3", etc.
        spread_match = re.search(r"([\+\-]\d+\.?\d*)\s*(?:pts?|points?|spread)?", combined)
        if spread_match and info.market_type == MarketType.SPREAD:
            try:
                info.spread_value = float(spread_match.group(1))
            except ValueError:
                pass
        
        # Parse total: "over 220.5", "under 45", "o/u 6.5"
        total_match = re.search(r"(?:over|under|o/u|total)\s*(\d+\.?\d*)", combined, re.IGNORECASE)
        if total_match:
            try:
                info.total_value = float(total_match.group(1))
            except ValueError:
                pass
    
    def invalidate_cache(self, ticker: str | None = None) -> None:
        """Clear detection cache."""
        if ticker:
            self._cache.pop(ticker, None)
        else:
            self._cache.clear()
    
    def stats(self) -> dict[str, Any]:
        """Detection statistics."""
        return {
            "cached_detections": len(self._cache),
            "sports_detected": self._stats["total_detected"],
            "by_sport": dict(self._stats["by_sport"]),
            "by_market_type": dict(self._stats["by_market_type"]),
        }


# ── Singleton ─────────────────────────────────────────────────────────────

sports_detector = SportsDetector()
