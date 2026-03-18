"""
Phase 6 — Crypto Price Feed.

Free cryptocurrency data from CoinGecko (no API key needed):
  • Current prices + 24h change for BTC, ETH, SOL, etc.
  • Market cap, volume, volatility
  • Price trend signals for Kalshi crypto markets

CoinGecko free tier: 10-30 req/min depending on endpoint.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.intelligence.base import DataSource, DataSourceType, SourceHealth, SourceSignal
from app.logging_config import get_logger

log = get_logger("intelligence.crypto")

# Coins that Kalshi has markets for
TRACKED_COINS = {
    "bitcoin": "BTC",
    "ethereum": "ETH",
    "solana": "SOL",
    "dogecoin": "DOGE",
    "ripple": "XRP",
    "cardano": "ADA",
}

COINGECKO_BASE = "https://api.coingecko.com/api/v3"


class CryptoPriceFeed(DataSource):
    """
    Free crypto price data from CoinGecko for Kalshi crypto markets.
    """

    def __init__(
        self,
        poll_interval: float = 90.0,
        enabled: bool = True,
    ) -> None:
        self._poll_interval = poll_interval
        self._enabled = enabled
        self._client: httpx.AsyncClient | None = None

        self._price_cache: dict[str, dict[str, Any]] = {}
        self._price_history: dict[str, list[float]] = {}  # coin → last N prices
        self._stats = {
            "fetches": 0, "errors": 0, "total_signals": 0,
        }

    @property
    def name(self) -> str:
        return "crypto_prices"

    @property
    def source_type(self) -> DataSourceType:
        return DataSourceType.CRYPTO

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def poll_interval_seconds(self) -> float:
        return self._poll_interval

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            headers={"Accept": "application/json"},
            follow_redirects=True,
        )
        log.info("crypto_price_feed_started")

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def fetch_signals(self, tickers: list[str] | None = None) -> list[SourceSignal]:
        if not self._client:
            return []

        signals: list[SourceSignal] = []

        try:
            coins_str = ",".join(TRACKED_COINS.keys())
            url = f"{COINGECKO_BASE}/coins/markets"
            params = {
                "vs_currency": "usd",
                "ids": coins_str,
                "order": "market_cap_desc",
                "per_page": "20",
                "page": "1",
                "sparkline": "false",
                "price_change_percentage": "1h,24h,7d",
            }
            resp = await self._client.get(url, params=params)
            self._stats["fetches"] += 1

            if resp.status_code == 429:
                log.debug("coingecko_rate_limited")
                return []

            if resp.status_code != 200:
                self._stats["errors"] += 1
                return []

            data = resp.json()

            for coin in data:
                coin_id = coin.get("id", "")
                symbol = coin.get("symbol", "").upper()
                price = coin.get("current_price", 0)
                change_24h = coin.get("price_change_percentage_24h", 0) or 0
                change_1h = coin.get("price_change_percentage_1h_in_currency", 0) or 0
                change_7d = coin.get("price_change_percentage_7d_in_currency", 0) or 0
                volume = coin.get("total_volume", 0) or 0
                market_cap = coin.get("market_cap", 0) or 0
                high_24h = coin.get("high_24h", 0) or 0
                low_24h = coin.get("low_24h", 0) or 0
                ath = coin.get("ath", 0) or 0

                if price <= 0:
                    continue

                # Cache
                self._price_cache[coin_id] = {
                    "price": price, "symbol": symbol,
                    "change_24h": change_24h, "change_1h": change_1h,
                    "volume": volume, "market_cap": market_cap,
                    "timestamp": time.time(),
                }

                # Track price history for volatility
                hist = self._price_history.setdefault(coin_id, [])
                hist.append(price)
                if len(hist) > 200:
                    self._price_history[coin_id] = hist[-200:]

                # Compute volatility from price history
                volatility = 0.0
                if len(hist) > 5:
                    returns = [(hist[i] - hist[i - 1]) / hist[i - 1]
                               for i in range(1, len(hist)) if hist[i - 1] > 0]
                    if returns:
                        mean_ret = sum(returns) / len(returns)
                        volatility = (sum((r - mean_ret) ** 2 for r in returns) / len(returns)) ** 0.5

                # Signal value: normalised momentum (-1 to +1)
                momentum = max(-1.0, min(1.0, change_24h / 10.0))

                # Distance from 24h range midpoint
                range_mid = (high_24h + low_24h) / 2 if high_24h > 0 else price
                range_size = high_24h - low_24h if high_24h > low_24h else 1
                range_position = (price - range_mid) / (range_size / 2) if range_size > 0 else 0

                # Distance from ATH
                ath_distance = (ath - price) / ath if ath > 0 else 0

                signals.append(SourceSignal(
                    source_name=self.name,
                    source_type=self.source_type,
                    ticker=f"crypto:{symbol}",
                    signal_value=momentum,
                    confidence=0.75,
                    edge_estimate=0.0,
                    category="crypto",
                    headline=f"{symbol}: ${price:,.2f} ({change_24h:+.1f}% 24h)",
                    features={
                        "crypto_price": price,
                        "crypto_change_1h": round(change_1h, 4),
                        "crypto_change_24h": round(change_24h, 4),
                        "crypto_change_7d": round(change_7d, 4),
                        "crypto_volume_usd": volume,
                        "crypto_market_cap": market_cap,
                        "crypto_volatility": round(volatility, 6),
                        "crypto_range_position": round(range_position, 4),
                        "crypto_ath_distance": round(ath_distance, 4),
                        "crypto_momentum": round(momentum, 4),
                    },
                    raw_data=coin,
                ))

        except Exception as e:
            self._stats["errors"] += 1
            log.debug("coingecko_error", error=str(e))

        self._stats["total_signals"] += len(signals)
        return signals

    def get_prices(self) -> dict[str, dict]:
        """Get current price cache for dashboard."""
        return dict(self._price_cache)

    def health(self) -> SourceHealth:
        return SourceHealth(
            name=self.name,
            source_type=self.source_type,
            enabled=self._enabled,
            healthy=self._stats["errors"] < self._stats["fetches"] + 1,
            total_fetches=self._stats["fetches"],
            total_errors=self._stats["errors"],
            total_signals=self._stats["total_signals"],
            api_calls_limit=0,  # CoinGecko free has rate limit but no hard cap
        )
