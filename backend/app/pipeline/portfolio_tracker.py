"""
JA Hedge — Portfolio Tracking Engine.

Real-time portfolio state management:
- Syncs positions with Kalshi API
- Computes P&L (realized + unrealized)
- Tracks daily performance metrics
- Persists to database for historical analytics
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_session_factory
from app.db.models import FillRecord, OrderRecord, PositionRecord
from app.kalshi.api import KalshiAPI
from app.kalshi.models import Fill, MarketPosition, Order
from app.kalshi.ws_client import KalshiWebSocket, WSChannel, WSMessage
from app.logging_config import get_logger
from app.pipeline import market_cache

log = get_logger("pipeline.portfolio")


class PortfolioState:
    """
    In-memory portfolio snapshot for fast access.

    Updated by sync loops and WebSocket fill/order events.
    """

    def __init__(self) -> None:
        self.balance_cents: int = 0
        self.balance_dollars: str = "0.00"
        self.positions: dict[str, MarketPosition] = {}
        self.open_orders: dict[str, Order] = {}
        self.daily_pnl: Decimal = Decimal("0")
        self.daily_trades: int = 0
        self.daily_fees: Decimal = Decimal("0")
        self._last_sync: float = 0

    @property
    def total_exposure(self) -> Decimal:
        """Sum of absolute market exposure across all positions."""
        total = Decimal("0")
        for p in self.positions.values():
            if p.market_exposure_dollars:
                total += abs(Decimal(p.market_exposure_dollars))
        return total

    @property
    def position_count(self) -> int:
        return len(self.positions)

    @property
    def open_order_count(self) -> int:
        return len(self.open_orders)

    @property
    def last_sync(self) -> float:
        return self._last_sync


# Global portfolio state singleton
portfolio_state = PortfolioState()


class PortfolioTracker:
    """
    Manages portfolio state sync with Kalshi.

    1. Periodic sync: Pulls balance, positions, open orders
    2. Real-time: WebSocket fill/order updates
    3. Persistence: Stores fills/orders/positions in DB
    """

    def __init__(
        self,
        api: KalshiAPI,
        ws: KalshiWebSocket | None = None,
        *,
        sync_interval: float = 10.0,
    ):
        self._api = api
        self._ws = ws
        self._sync_interval = sync_interval
        self._running = False
        self._sync_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the portfolio tracker."""
        self._running = True

        # Initial full sync
        await self._full_sync()

        # Start periodic sync
        self._sync_task = asyncio.create_task(
            self._sync_loop(), name="portfolio_sync"
        )

        # Setup WebSocket handlers
        if self._ws:
            self._ws.on(WSChannel.FILL)(self._on_fill)
            self._ws.on(WSChannel.ORDER_UPDATE)(self._on_order_update)

        log.info(
            "portfolio_tracker_started",
            balance=portfolio_state.balance_dollars,
            positions=portfolio_state.position_count,
            open_orders=portfolio_state.open_order_count,
        )

    async def stop(self) -> None:
        """Stop the tracker gracefully."""
        self._running = False
        if self._sync_task and not self._sync_task.done():
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass
        log.info("portfolio_tracker_stopped")

    async def _full_sync(self) -> None:
        """Pull full portfolio state from Kalshi API."""
        try:
            # Balance
            balance = await self._api.portfolio.get_balance()
            portfolio_state.balance_cents = balance.balance or 0
            portfolio_state.balance_dollars = balance.balance_dollars or "0.00"

            # Positions
            positions = await self._api.portfolio.get_all_positions(
                settlement_status="unsettled",
                count_filter="non_zero",
            )
            portfolio_state.positions = {p.ticker: p for p in positions}

            # Persist positions to DB
            await self._persist_positions(positions)

            portfolio_state._last_sync = time.time()
            log.info(
                "portfolio_synced",
                balance=portfolio_state.balance_dollars,
                positions=len(positions),
            )
        except Exception as e:
            log.error("portfolio_sync_failed", error=str(e))

    async def _sync_loop(self) -> None:
        """Periodic portfolio sync."""
        try:
            while self._running:
                await asyncio.sleep(self._sync_interval)
                await self._full_sync()
        except asyncio.CancelledError:
            return

    async def _on_fill(self, msg: WSMessage) -> None:
        """Handle real-time fill from WebSocket."""
        data = msg.data
        log.info("ws_fill_received", data=data)

        # Persist fill to DB
        try:
            await self._persist_fill(data)
        except Exception as e:
            log.error("fill_persist_failed", error=str(e))

        # Update daily stats
        portfolio_state.daily_trades += 1
        if data.get("fee_cost_dollars"):
            portfolio_state.daily_fees += Decimal(data["fee_cost_dollars"])

        # Trigger a position refresh for this ticker
        ticker = data.get("ticker")
        if ticker:
            try:
                pos = await self._api.portfolio.get_position(ticker)
                portfolio_state.positions[ticker] = pos
            except Exception:
                pass

    async def _on_order_update(self, msg: WSMessage) -> None:
        """Handle real-time order status update from WebSocket."""
        data = msg.data
        order_id = data.get("order_id")
        status = data.get("status")

        if not order_id:
            return

        log.info("ws_order_update", order_id=order_id, status=status)

        # Remove from open orders if terminal
        if status in ("executed", "canceled"):
            portfolio_state.open_orders.pop(order_id, None)

    async def _persist_positions(self, positions: list[MarketPosition]) -> None:
        """Upsert positions to database."""
        if not positions:
            return

        try:
            factory = get_session_factory()
            async with factory() as session:
                for p in positions:
                    # Compute unrealized P&L from market cache
                    unrealized = Decimal("0")
                    market = market_cache.get(p.ticker)
                    if market and market.last_price and p.position:
                        # Simplified unrealized: (current_price - avg_entry) * position
                        unrealized = Decimal("0")  # Computed properly in Phase 9

                    stmt = pg_insert(PositionRecord).values(
                        ticker=p.ticker,
                        net_contracts=p.position or 0,
                        realized_pnl=Decimal(p.realized_pnl_dollars) if p.realized_pnl_dollars else Decimal("0"),
                        total_fees=Decimal(p.fees_paid_dollars) if p.fees_paid_dollars else Decimal("0"),
                        market_exposure=Decimal(p.market_exposure_dollars) if p.market_exposure_dollars else Decimal("0"),
                        unrealized_pnl=unrealized,
                    ).on_conflict_do_update(
                        index_elements=["ticker"],
                        set_={
                            "net_contracts": p.position or 0,
                            "realized_pnl": Decimal(p.realized_pnl_dollars) if p.realized_pnl_dollars else Decimal("0"),
                            "total_fees": Decimal(p.fees_paid_dollars) if p.fees_paid_dollars else Decimal("0"),
                            "market_exposure": Decimal(p.market_exposure_dollars) if p.market_exposure_dollars else Decimal("0"),
                        },
                    )
                    await session.execute(stmt)
                await session.commit()
        except Exception as e:
            log.error("positions_persist_failed", error=str(e))

    async def _persist_fill(self, data: dict[str, Any]) -> None:
        """Persist a single fill to the database."""
        try:
            factory = get_session_factory()
            async with factory() as session:
                fill = FillRecord(
                    fill_id=data.get("fill_id"),
                    order_id=data.get("order_id", ""),
                    ticker=data.get("ticker", ""),
                    side=data.get("side", ""),
                    action=data.get("action", ""),
                    count=data.get("count"),
                    yes_price_cents=data.get("yes_price"),
                    no_price_cents=data.get("no_price"),
                    yes_price_dollars=data.get("yes_price_dollars"),
                    no_price_dollars=data.get("no_price_dollars"),
                    is_taker=data.get("is_taker"),
                    fee_cost_dollars=data.get("fee_cost_dollars"),
                )
                session.add(fill)
                await session.commit()
        except Exception as e:
            log.error("fill_db_failed", error=str(e))
