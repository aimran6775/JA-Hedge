"""
JA Hedge — Order API routes.

POST /api/orders          — Submit a manual order
DELETE /api/orders/:id    — Cancel an order
DELETE /api/orders        — Cancel all orders
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.kalshi.models import OrderAction, OrderSide, OrderType, TimeInForce
from app.state import state

router = APIRouter(prefix="/orders", tags=["Orders"])


class CreateOrderBody(BaseModel):
    ticker: str
    side: str  # "yes" | "no"
    action: str = "buy"  # "buy" | "sell"
    count: int = 1
    price_cents: int | None = None
    order_type: str = "limit"
    time_in_force: str = "good_till_canceled"
    buy_max_cost: int | None = None


class OrderResponse(BaseModel):
    success: bool
    order_id: str | None = None
    error: str | None = None
    latency_ms: float = 0


def _require_engine():
    if not state.execution_engine or not state.ready:
        raise HTTPException(503, detail="Execution engine not initialized")


@router.post("", response_model=OrderResponse)
async def create_order(body: CreateOrderBody) -> OrderResponse:
    """Submit a manual order via the execution engine."""
    _require_engine()

    side = OrderSide.YES if body.side.lower() == "yes" else OrderSide.NO
    action = OrderAction.BUY if body.action.lower() == "buy" else OrderAction.SELL
    order_type = OrderType.LIMIT if body.order_type.lower() == "limit" else OrderType.MARKET

    result = await state.execution_engine.execute(
        ticker=body.ticker,
        side=side,
        action=action,
        count=body.count,
        price_cents=body.price_cents,
        order_type=order_type,
        buy_max_cost=body.buy_max_cost,
    )

    return OrderResponse(
        success=result.success,
        order_id=result.order_id,
        error=result.error,
        latency_ms=result.latency_ms,
    )


@router.delete("/{order_id}")
async def cancel_order(order_id: str) -> dict:
    """Cancel a single order."""
    _require_engine()

    success = await state.execution_engine.cancel(order_id)
    return {
        "status": "cancelled" if success else "failed",
        "order_id": order_id,
    }


@router.delete("")
async def cancel_all_orders(ticker: str | None = None) -> dict:
    """Cancel all resting orders (optionally filtered by ticker)."""
    _require_engine()

    success = await state.execution_engine.cancel_all(ticker=ticker)
    return {"status": "ok" if success else "failed", "ticker": ticker}
