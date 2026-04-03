"""
Phase 24 \u2014 Free Sports Odds via ESPN Public API.

ESPN's scoreboard endpoints include betting odds data from major
sportsbooks (Caesars, BetMGM, ESPN BET) and require no API key.

Replaces the dead DraftKings + FanDuel scrapers (DK returns 403
via Akamai WAF, FD returns 400 after API restructure).

Sources:
  - ESPN Scoreboard API (public JSON, includes odds)
    NBA / NFL / MLB / NHL / MMA / NCAAB

Rate-limited to ~1 req / 45s per sport to be a good citizen.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.intelligence.base import DataSource, DataSourceType, SourceHealth, SourceSignal
from app.logging_config import get_logger

log = get_logger("intelligence.sports_odds")

# -- ESPN Scoreboard endpoints ------------------------------------------------

ESPN_SPORTS = {
    "basketball_nba":  "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
    "football_nfl":    "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
    "baseball_mlb":    "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard",
    "hockey_nhl":      "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard",
    "mma_mixed_martial_arts": "https://site.api.espn.com/apis/site/v2/sports/mma/ufc/scoreboard",
    "basketball_ncaab": "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard",
}


@dataclass
class OddsLine:
    """Parsed moneyline odds for a single game."""
    sport: str
    home_team: str
    away_team: str
    home_ml: int = 0
    away_ml: int = 0
    home_prob: float = 0.0
    away_prob: float = 0.0
    source: str = ""
    timestamp: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)


def _american_to_prob(ml: int) -> float:
    """Convert American moneyline to implied probability."""
    if ml == 0:
        return 0.0
    if ml > 0:
        return 100.0 / (ml + 100.0)
    return abs(ml) / (abs(ml) + 100.0)


def _remove_vig(p1: float, p2: float) -> tuple[float, float]:
    """Remove bookmaker vig from a pair of implied probabilities."""
    total = p1 + p2
    if total <= 0:
        return (0.5, 0.5)
    return (p1 / total, p2 / total)


class SportsOddsScraper(DataSource):
    """
    Free sports odds from ESPN public scoreboard API.

    Provides Vegas-consensus probability anchors for sports markets.
    ESPN embeds odds from multiple books (Caesars, ESPN BET, BetMGM)
    in their scoreboard JSON, giving us multi-book consensus for free.
    """

    def __init__(
        self,
        poll_interval: float = 45.0,
        enabled: bool = True,
    ) -> None:
        self._poll_interval = poll_interval
        self._enabled = enabled
        self._client: httpx.AsyncClient | None = None

        self._odds_cache: dict[str, list[OddsLine]] = {}
        self._last_fetch: dict[str, float] = {}
        self._stats = {
            "espn_fetches": 0, "espn_errors": 0, "espn_events": 0,
            "total_signals": 0,
        }
        self._ticker_team_cache: dict[str, tuple[str, str]] = {}

    @property
    def name(self) -> str:
        return "sports_odds_scraper"

    @property
    def source_type(self) -> DataSourceType:
        return DataSourceType.SPORTS_ODDS

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
                "Accept": "application/json",
            },
            follow_redirects=True,
        )
        log.info("sports_odds_scraper_started", source="espn")

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def fetch_signals(self, tickers: list[str] | None = None) -> list[SourceSignal]:
        """Fetch odds from ESPN scoreboard and produce signals."""
        if not self._client:
            return []

        tasks = [self._fetch_espn_sport(sport, url) for sport, url in ESPN_SPORTS.items()]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_lines: list[OddsLine] = []
        for res in results:
            if isinstance(res, list):
                all_lines.extend(res)
            elif isinstance(res, Exception):
                log.debug("espn_sport_error", error=str(res))

        if not all_lines:
            return []

        games: dict[str, list[OddsLine]] = {}
        for line in all_lines:
            key = self._game_key(line)
            games.setdefault(key, []).append(line)

        signals: list[SourceSignal] = []
        for game_key, lines in games.items():
            home_probs = [l.home_prob for l in lines if l.home_prob > 0]
            away_probs = [l.away_prob for l in lines if l.away_prob > 0]

            if not home_probs:
                continue

            consensus_home = sum(home_probs) / len(home_probs)
            consensus_away = sum(away_probs) / len(away_probs) if away_probs else 1.0 - consensus_home

            sport = lines[0].sport
            self._odds_cache.setdefault(sport, [])

            features = {
                "vegas_home_prob": round(consensus_home, 4),
                "vegas_away_prob": round(consensus_away, 4),
                "num_books": len(lines),
                "book_spread": round(max(home_probs) - min(home_probs), 4) if len(home_probs) > 1 else 0.0,
                "home_ml_avg": round(sum(l.home_ml for l in lines) / len(lines)),
                "away_ml_avg": round(sum(l.away_ml for l in lines) / len(lines)),
            }

            sig = SourceSignal(
                source_name=self.name,
                source_type=self.source_type,
                ticker=game_key,
                signal_value=consensus_home - 0.5,
                confidence=min(0.9, 0.5 + len(lines) * 0.15),
                edge_estimate=0.0,
                category=sport,
                headline=f"{lines[0].away_team} @ {lines[0].home_team}",
                features=features,
                raw_data={
                    "home_team": lines[0].home_team,
                    "away_team": lines[0].away_team,
                    "sport": sport,
                    "sources": [l.source for l in lines],
                },
            )
            signals.append(sig)

        self._stats["total_signals"] += len(signals)
        return signals

    # -- ESPN Scoreboard -------------------------------------------------------

    async def _fetch_espn_sport(self, sport: str, url: str) -> list[OddsLine]:
        """Fetch moneylines from ESPN scoreboard for one sport."""
        if not self._client:
            return []

        last = self._last_fetch.get(f"espn_{sport}", 0)
        if time.time() - last < 30:
            return []

        lines: list[OddsLine] = []

        try:
            resp = await self._client.get(url)
            self._stats["espn_fetches"] += 1
            self._last_fetch[f"espn_{sport}"] = time.time()

            if resp.status_code != 200:
                self._stats["espn_errors"] += 1
                log.debug("espn_http_error", sport=sport, status=resp.status_code)
                return []

            data = resp.json()
            events = data.get("events", [])

            for event in events:
                try:
                    parsed = self._parse_espn_event(event, sport)
                    lines.extend(parsed)
                except Exception as e:
                    log.debug("espn_event_parse_error", sport=sport, error=str(e))

            self._stats["espn_events"] += len(lines)

        except Exception as e:
            self._stats["espn_errors"] += 1
            log.debug("espn_sport_fetch_error", sport=sport, error=str(e))

        return lines

    def _parse_espn_event(self, event: dict, sport: str) -> list[OddsLine]:
        """Parse one ESPN event into OddsLine objects (one per book)."""
        lines: list[OddsLine] = []

        competitions = event.get("competitions", [])
        if not competitions:
            return []

        comp = competitions[0]
        competitors = comp.get("competitors", [])
        if len(competitors) < 2:
            return []

        home_name = ""
        away_name = ""
        for c in competitors:
            team = c.get("team", {})
            name = team.get("displayName", team.get("shortDisplayName", team.get("name", "")))
            if c.get("homeAway") == "home":
                home_name = name
            else:
                away_name = name

        if not home_name or not away_name:
            return []

        odds_list = comp.get("odds", [])
        for odds in odds_list:
            provider = odds.get("provider", {}).get("name", "unknown").lower()

            home_odds = odds.get("homeTeamOdds", {})
            away_odds = odds.get("awayTeamOdds", {})

            home_ml = self._extract_ml(home_odds)
            away_ml = self._extract_ml(away_odds)

            if home_ml == 0 and away_ml == 0:
                continue

            hp = _american_to_prob(home_ml)
            ap = _american_to_prob(away_ml)
            hp, ap = _remove_vig(hp, ap)

            if hp > 0 and ap > 0:
                lines.append(OddsLine(
                    sport=sport,
                    home_team=home_name,
                    away_team=away_name,
                    home_ml=home_ml,
                    away_ml=away_ml,
                    home_prob=hp,
                    away_prob=ap,
                    source=provider,
                    timestamp=time.time(),
                ))

        return lines

    @staticmethod
    def _extract_ml(team_odds: dict) -> int:
        """Extract moneyline from ESPN team odds object."""
        for key in ("moneyLine", "moneyline", "odds"):
            val = team_odds.get(key)
            if val is not None:
                try:
                    return int(float(str(val).replace("+", "").replace("EVEN", "100").strip()))
                except (ValueError, TypeError):
                    continue
        return 0

    # -- Helpers ---------------------------------------------------------------

    @staticmethod
    def _game_key(line: OddsLine) -> str:
        """Normalised game key for dedup across books."""
        home = re.sub(r"[^a-z]", "", line.home_team.lower())
        away = re.sub(r"[^a-z]", "", line.away_team.lower())
        return f"{line.sport}:{away}@{home}"

    def get_odds_for_teams(self, home: str, away: str, sport: str = "") -> dict[str, float] | None:
        """Look up consensus odds for a team matchup."""
        home_n = re.sub(r"[^a-z]", "", home.lower())
        away_n = re.sub(r"[^a-z]", "", away.lower())

        best: list[OddsLine] = []
        for sport_key, lines_list in self._odds_cache.items():
            for line in lines_list:
                lh = re.sub(r"[^a-z]", "", line.home_team.lower())
                la = re.sub(r"[^a-z]", "", line.away_team.lower())
                if (home_n in lh or lh in home_n) and (away_n in la or la in away_n):
                    best.append(line)

        if not best:
            return None

        home_probs = [l.home_prob for l in best]
        return {
            "home_prob": sum(home_probs) / len(home_probs),
            "away_prob": 1.0 - sum(home_probs) / len(home_probs),
            "num_books": len(best),
            "book_spread": max(home_probs) - min(home_probs) if len(home_probs) > 1 else 0.0,
        }

    def health(self) -> SourceHealth:
        return SourceHealth(
            name=self.name,
            source_type=self.source_type,
            enabled=self._enabled,
            healthy=self._stats["espn_errors"] < self._stats["espn_fetches"] + 1,
            total_fetches=self._stats["espn_fetches"],
            total_errors=self._stats["espn_errors"],
            total_signals=self._stats["total_signals"],
            api_calls_limit=0,
        )
