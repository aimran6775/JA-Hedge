"""
JA Hedge — Portfolio endpoints.

Covers:
  GET  /portfolio/balance         — Account balance
  GET  /portfolio/positions       — All market positions (paginated)
  GET  /portfolio/positions/:ticker — Single market position
  GET  /portfolio/events/:ticker/positions — Event-level position
  GET  /portfolio/settlements     — Settlement history (paginated)
  GET  /portfolio/fills           — Fill history (paginated)
"""

from __future__ import annotations

from typing import Any

from app.kalshi.client import KalshiClient
from app.kalshi.models import (
    Balance,
    EventPosition,
    Fill,
    MarketPosition,
    Settlement,
)
from app.logging_config import get_logger

log = get_logger("kalshi.endpoints.portfolio")


class PortfolioAPI:
    """Typed wrappers for portfolio-related Kalshi endpoints."""

    def __init__(self, client: KalshiClient):
        self._client = client

    # ── Balance ───────────────────────────────────────────────────────────

    async def get_balance(self) -> Balance:
        """Get current account balance."""
        resp = await self._client.get("/portfolio/balance")
        return Balance.model_validate(resp)

    # ── Market Positions ──────────────────────────────────────────────────

    async def list_positions(
        self,
        *,
        limit: int = 200,
        cursor: str | None = None,
        settlement_status: str | None = None,
        ticker: str | None = None,
        event_ticker: str | None = None,
        count_filter: str | None = None,
    ) -> tuple[list[MarketPosition], str | None]:
        """
        List all market positions.

        Args:
            settlement_status: "unsettled" | "settled" | "all"
            count_filter: "non_zero" | "has_yes" | "has_no" | "all"
        """
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        if settlement_status:
            params["settlement_status"] = settlement_status
        if ticker:
            params["ticker"] = ticker
        if event_ticker:
            params["event_ticker"] = event_ticker
        if count_filter:
            params["count_filter"] = count_filter

        resp = await self._client.get("/portfolio/positions", params=params)
        positions = [
            MarketPosition.model_validate(p)
            for p in resp.get("market_positions", [])
        ]
        return positions, resp.get("cursor")

    async def get_all_positions(
        self,
        *,
        settlement_status: str = "unsettled",
        count_filter: str = "non_zero",
    ) -> list[MarketPosition]:
        """Fetch ALL positions across pages."""
        params: dict[str, Any] = {
            "settlement_status": settlement_status,
            "count_filter": count_filter,
        }
        raw = await self._client.get_all_pages(
            "/portfolio/positions",
            params=params,
            data_key="market_positions",
        )
        return [MarketPosition.model_validate(p) for p in raw]

    async def get_position(self, ticker: str) -> MarketPosition:
        """Get position for a single market."""
        resp = await self._client.get(f"/portfolio/positions/{ticker}")
        return MarketPosition.model_validate(
            resp.get("market_position", resp)
        )

    # ── Event Positions ───────────────────────────────────────────────────

    async def get_event_position(self, event_ticker: str) -> EventPosition:
        """Get aggregate position for an event."""
        resp = await self._client.get(
            f"/portfolio/events/{event_ticker}/positions"
        )
        return EventPosition.model_validate(
            resp.get("event_position", resp)
        )

    # ── Fills ─────────────────────────────────────────────────────────────

    async def list_fills(
        self,
        *,
        limit: int = 200,
        cursor: str | None = None,
        ticker: str | None = None,
        order_id: str | None = None,
        min_ts: int | None = None,
        max_ts: int | None = None,
    ) -> tuple[list[Fill], str | None]:
        """List trade fills with filters."""
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        if ticker:
            params["ticker"] = ticker
        if order_id:
            params["order_id"] = order_id
        if min_ts:
            params["min_ts"] = min_ts
        if max_ts:
            params["max_ts"] = max_ts

        resp = await self._client.get("/portfolio/fills", params=params)
        fills = [Fill.model_validate(f) for f in resp.get("fills", [])]
        return fills, resp.get("cursor")

    async def get_all_fills(
        self,
        *,
        ticker: str | None = None,
        min_ts: int | None = None,
        max_ts: int | None = None,
    ) -> list[Fill]:
        """Fetch ALL fills across pages."""
        params: dict[str, Any] = {}
        if ticker:
            params["ticker"] = ticker
        if min_ts:
            params["min_ts"] = min_ts
        if max_ts:
            params["max_ts"] = max_ts

        raw = await self._client.get_all_pages(
            "/portfolio/fills",
            params=params,
            data_key="fills",
        )
        return [Fill.model_validate(f) for f in raw]

    # ── Settlements ───────────────────────────────────────────────────────

    async def list_settlements(
        self,
        *,
        limit: int = 200,
        cursor: str | None = None,
        ticker: str | None = None,
        min_ts: int | None = None,
        max_ts: int | None = None,
    ) -> tuple[list[Settlement], str | None]:
        """List settlement records."""
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        if ticker:
            params["ticker"] = ticker
        if min_ts:
            params["min_ts"] = min_ts
        if max_ts:
            params["max_ts"] = max_ts

        resp = await self._client.get("/portfolio/settlements", params=params)
        settlements = [
            Settlement.model_validate(s)
            for s in resp.get("settlements", [])
        ]
        return settlements, resp.get("cursor")

    async def get_all_settlements(
        self,
        *,
        ticker: str | None = None,
    ) -> list[Settlement]:
        """Fetch ALL settlements across pages."""
        params: dict[str, Any] = {}
        if ticker:
            params["ticker"] = ticker

        raw = await self._client.get_all_pages(
            "/portfolio/settlements",
            params=params,
            data_key="settlements",
        )
        return [Settlement.model_validate(s) for s in raw]
