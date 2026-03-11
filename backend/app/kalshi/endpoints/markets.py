"""
JA Hedge — Markets / Events / Series endpoints.

Covers:
  GET /markets            — List markets (paginated, filterable)
  GET /markets/:ticker    — Single market
  GET /events             — List events
  GET /events/:ticker     — Single event (with child markets)
  GET /series/:ticker     — Single series
  GET /markets/:ticker/orderbook — Orderbook snapshot
"""

from __future__ import annotations

from typing import Any

from app.kalshi.client import KalshiClient
from app.kalshi.models import (
    Event,
    Market,
    MarketStatus,
    Orderbook,
    Series,
)
from app.logging_config import get_logger

log = get_logger("kalshi.endpoints.markets")


class MarketsAPI:
    """Typed wrappers for market-related Kalshi endpoints."""

    def __init__(self, client: KalshiClient):
        self._client = client

    # ── Markets ───────────────────────────────────────────────────────────

    async def list_markets(
        self,
        *,
        limit: int = 200,
        cursor: str | None = None,
        event_ticker: str | None = None,
        series_ticker: str | None = None,
        status: MarketStatus | None = None,
        tickers: list[str] | None = None,
        category: str | None = None,
    ) -> tuple[list[Market], str | None]:
        """
        List markets with optional filters.

        Returns:
            (markets, next_cursor)
        """
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        if event_ticker:
            params["event_ticker"] = event_ticker
        if series_ticker:
            params["series_ticker"] = series_ticker
        if status:
            params["status"] = status.value
        if tickers:
            params["tickers"] = ",".join(tickers)
        if category:
            params["category"] = category

        resp = await self._client.get("/markets", params=params, authenticated=False)
        markets = [Market.model_validate(m) for m in resp.get("markets", [])]
        return markets, resp.get("cursor")

    async def get_all_markets(
        self,
        *,
        event_ticker: str | None = None,
        series_ticker: str | None = None,
        status: MarketStatus | None = None,
        category: str | None = None,
    ) -> list[Market]:
        """Fetch ALL markets across all pages."""
        params: dict[str, Any] = {}
        if event_ticker:
            params["event_ticker"] = event_ticker
        if series_ticker:
            params["series_ticker"] = series_ticker
        if status:
            # Kalshi API filter uses "open"/"closed"/"settled"
            # but MarketStatus.ACTIVE is a response-only alias for "open"
            api_val = status.value
            if api_val == "active":
                api_val = "open"
            params["status"] = api_val
        if category:
            params["category"] = category

        raw = await self._client.get_all_pages(
            "/markets",
            params=params,
            data_key="markets",
            authenticated=False,
        )
        return [Market.model_validate(m) for m in raw]

    async def get_market(self, ticker: str) -> Market:
        """Get a single market by ticker."""
        resp = await self._client.get(f"/markets/{ticker}", authenticated=False)
        return Market.model_validate(resp.get("market", resp))

    async def get_markets_by_tickers(self, tickers: list[str]) -> list[Market]:
        """
        Batch fetch multiple markets by ticker.
        Kalshi supports comma-separated tickers param.
        """
        if not tickers:
            return []
        # Kalshi limits to ~100 tickers per request
        all_markets: list[Market] = []
        for i in range(0, len(tickers), 100):
            batch = tickers[i : i + 100]
            markets, _ = await self.list_markets(tickers=batch, limit=len(batch))
            all_markets.extend(markets)
        return all_markets

    # ── Events ────────────────────────────────────────────────────────────

    async def list_events(
        self,
        *,
        limit: int = 200,
        cursor: str | None = None,
        series_ticker: str | None = None,
        status: MarketStatus | None = None,
        with_nested_markets: bool = False,
    ) -> tuple[list[Event], str | None]:
        """List events with optional filters."""
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        if series_ticker:
            params["series_ticker"] = series_ticker
        if status:
            params["status"] = status.value
        if with_nested_markets:
            params["with_nested_markets"] = "true"

        resp = await self._client.get("/events", params=params, authenticated=False)
        events = [Event.model_validate(e) for e in resp.get("events", [])]
        return events, resp.get("cursor")

    async def get_event(self, event_ticker: str, *, with_nested_markets: bool = True) -> Event:
        """Get a single event by ticker."""
        params: dict[str, Any] = {}
        if with_nested_markets:
            params["with_nested_markets"] = "true"
        resp = await self._client.get(
            f"/events/{event_ticker}", params=params, authenticated=False
        )
        return Event.model_validate(resp.get("event", resp))

    # ── Series ────────────────────────────────────────────────────────────

    async def get_series(self, series_ticker: str) -> Series:
        """Get a single series by ticker."""
        resp = await self._client.get(
            f"/series/{series_ticker}", authenticated=False
        )
        return Series.model_validate(resp.get("series", resp))

    # ── Orderbook ─────────────────────────────────────────────────────────

    async def get_orderbook(self, ticker: str, *, depth: int | None = None) -> Orderbook:
        """
        Get the orderbook snapshot for a market.

        Args:
            ticker: Market ticker
            depth: Number of levels to return (default: all)
        """
        params: dict[str, Any] = {}
        if depth is not None:
            params["depth"] = depth
        resp = await self._client.get(
            f"/markets/{ticker}/orderbook", params=params, authenticated=False
        )
        return Orderbook.model_validate(resp.get("orderbook", resp))

    # ── Utility ───────────────────────────────────────────────────────────

    async def search_markets(
        self,
        query: str,
        *,
        status: MarketStatus | None = None,
        limit: int = 50,
    ) -> list[Market]:
        """
        Search markets by text query.

        Note: Kalshi's search is via the /markets endpoint with a search param
        (not officially documented but works).
        """
        params: dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status.value

        # Kalshi doesn't have a formal search param in v2 —
        # fall back to client-side filter
        markets, _ = await self.list_markets(limit=limit, status=status)
        q_lower = query.lower()
        return [
            m
            for m in markets
            if (m.title and q_lower in m.title.lower())
            or (m.subtitle and q_lower in m.subtitle.lower())
            or q_lower in m.ticker.lower()
            or q_lower in m.event_ticker.lower()
        ]
