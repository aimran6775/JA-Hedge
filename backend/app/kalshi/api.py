"""
JA Hedge — Unified Kalshi API Facade.

Combines the raw HTTP client with all typed endpoint wrappers
into a single entry point for the rest of the application.

Usage:
    from app.kalshi.api import KalshiAPI

    async with KalshiAPI.from_settings() as api:
        balance = await api.portfolio.get_balance()
        markets = await api.markets.get_all_markets(status=MarketStatus.ACTIVE)
        order = await api.orders.place_limit_order(...)
"""

from __future__ import annotations

from app.config import Settings, get_settings
from app.kalshi.auth import KalshiAuth, NoAuth
from app.kalshi.client import KalshiClient
from app.kalshi.endpoints.exchange import ExchangeAPI
from app.kalshi.endpoints.historical import HistoricalAPI
from app.kalshi.endpoints.markets import MarketsAPI
from app.kalshi.endpoints.orders import OrdersAPI
from app.kalshi.endpoints.portfolio import PortfolioAPI
from app.kalshi.rate_limiter import RateLimiter
from app.logging_config import get_logger

log = get_logger("kalshi.api")


class KalshiAPI:
    """
    Unified Kalshi API facade.

    Provides typed access to every endpoint through sub-objects:
        .markets    — Markets, Events, Series, Orderbooks
        .portfolio  — Balance, Positions, Fills, Settlements
        .orders     — Create/Cancel/Amend orders, Order Groups
        .exchange   — Exchange status and schedule
        .historical — Candlesticks and public trades
    """

    def __init__(self, client: KalshiClient):
        self._client = client
        self.markets = MarketsAPI(client)
        self.portfolio = PortfolioAPI(client)
        self.orders = OrdersAPI(client)
        self.exchange = ExchangeAPI(client)
        self.historical = HistoricalAPI(client)

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> KalshiAPI:
        """
        Create a KalshiAPI from application settings.

        This returns the facade object; you must use it as an async context manager:
            async with KalshiAPI.from_settings() as api:
                ...
        """
        s = settings or get_settings()

        # Build auth
        if s.has_api_keys:
            auth: KalshiAuth | NoAuth = KalshiAuth(
                key_id=s.kalshi_api_key_id,
                private_key_path=s.resolved_key_path,
            )
            log.info("kalshi_api_authenticated", mode=s.jahedge_mode.value)
        else:
            auth = NoAuth()
            log.warning("kalshi_api_unauthenticated", mode=s.jahedge_mode.value)

        # Build rate limiter
        rate_limiter = RateLimiter(
            read_per_sec=s.rate_limit_read_per_sec,
            write_per_sec=s.rate_limit_write_per_sec,
        )

        # Build client
        client = KalshiClient(
            base_url=s.kalshi_rest_url,
            auth=auth,
            rate_limiter=rate_limiter,
            max_retries=3,
            timeout=s.kalshi_timeout,
        )

        return cls(client)

    @property
    def client(self) -> KalshiClient:
        """Access the underlying HTTP client (for custom requests)."""
        return self._client

    async def __aenter__(self) -> KalshiAPI:
        await self._client.__aenter__()
        return self

    async def __aexit__(self, *args) -> None:
        await self._client.__aexit__(*args)

    async def health_check(self) -> bool:
        """Quick connectivity test — hits /exchange/status."""
        try:
            status = await self.exchange.get_status()
            return status.exchange_active
        except Exception as e:
            log.error("health_check_failed", error=str(e))
            return False
