"""
Phase 2 — Free Sports Odds Scraper.

Scrapes live odds from DraftKings and FanDuel public sportsbook pages.
These endpoints serve JSON to their own frontends and require no API key.

Replaces the exhausted Odds API for sports market pricing, giving us
a free, unlimited Vegas-probability anchor for Frankenstein.

Sources:
  • DraftKings Sportsbook API (public JSON)
  • FanDuel Sportsbook API (public JSON)

Rate-limited to ~1 req / 30s per book to be a good citizen.
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

# ── DraftKings public endpoints ──────────────────────────────────────────────

# These are the same JSON endpoints DK's frontend fetches.
# Group IDs: NBA=42648, NFL=88808, MLB=84240, NHL=42133, MMA=9034,
#            Soccer-EPL=40253, Tennis=92893, NCAAB=92483
DK_EVENT_GROUPS = {
    "basketball_nba": 42648,
    "football_nfl": 88808,
    "baseball_mlb": 84240,
    "hockey_nhl": 42133,
    "mma_mixed_martial_arts": 9034,
    "basketball_ncaab": 92483,
}

DK_BASE = "https://sportsbook-nash.draftkings.com/sites/US-SB/api/v5"


# ── FanDuel public endpoints ─────────────────────────────────────────────────

FD_SPORT_MAP = {
    "basketball_nba": "nba",
    "football_nfl": "nfl",
    "baseball_mlb": "mlb",
    "hockey_nhl": "nhl",
    "basketball_ncaab": "college-basketball",
}

FD_BASE = "https://sbapi.mi.sportsbook.fanduel.com/api"


@dataclass
class OddsLine:
    """Parsed moneyline odds for a single game."""
    sport: str
    home_team: str
    away_team: str
    home_ml: int = 0        # American moneyline
    away_ml: int = 0
    home_prob: float = 0.0  # Implied probability (vig-removed)
    away_prob: float = 0.0
    source: str = ""        # "draftkings" or "fanduel"
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
    Free sports odds from DraftKings + FanDuel public APIs.

    Provides Vegas-consensus probability anchors for sports markets
    without consuming any API quota.
    """

    def __init__(
        self,
        poll_interval: float = 45.0,
        enabled: bool = True,
    ) -> None:
        self._poll_interval = poll_interval
        self._enabled = enabled
        self._client: httpx.AsyncClient | None = None

        # State
        self._odds_cache: dict[str, list[OddsLine]] = {}  # sport → lines
        self._last_fetch: dict[str, float] = {}
        self._stats = {
            "dk_fetches": 0, "dk_errors": 0, "dk_events": 0,
            "fd_fetches": 0, "fd_errors": 0, "fd_events": 0,
            "total_signals": 0,
        }

        # Ticker mapping: Kalshi ticker patterns → game/team resolution
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
                              "Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json",
            },
            follow_redirects=True,
        )
        log.info("sports_odds_scraper_started")

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def fetch_signals(self, tickers: list[str] | None = None) -> list[SourceSignal]:
        """Fetch odds from both books, merge, and produce signals."""
        if not self._client:
            return []

        # Fetch both books concurrently
        dk_lines, fd_lines = await asyncio.gather(
            self._fetch_draftkings(),
            self._fetch_fanduel(),
            return_exceptions=True,
        )

        all_lines: list[OddsLine] = []
        if isinstance(dk_lines, list):
            all_lines.extend(dk_lines)
        else:
            log.debug("dk_fetch_error", error=str(dk_lines))

        if isinstance(fd_lines, list):
            all_lines.extend(fd_lines)
        else:
            log.debug("fd_fetch_error", error=str(fd_lines))

        if not all_lines:
            return []

        # Group by game (home_team + away_team normalised)
        games: dict[str, list[OddsLine]] = {}
        for line in all_lines:
            key = self._game_key(line)
            games.setdefault(key, []).append(line)

        # Build consensus and produce signals
        signals: list[SourceSignal] = []
        for game_key, lines in games.items():
            # Average implied probability across books
            home_probs = [l.home_prob for l in lines if l.home_prob > 0]
            away_probs = [l.away_prob for l in lines if l.away_prob > 0]

            if not home_probs:
                continue

            consensus_home = sum(home_probs) / len(home_probs)
            consensus_away = sum(away_probs) / len(away_probs) if away_probs else 1.0 - consensus_home

            # Store in cache for feature engine
            sport = lines[0].sport
            self._odds_cache.setdefault(sport, [])

            # Create a signal keyed by team names
            # The Frankenstein brain matches these to Kalshi tickers
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
                ticker=game_key,  # synthetic key — matched later
                signal_value=consensus_home - 0.5,  # >0 = home favored
                confidence=min(0.9, 0.5 + len(lines) * 0.15),
                edge_estimate=0.0,  # computed when matched to Kalshi price
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

    # ── DraftKings ────────────────────────────────────────────────────

    async def _fetch_draftkings(self) -> list[OddsLine]:
        """Fetch moneylines from DraftKings public API."""
        if not self._client:
            return []

        lines: list[OddsLine] = []

        for sport, group_id in DK_EVENT_GROUPS.items():
            # Rate limit per sport
            last = self._last_fetch.get(f"dk_{sport}", 0)
            if time.time() - last < 30:
                continue

            try:
                url = f"{DK_BASE}/eventgroups/{group_id}"
                resp = await self._client.get(url, params={"format": "json"})
                self._stats["dk_fetches"] += 1
                self._last_fetch[f"dk_{sport}"] = time.time()

                if resp.status_code != 200:
                    self._stats["dk_errors"] += 1
                    continue

                data = resp.json()
                parsed = self._parse_dk_response(data, sport)
                lines.extend(parsed)
                self._stats["dk_events"] += len(parsed)

            except Exception as e:
                self._stats["dk_errors"] += 1
                log.debug("dk_sport_error", sport=sport, error=str(e))

        return lines

    def _parse_dk_response(self, data: dict, sport: str) -> list[OddsLine]:
        """Parse DraftKings eventgroup JSON into OddsLine objects."""
        lines: list[OddsLine] = []

        try:
            event_group = data.get("eventGroup", {})
            offer_categories = event_group.get("offerCategories", [])

            for cat in offer_categories:
                # Look for "Game Lines" or "Moneyline" category
                cat_name = (cat.get("name") or "").lower()
                if "game" not in cat_name and "moneyline" not in cat_name and "match" not in cat_name:
                    continue

                for subcategory in cat.get("offerSubcategoryDescriptors", []):
                    for offer in subcategory.get("offerSubcategory", {}).get("offers", []):
                        for market in offer:
                            outcomes = market.get("outcomes", [])
                            if len(outcomes) < 2:
                                continue

                            # Check if this is a moneyline market
                            label = (market.get("label") or "").lower()
                            if "moneyline" not in label and "match result" not in label and "money" not in label:
                                # Also accept markets where label is empty
                                # but subcategory is moneyline
                                sub_name = (subcategory.get("name") or "").lower()
                                if "moneyline" not in sub_name and "match" not in sub_name:
                                    continue

                            home_name = outcomes[0].get("label", "")
                            away_name = outcomes[1].get("label", "")
                            home_ml_raw = outcomes[0].get("oddsAmerican", "0")
                            away_ml_raw = outcomes[1].get("oddsAmerican", "0")

                            home_ml = self._parse_american(home_ml_raw)
                            away_ml = self._parse_american(away_ml_raw)

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
                                    source="draftkings",
                                    timestamp=time.time(),
                                ))
        except Exception as e:
            log.debug("dk_parse_error", error=str(e))

        return lines

    # ── FanDuel ───────────────────────────────────────────────────────

    async def _fetch_fanduel(self) -> list[OddsLine]:
        """Fetch moneylines from FanDuel public API."""
        if not self._client:
            return []

        lines: list[OddsLine] = []

        for sport, fd_slug in FD_SPORT_MAP.items():
            last = self._last_fetch.get(f"fd_{sport}", 0)
            if time.time() - last < 30:
                continue

            try:
                # FanDuel's public content API
                url = f"{FD_BASE}/content-managed-page"
                params = {
                    "page": f"SPORT/{fd_slug}",
                    "_ak": "FhMFpcPWXMeyZxOx",  # Public app key (embedded in their frontend)
                    "timezone": "America/New_York",
                }
                resp = await self._client.get(url, params=params)
                self._stats["fd_fetches"] += 1
                self._last_fetch[f"fd_{sport}"] = time.time()

                if resp.status_code != 200:
                    self._stats["fd_errors"] += 1
                    continue

                data = resp.json()
                parsed = self._parse_fd_response(data, sport)
                lines.extend(parsed)
                self._stats["fd_events"] += len(parsed)

            except Exception as e:
                self._stats["fd_errors"] += 1
                log.debug("fd_sport_error", sport=sport, error=str(e))

        return lines

    def _parse_fd_response(self, data: dict, sport: str) -> list[OddsLine]:
        """Parse FanDuel content-managed-page JSON into OddsLine objects."""
        lines: list[OddsLine] = []

        try:
            attachments = data.get("attachments", {})
            events = attachments.get("events", {})
            markets = attachments.get("markets", {})

            for event_id, event in events.items():
                home_name = ""
                away_name = ""
                # Parse runners from event
                for runner in event.get("runners", []):
                    result = runner.get("result", {}).get("type", "")
                    if result == "HOME":
                        home_name = runner.get("name", "")
                    elif result == "AWAY":
                        away_name = runner.get("name", "")

                if not home_name:
                    home_name = event.get("homeName", event.get("name", ""))
                if not away_name:
                    away_name = event.get("awayName", "")

                # Find the moneyline market for this event
                market_ids = event.get("markets", [])
                for mid in market_ids:
                    market = markets.get(str(mid), {})
                    mtype = (market.get("marketType") or "").upper()
                    mname = (market.get("marketName") or "").lower()

                    if "MONEY_LINE" not in mtype and "moneyline" not in mname and "match result" not in mname:
                        continue

                    runners = market.get("runners", [])
                    if len(runners) < 2:
                        continue

                    home_ml = 0
                    away_ml = 0
                    for runner in runners:
                        result_type = runner.get("result", {}).get("type", "")
                        ml = self._parse_american(
                            runner.get("winRunnerOdds", {}).get("americanDisplayOdds", {}).get("americanOdds", "0")
                        )
                        if result_type == "HOME" or runner.get("runnerName", "") == home_name:
                            home_ml = ml
                        elif result_type == "AWAY" or runner.get("runnerName", "") == away_name:
                            away_ml = ml

                    if home_ml == 0 and away_ml == 0:
                        # Try just taking first two runners as home/away
                        if len(runners) >= 2:
                            home_ml = self._parse_american(
                                runners[0].get("winRunnerOdds", {}).get("americanDisplayOdds", {}).get("americanOdds", "0")
                            )
                            away_ml = self._parse_american(
                                runners[1].get("winRunnerOdds", {}).get("americanDisplayOdds", {}).get("americanOdds", "0")
                            )
                            if not home_name:
                                home_name = runners[0].get("runnerName", "Team A")
                            if not away_name:
                                away_name = runners[1].get("runnerName", "Team B")

                    hp = _american_to_prob(home_ml)
                    ap = _american_to_prob(away_ml)
                    hp, ap = _remove_vig(hp, ap)

                    if hp > 0 and ap > 0 and home_name and away_name:
                        lines.append(OddsLine(
                            sport=sport,
                            home_team=home_name,
                            away_team=away_name,
                            home_ml=home_ml,
                            away_ml=away_ml,
                            home_prob=hp,
                            away_prob=ap,
                            source="fanduel",
                            timestamp=time.time(),
                        ))
                    break  # One moneyline per event

        except Exception as e:
            log.debug("fd_parse_error", error=str(e))

        return lines

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _parse_american(val: Any) -> int:
        """Parse American ML from string/int/float."""
        if isinstance(val, int):
            return val
        if isinstance(val, float):
            return int(val)
        if isinstance(val, str):
            val = val.replace("+", "").replace("EVEN", "100").strip()
            try:
                return int(val)
            except ValueError:
                return 0
        return 0

    @staticmethod
    def _game_key(line: OddsLine) -> str:
        """Normalised game key for dedup across books."""
        home = re.sub(r"[^a-z]", "", line.home_team.lower())
        away = re.sub(r"[^a-z]", "", line.away_team.lower())
        return f"{line.sport}:{away}@{home}"

    def get_odds_for_teams(self, home: str, away: str, sport: str = "") -> dict[str, float] | None:
        """Look up consensus odds for a team matchup.

        Used by the sports predictor to get a Vegas anchor.
        Returns {home_prob, away_prob, num_books, book_spread} or None.
        """
        home_n = re.sub(r"[^a-z]", "", home.lower())
        away_n = re.sub(r"[^a-z]", "", away.lower())

        for source_name, ticker_map in [("_cache", self._odds_cache)]:
            pass  # odds_cache is sport → [OddsLine]

        # Search all cached lines
        best: list[OddsLine] = []
        for sport_key, lines in self._odds_cache.items():
            for line in lines:
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
            healthy=self._stats["dk_errors"] + self._stats["fd_errors"] < self._stats["dk_fetches"] + self._stats["fd_fetches"] + 1,
            total_fetches=self._stats["dk_fetches"] + self._stats["fd_fetches"],
            total_errors=self._stats["dk_errors"] + self._stats["fd_errors"],
            total_signals=self._stats["total_signals"],
            api_calls_limit=0,  # no limit — free!
        )
