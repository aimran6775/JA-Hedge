"""
JA Hedge — Orders & Order Groups endpoints.

Covers:
  POST   /portfolio/orders                — Create order
  GET    /portfolio/orders                — List orders (paginated)
  GET    /portfolio/orders/:order_id      — Get single order
  DELETE /portfolio/orders/:order_id      — Cancel single order
  PATCH  /portfolio/orders/:order_id      — Amend order (price/count)
  POST   /portfolio/orders/batched        — Batch create orders
  DELETE /portfolio/orders                — Cancel all orders (for ticker)
  POST   /portfolio/order_groups          — Create order group
  GET    /portfolio/order_groups/:id      — Get order group
  DELETE /portfolio/order_groups/:id      — Cancel order group
"""

from __future__ import annotations

import uuid
from typing import Any

from app.kalshi.client import KalshiClient
from app.kalshi.models import (
    CreateOrderRequest,
    Order,
    OrderAction,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from app.logging_config import get_logger

log = get_logger("kalshi.endpoints.orders")


class OrdersAPI:
    """Typed wrappers for order-related Kalshi endpoints."""

    def __init__(self, client: KalshiClient):
        self._client = client

    # ── Create Order ──────────────────────────────────────────────────────

    async def create_order(self, order: CreateOrderRequest) -> Order:
        """
        Submit a new order to Kalshi.

        Automatically assigns a client_order_id if not provided.
        """
        payload = order.model_dump(exclude_none=True)
        if "client_order_id" not in payload:
            payload["client_order_id"] = str(uuid.uuid4())

        log.info(
            "order_submit",
            ticker=order.ticker,
            side=order.side.value,
            action=order.action.value,
            type=order.type.value,
            count=order.count,
            client_order_id=payload.get("client_order_id"),
        )

        resp = await self._client.post("/portfolio/orders", json=payload)
        return Order.model_validate(resp.get("order", resp))

    async def place_limit_order(
        self,
        ticker: str,
        side: OrderSide,
        action: OrderAction,
        *,
        count: int,
        yes_price_cents: int | None = None,
        no_price_cents: int | None = None,
        yes_price_dollars: str | None = None,
        no_price_dollars: str | None = None,
        time_in_force: TimeInForce = TimeInForce.GTC,
        buy_max_cost: int | None = None,
        client_order_id: str | None = None,
    ) -> Order:
        """Convenience method for placing a limit order."""
        order = CreateOrderRequest(
            ticker=ticker,
            side=side,
            action=action,
            type=OrderType.LIMIT,
            count=count,
            yes_price=yes_price_cents,
            no_price=no_price_cents,
            yes_price_dollars=yes_price_dollars,
            no_price_dollars=no_price_dollars,
            time_in_force=time_in_force,
            buy_max_cost=buy_max_cost,
            client_order_id=client_order_id or str(uuid.uuid4()),
        )
        return await self.create_order(order)

    async def place_market_order(
        self,
        ticker: str,
        side: OrderSide,
        action: OrderAction,
        *,
        count: int,
        buy_max_cost: int | None = None,
        client_order_id: str | None = None,
    ) -> Order:
        """Convenience method for placing a market order."""
        order = CreateOrderRequest(
            ticker=ticker,
            side=side,
            action=action,
            type=OrderType.MARKET,
            count=count,
            buy_max_cost=buy_max_cost,
            client_order_id=client_order_id or str(uuid.uuid4()),
        )
        return await self.create_order(order)

    # ── List / Get Orders ─────────────────────────────────────────────────

    async def list_orders(
        self,
        *,
        limit: int = 200,
        cursor: str | None = None,
        ticker: str | None = None,
        event_ticker: str | None = None,
        status: OrderStatus | None = None,
        min_ts: int | None = None,
        max_ts: int | None = None,
    ) -> tuple[list[Order], str | None]:
        """List orders with optional filters."""
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        if ticker:
            params["ticker"] = ticker
        if event_ticker:
            params["event_ticker"] = event_ticker
        if status:
            params["status"] = status.value
        if min_ts:
            params["min_ts"] = min_ts
        if max_ts:
            params["max_ts"] = max_ts

        resp = await self._client.get("/portfolio/orders", params=params)
        orders = [Order.model_validate(o) for o in resp.get("orders", [])]
        return orders, resp.get("cursor")

    async def get_all_orders(
        self,
        *,
        ticker: str | None = None,
        status: OrderStatus | None = None,
    ) -> list[Order]:
        """Fetch ALL orders across pages."""
        params: dict[str, Any] = {}
        if ticker:
            params["ticker"] = ticker
        if status:
            params["status"] = status.value

        raw = await self._client.get_all_pages(
            "/portfolio/orders",
            params=params,
            data_key="orders",
        )
        return [Order.model_validate(o) for o in raw]

    async def get_order(self, order_id: str) -> Order:
        """Get a single order by ID."""
        resp = await self._client.get(f"/portfolio/orders/{order_id}")
        return Order.model_validate(resp.get("order", resp))

    # ── Cancel Orders ─────────────────────────────────────────────────────

    async def cancel_order(self, order_id: str) -> dict[str, Any]:
        """Cancel a single order by ID."""
        log.info("order_cancel", order_id=order_id)
        return await self._client.delete(f"/portfolio/orders/{order_id}")

    async def cancel_all_orders(
        self,
        *,
        ticker: str | None = None,
        event_ticker: str | None = None,
    ) -> dict[str, Any]:
        """
        Cancel all resting orders, optionally filtered by ticker/event.

        Returns:
            Dict with cancelled order info from Kalshi
        """
        params: dict[str, Any] = {}
        if ticker:
            params["ticker"] = ticker
        if event_ticker:
            params["event_ticker"] = event_ticker

        log.warning("cancel_all_orders", ticker=ticker, event_ticker=event_ticker)
        return await self._client.delete("/portfolio/orders", params=params)

    # ── Amend Order ───────────────────────────────────────────────────────

    async def amend_order(
        self,
        order_id: str,
        *,
        count: int | None = None,
        yes_price: int | None = None,
        no_price: int | None = None,
        yes_price_dollars: str | None = None,
        no_price_dollars: str | None = None,
    ) -> Order:
        """
        Amend an existing resting order's price and/or count.

        Only provided fields are updated; omitted fields stay unchanged.
        """
        payload: dict[str, Any] = {}
        if count is not None:
            payload["count"] = count
        if yes_price is not None:
            payload["yes_price"] = yes_price
        if no_price is not None:
            payload["no_price"] = no_price
        if yes_price_dollars is not None:
            payload["yes_price_dollars"] = yes_price_dollars
        if no_price_dollars is not None:
            payload["no_price_dollars"] = no_price_dollars

        log.info("order_amend", order_id=order_id, changes=payload)
        resp = await self._client.put(
            f"/portfolio/orders/{order_id}", json=payload
        )
        return Order.model_validate(resp.get("order", resp))

    # ── Batch Orders ──────────────────────────────────────────────────────

    async def batch_create_orders(
        self, orders: list[CreateOrderRequest]
    ) -> list[Order]:
        """
        Create multiple orders in a single API call.

        Kalshi's batch endpoint processes up to 20 orders atomically.
        """
        if len(orders) > 20:
            raise ValueError("Kalshi batch limit is 20 orders per request")

        payloads = []
        for order in orders:
            payload = order.model_dump(exclude_none=True)
            if "client_order_id" not in payload:
                payload["client_order_id"] = str(uuid.uuid4())
            payloads.append(payload)

        log.info("batch_order_submit", count=len(payloads))
        resp = await self._client.post(
            "/portfolio/orders/batched",
            json={"orders": payloads},
        )
        return [
            Order.model_validate(o) for o in resp.get("orders", [])
        ]

    # ── Order Groups ──────────────────────────────────────────────────────

    async def create_order_group(
        self,
        *,
        order_group_type: str = "merge",
        orders: list[CreateOrderRequest],
    ) -> dict[str, Any]:
        """
        Create an order group (e.g., merge orders across markets in an event).

        Args:
            order_group_type: "merge" (only type supported currently)
            orders: Orders to include in the group
        """
        payloads = []
        for order in orders:
            payload = order.model_dump(exclude_none=True)
            if "client_order_id" not in payload:
                payload["client_order_id"] = str(uuid.uuid4())
            payloads.append(payload)

        resp = await self._client.post(
            "/portfolio/order_groups",
            json={
                "order_group_type": order_group_type,
                "orders": payloads,
            },
        )
        return resp

    async def get_order_group(self, order_group_id: str) -> dict[str, Any]:
        """Get an order group by ID."""
        return await self._client.get(
            f"/portfolio/order_groups/{order_group_id}"
        )

    async def cancel_order_group(self, order_group_id: str) -> dict[str, Any]:
        """Cancel an order group and all its constituent orders."""
        log.warning("cancel_order_group", order_group_id=order_group_id)
        return await self._client.delete(
            f"/portfolio/order_groups/{order_group_id}"
        )
