"""
JA Hedge — Order Execution Engine.

Smart order routing with:
- Pre-trade risk checks (via RiskManager)
- Optimal order placement (limit vs market, price improvement)
- Position tracking on fill
- Execution audit trail
- Cancel/amend support
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.db.engine import get_session_factory
from app.db.models import OrderRecord
from app.kalshi.api import KalshiAPI
from app.kalshi.models import (
    CreateOrderRequest,
    Order,
    OrderAction,
    OrderSide,
    OrderType,
    TimeInForce,
)
from app.logging_config import get_logger
from app.pipeline import market_cache
from app.pipeline.portfolio_tracker import portfolio_state

log = get_logger("engine.execution")


@dataclass
class ExecutionResult:
    """Result of an order execution attempt."""

    success: bool
    order: Order | None = None
    order_id: str | None = None
    client_order_id: str | None = None
    error: str | None = None
    latency_ms: float = 0
    risk_check_passed: bool = True
    risk_rejection_reason: str | None = None


@dataclass
class ExecutionStats:
    """Running execution statistics."""

    total_orders: int = 0
    successful_orders: int = 0
    failed_orders: int = 0
    total_latency_ms: float = 0
    avg_latency_ms: float = 0
    risk_rejections: int = 0


class ExecutionEngine:
    """
    Handles all order submission to Kalshi.

    All orders flow through here for:
    1. Risk pre-checks
    2. Optimal pricing
    3. Submission
    4. Audit logging
    """

    def __init__(
        self,
        api: KalshiAPI,
        risk_manager: Any = None,  # Type: RiskManager (circular import avoidance)
    ):
        self._api = api
        self._risk_manager = risk_manager
        self._stats = ExecutionStats()
        self._enabled = True

    @property
    def stats(self) -> ExecutionStats:
        return self._stats

    @property
    def enabled(self) -> bool:
        return self._enabled

    def enable(self) -> None:
        self._enabled = True
        log.info("execution_engine_enabled")

    def disable(self) -> None:
        self._enabled = False
        log.warning("execution_engine_disabled")

    async def execute(
        self,
        ticker: str,
        side: OrderSide,
        action: OrderAction,
        count: int,
        *,
        price_cents: int | None = None,
        order_type: OrderType = OrderType.LIMIT,
        time_in_force: TimeInForce = TimeInForce.GTC,
        buy_max_cost: int | None = None,
        strategy_id: str | None = None,
        signal_id: int | None = None,
    ) -> ExecutionResult:
        """
        Execute an order with full risk checks and audit trail.

        Args:
            ticker: Market ticker
            side: YES or NO
            action: BUY or SELL
            count: Number of contracts
            price_cents: Limit price in cents (required for limit orders)
            order_type: LIMIT or MARKET
            time_in_force: GTC, FOK, or IOC
            buy_max_cost: Safety cap on total cost (cents)
            strategy_id: Link to strategy config
            signal_id: Link to AI signal
        """
        start = time.monotonic()
        client_order_id = str(uuid.uuid4())

        # Check if engine is enabled
        if not self._enabled:
            return ExecutionResult(
                success=False,
                client_order_id=client_order_id,
                error="Execution engine is disabled",
            )

        # ── Pre-trade Risk Checks ─────────────────────────
        if self._risk_manager:
            risk_ok, risk_reason = await self._risk_manager.pre_trade_check(
                ticker=ticker,
                side=side,
                action=action,
                count=count,
                price_cents=price_cents,
            )
            if not risk_ok:
                self._stats.risk_rejections += 1
                log.warning(
                    "order_risk_rejected",
                    ticker=ticker,
                    reason=risk_reason,
                )
                return ExecutionResult(
                    success=False,
                    client_order_id=client_order_id,
                    risk_check_passed=False,
                    risk_rejection_reason=risk_reason,
                )

        # ── Build Order ───────────────────────────────────
        order_req = CreateOrderRequest(
            ticker=ticker,
            side=side,
            action=action,
            type=order_type,
            count=count,
            client_order_id=client_order_id,
            time_in_force=time_in_force,
        )

        # Set price based on side
        if price_cents is not None:
            if side == OrderSide.YES:
                order_req.yes_price = price_cents
            else:
                order_req.no_price = price_cents

        if buy_max_cost is not None:
            order_req.buy_max_cost = buy_max_cost

        # ── Submit Order ──────────────────────────────────
        try:
            order = await self._api.orders.create_order(order_req)
            latency = (time.monotonic() - start) * 1000

            self._stats.total_orders += 1
            self._stats.successful_orders += 1
            self._stats.total_latency_ms += latency
            self._stats.avg_latency_ms = (
                self._stats.total_latency_ms / self._stats.total_orders
            )

            log.info(
                "order_executed",
                ticker=ticker,
                side=side.value,
                action=action.value,
                count=count,
                order_id=order.order_id,
                latency_ms=round(latency, 2),
            )

            # Persist to DB
            await self._persist_order(
                order, strategy_id=strategy_id, signal_id=signal_id
            )

            # Update portfolio state
            portfolio_state.open_orders[order.order_id] = order

            return ExecutionResult(
                success=True,
                order=order,
                order_id=order.order_id,
                client_order_id=client_order_id,
                latency_ms=latency,
            )

        except Exception as e:
            latency = (time.monotonic() - start) * 1000
            self._stats.total_orders += 1
            self._stats.failed_orders += 1

            log.error(
                "order_failed",
                ticker=ticker,
                error=str(e),
                latency_ms=round(latency, 2),
            )

            return ExecutionResult(
                success=False,
                client_order_id=client_order_id,
                error=str(e),
                latency_ms=latency,
            )

    async def cancel(self, order_id: str) -> bool:
        """Cancel a single order."""
        try:
            await self._api.orders.cancel_order(order_id)
            portfolio_state.open_orders.pop(order_id, None)
            log.info("order_cancelled", order_id=order_id)
            return True
        except Exception as e:
            log.error("cancel_failed", order_id=order_id, error=str(e))
            return False

    async def cancel_all(self, *, ticker: str | None = None) -> bool:
        """Cancel all resting orders."""
        try:
            await self._api.orders.cancel_all_orders(ticker=ticker)
            if ticker:
                portfolio_state.open_orders = {
                    k: v
                    for k, v in portfolio_state.open_orders.items()
                    if v.ticker != ticker
                }
            else:
                portfolio_state.open_orders.clear()
            log.warning("all_orders_cancelled", ticker=ticker)
            return True
        except Exception as e:
            log.error("cancel_all_failed", error=str(e))
            return False

    async def _persist_order(
        self,
        order: Order,
        *,
        strategy_id: str | None = None,
        signal_id: int | None = None,
    ) -> None:
        """Save order to database for audit trail."""
        try:
            factory = get_session_factory()
            async with factory() as session:
                record = OrderRecord(
                    order_id=order.order_id,
                    client_order_id=order.client_order_id,
                    ticker=order.ticker,
                    side=order.side.value,
                    action=order.action.value,
                    order_type=order.type.value,
                    status=order.status.value,
                    yes_price_cents=order.yes_price,
                    no_price_cents=order.no_price,
                    yes_price_dollars=order.yes_price_dollars,
                    no_price_dollars=order.no_price_dollars,
                    count=order.count,
                    remaining_count=order.remaining_count,
                    fill_count=order.fill_count,
                    strategy_id=strategy_id,
                    signal_id=signal_id,
                )
                session.add(record)
                await session.commit()
        except Exception as e:
            log.error("order_persist_failed", error=str(e))
