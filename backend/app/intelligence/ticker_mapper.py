"""
TickerMapper — Maps Kalshi tickers to Intelligence Hub signal keys.

This is the critical bridge between Kalshi's ticker format and the
intelligence sources' signal keys.  Without it, the hub has data
but the scanner can never find it.

Kalshi ticker patterns:
  KXBTC-26APR-T100K       → crypto:BTC,    strike=100000
  KXETH-26APR-T3500       → crypto:ETH,    strike=3500
  KXSP500-26APR-T5500     → (S&P 500),     strike=5500
  KXNBA...-LAKLAL         → basketball_nba (Lakers)
  KXMLB...-NYMSF          → baseball_mlb   (NYM vs SF)
  KXNHL...-BOSNYR         → hockey_nhl     (BOS vs NYR)
  KXBONDI...-T4.30        → econ:DGS10,    strike=4.30
  KXGOLD...-T5066.99      → econ:gold,     strike=5066.99
  KXTEMP...-NYC-T85       → weather:new_york, strike=85
  KXTRUMP...               → poly:trump     (political)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.logging_config import get_logger

log = get_logger("intelligence.ticker_mapper")


@dataclass
class TickerMapping:
    """Result of mapping a Kalshi ticker to intelligence keys."""
    kalshi_ticker: str
    category: str                          # crypto, sports, finance, politics, weather, economics
    intelligence_keys: list[str]           # Keys to look up in the signal cache
    strike_price: float | None = None      # Extracted strike (e.g., 100000 for KXBTC-T100K)
    underlying: str = ""                   # e.g., "bitcoin", "10y_treasury", "lakers"
    sport: str = ""                        # e.g., "nba", "mlb", "nhl"
    teams: tuple[str, str] = ("", "")      # (home, away) for sports
    city: str = ""                         # For weather markets


# ── Crypto Mapping ──────────────────────────────────────────────────

# Ticker prefix → (CoinGecko id, symbol)
CRYPTO_MAP = {
    "KXBTC":   ("bitcoin", "BTC"),
    "KXETH":   ("ethereum", "ETH"),
    "KXSOL":   ("solana", "SOL"),
    "KXDOGE":  ("dogecoin", "DOGE"),
    "KXADA":   ("cardano", "ADA"),
    "KXXRP":   ("ripple", "XRP"),
    "KXBNB":   ("binancecoin", "BNB"),
    "KXAVAX":  ("avalanche-2", "AVAX"),
    "KXDOT":   ("polkadot", "DOT"),
    "KXMATIC": ("matic-network", "MATIC"),
    "KXLINK":  ("chainlink", "LINK"),
}

# ── Finance / Commodity Mapping ─────────────────────────────────────

FINANCE_MAP = {
    "KXSP500":    ("SP500", "S&P 500"),
    "KXSPX":      ("SP500", "S&P 500"),
    "KXNDX":      ("NASDAQ", "Nasdaq 100"),
    "KXNASDAQ":   ("NASDAQ", "Nasdaq 100"),
    "KXDOW":      ("DJI", "Dow Jones"),
    "KXDJIA":     ("DJI", "Dow Jones"),
    "KXRUT":      ("RUT", "Russell 2000"),
    "KXGOLD":     ("GOLD", "Gold"),
    "KXGOLDMON":  ("GOLD", "Gold"),
    "KXSILVER":   ("SILVER", "Silver"),
    "KXOIL":      ("OIL", "Crude Oil"),
    "KXCRUDEOIL": ("OIL", "Crude Oil"),
    "KXCOPPER":   ("COPPER", "Copper"),
    "KXCOPPERMON":("COPPER", "Copper"),
    "KXCOFFEE":   ("COFFEE", "Coffee"),
    "KXCOFFEEMON":("COFFEE", "Coffee"),
    "KXBONDI":    ("DGS10", "10Y Treasury"),
    "KXBONDIOUT": ("DGS10", "10Y Treasury"),
    "KXBOND2Y":   ("DGS2", "2Y Treasury"),
    "KXFEDRATE":  ("FEDFUNDS", "Fed Funds Rate"),
    "KXCPI":      ("CPI", "CPI"),
    "KXJOBS":     ("PAYEMS", "Nonfarm Payrolls"),
    "KXUNRATE":   ("UNRATE", "Unemployment"),
    "KXGDP":      ("GDP", "GDP"),
}

# ── Sports Team Abbreviation Mapping ────────────────────────────────

# Common 3-letter team abbreviations used in Kalshi tickers
NBA_TEAMS = {
    "LAL": "lakers", "BOS": "celtics", "GSW": "warriors", "MIL": "bucks",
    "PHI": "76ers", "DEN": "nuggets", "MIA": "heat", "NYK": "knicks",
    "DAL": "mavericks", "PHX": "suns", "LAC": "clippers", "MEM": "grizzlies",
    "SAC": "kings", "CLE": "cavaliers", "MIN": "timberwolves", "NOP": "pelicans",
    "ATL": "hawks", "CHI": "bulls", "TOR": "raptors", "IND": "pacers",
    "OKC": "thunder", "BKN": "nets", "ORL": "magic", "POR": "blazers",
    "CHA": "hornets", "SAS": "spurs", "HOU": "rockets", "DET": "pistons",
    "WAS": "wizards", "UTA": "jazz",
}

MLB_TEAMS = {
    "NYY": "yankees", "BOS": "red-sox", "LAD": "dodgers", "HOU": "astros",
    "ATL": "braves", "NYM": "mets", "PHI": "phillies", "SD": "padres",
    "SF": "giants", "SEA": "mariners", "MIN": "twins", "CLE": "guardians",
    "TB": "rays", "TEX": "rangers", "BAL": "orioles", "MIL": "brewers",
    "CHC": "cubs", "ARI": "diamondbacks", "STL": "cardinals", "DET": "tigers",
    "KC": "royals", "TOR": "blue-jays", "LAA": "angels", "CWS": "white-sox",
    "PIT": "pirates", "CIN": "reds", "COL": "rockies", "OAK": "athletics",
    "MIA": "marlins", "WAS": "nationals",
}

NHL_TEAMS = {
    "BOS": "bruins", "NYR": "rangers", "CAR": "hurricanes", "NJ": "devils",
    "FLA": "panthers", "TOR": "maple-leafs", "TB": "lightning", "COL": "avalanche",
    "DAL": "stars", "VGK": "golden-knights", "EDM": "oilers", "WPG": "jets",
    "MIN": "wild", "LA": "kings", "VAN": "canucks", "SEA": "kraken",
    "CGY": "flames", "OTT": "senators", "NYI": "islanders", "PIT": "penguins",
    "DET": "red-wings", "PHI": "flyers", "WSH": "capitals", "STL": "blues",
    "BUF": "sabres", "ARI": "coyotes", "CHI": "blackhawks", "NSH": "predators",
    "CBJ": "blue-jackets", "ANA": "ducks", "SJ": "sharks", "MTL": "canadiens",
}

NFL_TEAMS = {
    "KC": "chiefs", "BUF": "bills", "MIA": "dolphins", "NE": "patriots",
    "BAL": "ravens", "CIN": "bengals", "CLE": "browns", "PIT": "steelers",
    "HOU": "texans", "IND": "colts", "JAX": "jaguars", "TEN": "titans",
    "DEN": "broncos", "LV": "raiders", "LAC": "chargers", "SEA": "seahawks",
    "DAL": "cowboys", "NYG": "giants", "PHI": "eagles", "WAS": "commanders",
    "CHI": "bears", "DET": "lions", "GB": "packers", "MIN": "vikings",
    "ATL": "falcons", "CAR": "panthers", "NO": "saints", "TB": "buccaneers",
    "ARI": "cardinals", "LAR": "rams", "SF": "49ers",
}

SPORT_TEAM_MAPS = {
    "nba": NBA_TEAMS,
    "mlb": MLB_TEAMS,
    "nhl": NHL_TEAMS,
    "nfl": NFL_TEAMS,
}

# Kalshi sport prefixes
SPORT_PREFIX_MAP = {
    "KXNBA": ("basketball_nba", "nba"),
    "KXNBAGAME": ("basketball_nba", "nba"),
    "KXNBAPLAY": ("basketball_nba", "nba"),
    "KXMLB": ("baseball_mlb", "mlb"),
    "KXMLBHR": ("baseball_mlb", "mlb"),
    "KXMLBHIT": ("baseball_mlb", "mlb"),
    "KXMLBGAME": ("baseball_mlb", "mlb"),
    "KXNHL": ("hockey_nhl", "nhl"),
    "KXNHLGAME": ("hockey_nhl", "nhl"),
    "KXNFL": ("football_nfl", "nfl"),
    "KXNFLGAME": ("football_nfl", "nfl"),
    "KXNCAA": ("basketball_ncaab", "ncaab"),
    "KXNCAAMB": ("basketball_ncaab", "ncaab"),
    "KXMMA": ("mma_mixed_martial_arts", "mma"),
    "KXUFC": ("mma_mixed_martial_arts", "mma"),
}

# ── Political Mapping ───────────────────────────────────────────────

POLITICAL_KEYWORDS = [
    "TRUMP", "BIDEN", "HARRIS", "PRESIDENT", "SENATE", "HOUSE",
    "CONGRESS", "SCOTUS", "GOVERNOR", "ELECTION", "INAUG",
    "IMPEACH", "CABINET", "EXECUTIVE", "VETO",
]

# ── Weather City Mapping ────────────────────────────────────────────

WEATHER_CITY_MAP = {
    "NYC": "new_york", "NY": "new_york",
    "LA": "los_angeles", "LAX": "los_angeles",
    "CHI": "chicago", "ORD": "chicago",
    "HOU": "houston", "IAH": "houston",
    "PHX": "phoenix",
    "MIA": "miami",
    "DFW": "dallas", "DAL": "dallas",
    "DEN": "denver",
    "ATL": "atlanta",
    "DC": "washington_dc", "DCA": "washington_dc",
    "SEA": "seattle", "SFO": "san_francisco",
    "BOS": "boston",
}

# ── Strike Price Extraction ─────────────────────────────────────────

# Pattern: -T followed by a number (possibly with decimals and K/M suffixes)
STRIKE_RE = re.compile(r"-T([\d.]+)(K|M)?", re.IGNORECASE)


def _extract_strike(ticker: str) -> float | None:
    """Extract strike price from a Kalshi ticker.

    Examples:
      KXBTC-26APR-T100K  → 100000.0
      KXGOLD-T5066.99    → 5066.99
      KXBONDI-T4.30      → 4.30
      KXTEMP-NYC-T85     → 85.0
    """
    m = STRIKE_RE.search(ticker)
    if not m:
        return None
    val = float(m.group(1))
    suffix = (m.group(2) or "").upper()
    if suffix == "K":
        val *= 1000
    elif suffix == "M":
        val *= 1_000_000
    return val


def _extract_teams_from_ticker(ticker: str, sport: str) -> tuple[str, str]:
    """Try to extract team abbreviations from the end of a Kalshi ticker.

    Kalshi often encodes teams as the last segment, e.g.:
      KXNBAGAME-26APR04DETPHI  → DET, PHI
      KXMLBHR-26APR-NYYSF      → NYY, SF
      KXNHLGAME-BOSNYR         → BOS, NYR
    """
    # Get the last segment (after last dash, or last 6+ alphanumeric chars)
    parts = ticker.split("-")
    tail = parts[-1] if len(parts) > 1 else ticker

    # Strip date prefixes like "26APR04"
    tail = re.sub(r"^\d{1,2}[A-Z]{3}\d{0,2}", "", tail)

    team_map = SPORT_TEAM_MAPS.get(sport, {})
    if not team_map or len(tail) < 4:
        return ("", "")

    # Try splitting tail into two team codes (2-3 chars each)
    best = ("", "")
    for split_pos in range(2, min(4, len(tail))):
        t1 = tail[:split_pos].upper()
        t2 = tail[split_pos:].upper()
        if t1 in team_map and t2 in team_map:
            return (t1, t2)
        # Try 3-char first team
        if split_pos == 3 and t1 in team_map:
            best = (t1, t2)
        if split_pos == 2 and t2 in team_map:
            best = (t1, t2)

    return best


class TickerMapper:
    """Maps Kalshi tickers to intelligence signal keys.

    Usage:
        mapper = TickerMapper()
        mapping = mapper.map("KXBTC-26APR-T100K")
        # mapping.intelligence_keys = ["crypto:BTC"]
        # mapping.strike_price = 100000.0
        # mapping.category = "crypto"
    """

    def __init__(self) -> None:
        self._cache: dict[str, TickerMapping] = {}

    def map(self, ticker: str, title: str = "", category_hint: str = "") -> TickerMapping:
        """Map a Kalshi ticker to intelligence signal keys.

        Returns a TickerMapping with all matched intelligence keys,
        extracted strike price, and category information.
        """
        if ticker in self._cache:
            return self._cache[ticker]

        mapping = self._do_map(ticker, title, category_hint)
        self._cache[ticker] = mapping
        return mapping

    def _do_map(self, ticker: str, title: str, category_hint: str) -> TickerMapping:
        """Core mapping logic. Tries crypto → finance → sports → politics → weather."""
        upper = ticker.upper()
        strike = _extract_strike(ticker)

        # ── 1. Crypto ────────────────────────────────
        for prefix, (coin_id, symbol) in CRYPTO_MAP.items():
            if upper.startswith(prefix):
                return TickerMapping(
                    kalshi_ticker=ticker,
                    category="crypto",
                    intelligence_keys=[f"crypto:{symbol}"],
                    strike_price=strike,
                    underlying=coin_id,
                )

        # ── 2. Finance / Commodities / Economics ─────
        # Try exact prefix match (longest first)
        for prefix in sorted(FINANCE_MAP, key=len, reverse=True):
            if upper.startswith(prefix):
                series_id, name = FINANCE_MAP[prefix]
                return TickerMapping(
                    kalshi_ticker=ticker,
                    category="finance",
                    intelligence_keys=[f"econ:{series_id}"],
                    strike_price=strike,
                    underlying=series_id,
                )

        # ── 3. Sports ────────────────────────────────
        for prefix in sorted(SPORT_PREFIX_MAP, key=len, reverse=True):
            if upper.startswith(prefix):
                odds_sport_key, sport = SPORT_PREFIX_MAP[prefix]
                teams = _extract_teams_from_ticker(ticker, sport)
                keys = [f"sport:{odds_sport_key}"]

                # Add team-specific keys for sports odds matching
                team_map = SPORT_TEAM_MAPS.get(sport, {})
                if teams[0] and teams[0] in team_map:
                    keys.append(f"sport:{sport}:{team_map[teams[0]]}")
                if teams[1] and teams[1] in team_map:
                    keys.append(f"sport:{sport}:{team_map[teams[1]]}")
                # Add combined game key for odds lookup
                if teams[0] and teams[1]:
                    t1_name = team_map.get(teams[0], teams[0].lower())
                    t2_name = team_map.get(teams[1], teams[1].lower())
                    keys.append(f"{odds_sport_key}:{t1_name}@{t2_name}")
                    keys.append(f"{odds_sport_key}:{t2_name}@{t1_name}")

                return TickerMapping(
                    kalshi_ticker=ticker,
                    category="sports",
                    intelligence_keys=keys,
                    strike_price=strike,
                    underlying=odds_sport_key,
                    sport=sport,
                    teams=teams,
                )

        # ── 4. Politics ──────────────────────────────
        if any(kw in upper for kw in POLITICAL_KEYWORDS):
            poly_slug = re.sub(r"[^a-z0-9]+", "-", ticker.lower()).strip("-")
            return TickerMapping(
                kalshi_ticker=ticker,
                category="politics",
                intelligence_keys=[f"poly:{poly_slug}"],
                strike_price=strike,
                underlying="politics",
            )

        # ── 5. Weather ───────────────────────────────
        if "TEMP" in upper or "WEATHER" in upper or "PRECIP" in upper or "SNOW" in upper:
            city = ""
            for abbrev, city_key in WEATHER_CITY_MAP.items():
                if abbrev in upper:
                    city = city_key
                    break
            keys = [f"weather:{city}"] if city else ["weather:national"]
            return TickerMapping(
                kalshi_ticker=ticker,
                category="weather",
                intelligence_keys=keys,
                strike_price=strike,
                city=city,
            )

        # ── 6. Category-level fallback ───────────────
        # Use the category hint from Kalshi's own category field
        cat = category_hint.lower() if category_hint else "unknown"
        keys = []
        if cat in ("politics", "political"):
            keys = [f"news:politics", f"social:politics"]
        elif cat in ("economics", "economy"):
            keys = [f"news:economics", f"econ:VIXCLS"]
        elif cat in ("crypto", "cryptocurrency"):
            keys = [f"news:crypto"]
        elif cat in ("sports",):
            keys = [f"news:sports"]
        else:
            keys = [f"news:{cat}"]

        return TickerMapping(
            kalshi_ticker=ticker,
            category=cat,
            intelligence_keys=keys,
            strike_price=strike,
        )

    def clear_cache(self) -> None:
        """Clear the mapping cache (e.g., on market refresh)."""
        self._cache.clear()

    def stats(self) -> dict[str, Any]:
        """Return cache statistics."""
        cats = {}
        for mapping in self._cache.values():
            cats[mapping.category] = cats.get(mapping.category, 0) + 1
        return {
            "cached_mappings": len(self._cache),
            "by_category": cats,
        }
