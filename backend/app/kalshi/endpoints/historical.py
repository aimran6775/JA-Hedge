"""
JA Hedge — Historical / Candlestick endpoints.

Covers:
  GET /series/:ticker/markets/:ticker/candlesticks — OHLCV candlestick data
  GET /markets/:ticker/trades                       — Recent trades
"""

from __future__ import annotations

from typing import Any

from app.kalshi.client import KalshiClient
from app.kalshi.models import Candlestick
from app.logging_config import get_logger

log = get_logger("kalshi.endpoints.historical")


class HistoricalAPI:
    """Typed wrappers for historical data endpoints."""

    def __init__(self, client: KalshiClient):
        self._client = client

    async def get_candlesticks(
        self,
        series_ticker: str,
        market_ticker: str,
        *,
        start_ts: int | None = None,
        end_ts: int | None = None,
        period_interval: int = 60,
    ) -> list[Candlestick]:
        """
        Get OHLCV candlestick data for a market.

        Args:
            series_ticker: Series ticker (e.g., "KXBTC")
            market_ticker: Market ticker (e.g., "KXBTC-24JAN01-T75000")
            start_ts: Start epoch seconds (inclusive)
            end_ts: End epoch seconds (inclusive)
            period_interval: Candle interval in minutes (1, 5, 15, 60, 1440)

        Returns:
            List of Candlestick objects
        """
        params: dict[str, Any] = {"period_interval": period_interval}
        if start_ts is not None:
            params["start_ts"] = start_ts
        if end_ts is not None:
            params["end_ts"] = end_ts

        resp = await self._client.get(
            f"/series/{series_ticker}/markets/{market_ticker}/candlesticks",
            params=params,
            authenticated=False,
        )
        candles = resp.get("candlesticks", [])
        return [Candlestick.model_validate(c) for c in candles]

    async def get_trades(
        self,
        ticker: str,
        *,
        limit: int = 100,
        cursor: str | None = None,
        min_ts: int | None = None,
        max_ts: int | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """
        Get recent public trades for a market.

        Returns:
            (trades, next_cursor)
        """
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        if min_ts is not None:
            params["min_ts"] = min_ts
        if max_ts is not None:
            params["max_ts"] = max_ts

        resp = await self._client.get(
            f"/markets/{ticker}/trades",
            params=params,
            authenticated=False,
        )
        return resp.get("trades", []), resp.get("cursor")

    async def get_all_trades(
        self,
        ticker: str,
        *,
        min_ts: int | None = None,
        max_ts: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch ALL public trades for a market across pages."""
        params: dict[str, Any] = {}
        if min_ts is not None:
            params["min_ts"] = min_ts
        if max_ts is not None:
            params["max_ts"] = max_ts

        return await self._client.get_all_pages(
            f"/markets/{ticker}/trades",
            params=params,
            data_key="trades",
            authenticated=False,
        )
