"""
Phase 7 — Polymarket Cross-Market Intelligence.

Scrapes Polymarket (prediction market on Polygon) for event prices.
Polymarket's CLOB API is public — no API key required.

Why this matters: when Polymarket and Kalshi disagree on the same
event, there's an arb-like edge.  Even directional discrepancy
is a strong alpha signal.
"""

from __future__ import annotations

import re
import time
from typing import Any

import httpx

from app.intelligence.base import DataSource, DataSourceType, SourceHealth, SourceSignal
from app.logging_config import get_logger

log = get_logger("intelligence.polymarket")

POLYMARKET_GAMMA_API = "https://gamma-api.polymarket.com"


class PolymarketSource(DataSource):
    """
    Cross-market intelligence from Polymarket public API.

    Fetches active event markets and compares their prices to Kalshi
    equivalent markets for divergence signals.
    """

    def __init__(
        self,
        poll_interval: float = 120.0,
        enabled: bool = True,
    ) -> None:
        self._poll_interval = poll_interval
        self._enabled = enabled
        self._client: httpx.AsyncClient | None = None

        self._market_cache: dict[str, dict[str, Any]] = {}  # slug → market data
        self._stats = {
            "fetches": 0, "errors": 0, "markets_found": 0, "total_signals": 0,
        }

    @property
    def name(self) -> str:
        return "polymarket"

    @property
    def source_type(self) -> DataSourceType:
        return DataSourceType.PREDICTION_MARKET

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def poll_interval_seconds(self) -> float:
        return self._poll_interval

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(20.0),
            headers={
                "Accept": "application/json",
                "User-Agent": "JA-Hedge/1.0",
            },
            follow_redirects=True,
        )
        log.info("polymarket_source_started")

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def fetch_signals(self, tickers: list[str] | None = None) -> list[SourceSignal]:
        if not self._client:
            return []

        signals: list[SourceSignal] = []

        try:
            # Fetch active markets from Gamma API
            markets = await self._fetch_active_markets()
            self._stats["markets_found"] = len(markets)

            for market in markets:
                sig = self._market_to_signal(market)
                if sig:
                    signals.append(sig)

        except Exception as e:
            self._stats["errors"] += 1
            log.debug("polymarket_error", error=str(e))

        self._stats["total_signals"] += len(signals)
        return signals

    async def _fetch_active_markets(self) -> list[dict]:
        """Fetch active markets from Polymarket Gamma API."""
        if not self._client:
            return []

        markets: list[dict] = []

        try:
            # Gamma API endpoints
            url = f"{POLYMARKET_GAMMA_API}/markets"
            params = {
                "closed": "false",
                "limit": "100",
                "order": "volume24hr",
                "ascending": "false",
            }
            resp = await self._client.get(url, params=params)
            self._stats["fetches"] += 1

            if resp.status_code != 200:
                self._stats["errors"] += 1
                return []

            data = resp.json()
            if isinstance(data, list):
                markets = data
            elif isinstance(data, dict):
                markets = data.get("data", data.get("markets", []))

        except Exception as e:
            self._stats["errors"] += 1
            log.debug("polymarket_fetch_error", error=str(e))

        # Also try events endpoint for richer data
        try:
            url = f"{POLYMARKET_GAMMA_API}/events"
            params = {
                "closed": "false",
                "limit": "50",
                "order": "volume24hr",
                "ascending": "false",
            }
            resp = await self._client.get(url, params=params)

            if resp.status_code == 200:
                events = resp.json()
                if isinstance(events, list):
                    for event in events:
                        for mkt in event.get("markets", []):
                            markets.append(mkt)

        except Exception:
            pass

        return markets

    def _market_to_signal(self, market: dict) -> SourceSignal | None:
        """Convert a Polymarket market to a SourceSignal."""
        try:
            question = market.get("question", "") or market.get("title", "")
            if not question:
                return None

            # Extract price/probability
            outcome_prices = market.get("outcomePrices", "")
            best_bid = 0.0
            best_ask = 0.0

            if isinstance(outcome_prices, str) and outcome_prices:
                try:
                    import json
                    prices = json.loads(outcome_prices)
                    if len(prices) >= 1:
                        best_bid = float(prices[0])
                    if len(prices) >= 2:
                        best_ask = float(prices[1])
                except (json.JSONDecodeError, ValueError):
                    pass
            elif isinstance(outcome_prices, list) and len(outcome_prices) >= 1:
                best_bid = float(outcome_prices[0])
                if len(outcome_prices) >= 2:
                    best_ask = float(outcome_prices[1])

            # Also try direct price fields
            if best_bid == 0:
                best_bid = float(market.get("bestBid", 0) or 0)
            if best_ask == 0:
                best_ask = float(market.get("bestAsk", 0) or 0)

            # Mid price as probability estimate
            mid_price = (best_bid + best_ask) / 2 if best_bid > 0 and best_ask > 0 else best_bid or best_ask

            if mid_price <= 0:
                return None

            volume = float(market.get("volume24hr", 0) or market.get("volume", 0) or 0)
            liquidity = float(market.get("liquidityClob", 0) or market.get("liquidity", 0) or 0)

            # Categorise the market
            category = self._categorize(question)
            slug = market.get("slug", market.get("conditionId", ""))

            # Cache
            self._market_cache[slug or question[:50]] = {
                "question": question,
                "price": mid_price,
                "volume_24h": volume,
                "liquidity": liquidity,
                "timestamp": time.time(),
            }

            # Signal value: the Polymarket probability itself (0 to 1 mapped to -1 to 1)
            signal = mid_price - 0.5  # centers around 0

            return SourceSignal(
                source_name=self.name,
                source_type=self.source_type,
                ticker=f"poly:{slug or self._slugify(question)}",
                signal_value=signal * 2,  # scale to -1..+1
                confidence=min(0.85, 0.4 + (volume / 100000) * 0.3),
                edge_estimate=0.0,  # computed when matched to Kalshi
                category=category,
                headline=question[:200],
                features={
                    "poly_price": round(mid_price, 4),
                    "poly_volume_24h": round(volume, 2),
                    "poly_liquidity": round(liquidity, 2),
                    "poly_bid": round(best_bid, 4),
                    "poly_ask": round(best_ask, 4),
                    "poly_spread": round(abs(best_ask - best_bid), 4),
                },
                raw_data={
                    "question": question,
                    "slug": slug,
                    "category": category,
                },
            )

        except Exception as e:
            log.debug("poly_market_parse_error", error=str(e))
            return None

    @staticmethod
    def _categorize(question: str) -> str:
        """Categorise a Polymarket question."""
        q = question.lower()
        if any(w in q for w in ["trump", "biden", "election", "congress", "president", "democrat", "republican"]):
            return "politics"
        if any(w in q for w in ["bitcoin", "btc", "ethereum", "eth", "crypto"]):
            return "crypto"
        if any(w in q for w in ["nba", "nfl", "mlb", "nhl", "ufc", "champion"]):
            return "sports"
        if any(w in q for w in ["fed", "inflation", "gdp", "recession", "rate"]):
            return "economics"
        if any(w in q for w in ["hurricane", "earthquake", "tornado", "temperature"]):
            return "weather"
        if any(w in q for w in ["ai", "openai", "chatgpt", "tech"]):
            return "tech"
        return "other"

    @staticmethod
    def _slugify(text: str) -> str:
        return re.sub(r'[^a-z0-9]+', '-', text.lower())[:60]

    def get_markets(self, category: str = "") -> list[dict]:
        """Get cached markets for dashboard."""
        markets = list(self._market_cache.values())
        if category:
            markets = [m for m in markets if self._categorize(m.get("question", "")) == category]
        return sorted(markets, key=lambda m: m.get("volume_24h", 0), reverse=True)[:50]

    def health(self) -> SourceHealth:
        return SourceHealth(
            name=self.name,
            source_type=self.source_type,
            enabled=self._enabled,
            healthy=self._stats["errors"] < self._stats["fetches"] + 1,
            total_fetches=self._stats["fetches"],
            total_errors=self._stats["errors"],
            total_signals=self._stats["total_signals"],
        )
