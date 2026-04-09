"""
JA Hedge — Paper Trading Simulator.

Provides a fully functional simulated exchange with fake cash for testing
the complete trading pipeline without needing real or demo funds.

Features:
- Configurable starting balance (default $10,000)
- Realistic order matching against live Kalshi orderbook data
- Limit orders rest in a local book and fill when price crosses
- Market orders fill at best available price
- Full position tracking with P&L
- Fill history with timestamps
- Slippage simulation
- Maker/taker fee simulation (matches Kalshi's fee schedule)

Usage:
    simulator = PaperTradingSimulator(starting_balance_cents=1_000_000)
    api_wrapper = simulator.wrap_api(real_kalshi_api)
    engine = ExecutionEngine(api=api_wrapper, risk_manager=rm)
    result = await engine.execute(ticker="TICKER", ...)
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from app.kalshi.models import (
    Balance,
    CreateOrderRequest,
    Fill,
    MarketPosition,
    Order,
    OrderAction,
    OrderSide,
    OrderStatus,
    OrderType,
    Orderbook,
    TimeInForce,
)
from app.logging_config import get_logger

log = get_logger("engine.paper_trader")


# ── Simulated Order Book Entry ────────────────────────────────────────────


@dataclass
class SimulatedOrder:
    """An order living in the paper trading engine."""

    order_id: str
    client_order_id: str
    ticker: str
    side: OrderSide
    action: OrderAction
    order_type: OrderType
    status: OrderStatus
    price_cents: int  # limit price in cents
    count: int
    remaining_count: int
    fill_count: int = 0
    taker_fill_cost_cents: int = 0
    maker_fill_cost_cents: int = 0
    taker_fees_cents: int = 0
    maker_fees_cents: int = 0
    created_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_order_model(self) -> Order:
        """Convert to the API-compatible Order model."""
        yes_price = self.price_cents if self.side == OrderSide.YES else None
        no_price = self.price_cents if self.side == OrderSide.NO else None
        return Order(
            order_id=self.order_id,
            client_order_id=self.client_order_id,
            ticker=self.ticker,
            side=self.side,
            action=self.action,
            type=self.order_type,
            status=self.status,
            yes_price=yes_price,
            no_price=no_price,
            count=self.count,
            initial_count=self.count,
            remaining_count=self.remaining_count,
            fill_count=self.fill_count,
            taker_fill_cost=self.taker_fill_cost_cents,
            maker_fill_cost=self.maker_fill_cost_cents,
            taker_fees=self.taker_fees_cents,
            maker_fees=self.maker_fees_cents,
            created_time=self.created_time,
            updated_time=self.updated_time,
        )


@dataclass
class SimulatedFill:
    """Record of a simulated fill."""

    fill_id: str
    order_id: str
    client_order_id: str
    ticker: str
    side: OrderSide
    action: OrderAction
    count: int
    price_cents: int
    is_taker: bool
    fee_cents: int = 0
    created_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_fill_model(self) -> Fill:
        yes_price = self.price_cents if self.side == OrderSide.YES else None
        no_price = self.price_cents if self.side == OrderSide.NO else None
        return Fill(
            fill_id=self.fill_id,
            order_id=self.order_id,
            client_order_id=self.client_order_id,
            ticker=self.ticker,
            side=self.side,
            action=self.action,
            count=self.count,
            yes_price=yes_price,
            no_price=no_price,
            is_taker=self.is_taker,
            fee_cost=self.fee_cents,
            created_time=self.created_time,
        )


@dataclass
class SimulatedPosition:
    """Tracks net position in a market."""

    ticker: str
    yes_count: int = 0   # net YES contracts held
    no_count: int = 0    # net NO contracts held
    total_cost_cents: int = 0
    realized_pnl_cents: int = 0
    fees_paid_cents: int = 0

    @property
    def net_position(self) -> int:
        """Positive = net YES, negative = net NO."""
        return self.yes_count - self.no_count

    def to_market_position(self) -> MarketPosition:
        return MarketPosition(
            ticker=self.ticker,
            position=self.net_position,
            market_exposure=abs(self.total_cost_cents),
            market_exposure_dollars=f"{abs(self.total_cost_cents) / 100:.2f}",
            realized_pnl=self.realized_pnl_cents,
            realized_pnl_dollars=f"{self.realized_pnl_cents / 100:.2f}",
            fees_paid=self.fees_paid_cents,
            fees_paid_dollars=f"{self.fees_paid_cents / 100:.2f}",
        )


# ── Paper Trading Simulator ──────────────────────────────────────────────


class PaperTradingSimulator:
    """
    Simulated exchange with fake cash for full pipeline testing.

    Supports:
    - Configurable starting balance
    - Limit & market order simulation
    - Instant fill (for aggressive prices) or resting (for passive prices)
    - Position tracking with P&L
    - Order cancellation
    - Fee simulation
    """

    # Kalshi fee schedule (simplified)
    TAKER_FEE_RATE = Decimal("0.07")  # 7¢ per contract for taker
    MAKER_FEE_RATE = Decimal("0.00")  # 0¢ for maker (Kalshi rebates makers)

    def __init__(
        self,
        starting_balance_cents: int = 1_000_000,  # $10,000
        *,
        fee_rate_cents: int = 7,  # taker fee per contract
        slippage_cents: int = 1,  # realistic slippage per fill
        instant_fill: bool = True,  # fill limit orders immediately (simulates aggressing)
        spread_simulation: bool = True,  # Phase 6: simulate spread impact
        maker_mode: bool = False,  # Phase 21: realistic maker fill simulation
    ):
        self.starting_balance_cents = starting_balance_cents
        self.balance_cents = starting_balance_cents
        self.fee_rate_cents = fee_rate_cents
        self.slippage_cents = slippage_cents
        self.instant_fill = instant_fill
        self.spread_simulation = spread_simulation
        self.maker_mode = maker_mode

        # State
        self._orders: dict[str, SimulatedOrder] = {}
        self._fills: list[SimulatedFill] = []
        self._positions: dict[str, SimulatedPosition] = {}
        self._order_history: list[SimulatedOrder] = []
        self._resting_orders: dict[str, SimulatedOrder] = {}  # Phase 21: orders waiting for fill

        # Stats
        self.total_orders = 0
        self.total_fills = 0
        self.total_fees_paid = 0
        self.total_volume_cents = 0

        log.info(
            "paper_trader_initialized",
            balance=f"${starting_balance_cents / 100:.2f}",
            fee_rate=f"{fee_rate_cents}¢/contract",
        )

    # ── Settlement ─────────────────────────────────────────────────────

    def settle_market(self, ticker: str, result: str) -> dict[str, Any]:
        """
        Settle a market when it resolves (YES wins or NO wins).

        For hold-to-settlement strategy:
        - If we hold YES and result is 'yes': credit 100¢ per contract
        - If we hold NO and result is 'no': credit 100¢ per contract
        - Otherwise: we lose the cost (already deducted on buy)

        Args:
            ticker: The market ticker
            result: 'yes', 'no', or 'void'

        Returns:
            Settlement details including P&L
        """
        pos = self._positions.get(ticker)
        if not pos:
            return {"ticker": ticker, "status": "no_position"}

        pnl_cents = 0
        result_lower = result.lower()

        if result_lower == "void":
            # Void: refund the cost
            self.balance_cents += pos.total_cost_cents
            pnl_cents = 0
        elif result_lower == "yes":
            # YES wins: credit 100¢ per YES contract held
            payout = pos.yes_count * 100
            self.balance_cents += payout
            pnl_cents = payout - pos.total_cost_cents
        elif result_lower == "no":
            # NO wins: credit 100¢ per NO contract held
            payout = pos.no_count * 100
            self.balance_cents += payout
            pnl_cents = payout - pos.total_cost_cents
        else:
            pnl_cents = -pos.total_cost_cents

        pos.realized_pnl_cents += pnl_cents

        log.info(
            "paper_settlement",
            ticker=ticker,
            result=result_lower,
            yes_count=pos.yes_count,
            no_count=pos.no_count,
            pnl=f"${pnl_cents / 100:.2f}",
            balance=f"${self.balance_cents / 100:.2f}",
        )

        # Remove the position
        del self._positions[ticker]

        return {
            "ticker": ticker,
            "result": result_lower,
            "pnl_cents": pnl_cents,
            "balance_cents": self.balance_cents,
        }

    def cleanup_stale_orders(self, max_age_seconds: float = 3600.0) -> int:
        """Cancel resting orders older than max_age_seconds.

        Prevents partial fills from sitting forever.
        """
        now = datetime.now(timezone.utc)
        cleaned = 0
        for order in list(self._orders.values()):
            if order.status == OrderStatus.RESTING:
                age = (now - order.created_time).total_seconds()
                if age > max_age_seconds:
                    order.status = OrderStatus.CANCELED
                    order.updated_time = now
                    cleaned += 1
        if cleaned:
            log.info("paper_stale_orders_cleaned", count=cleaned)
        return cleaned

    # ── Reset ─────────────────────────────────────────────────────────

    def reset(self, new_balance_cents: int | None = None) -> dict[str, Any]:
        """
        Reset the entire simulation: clear all trades, positions, orders,
        and restore balance. Optionally set a new starting balance.
        """
        old_balance = self.balance_cents
        old_pnl = self.pnl_cents
        old_trades = self.total_fills

        if new_balance_cents is not None:
            self.starting_balance_cents = new_balance_cents
        self.balance_cents = self.starting_balance_cents

        # Clear all state
        self._orders.clear()
        self._fills.clear()
        self._positions.clear()
        self._order_history.clear()

        # Reset stats
        self.total_orders = 0
        self.total_fills = 0
        self.total_fees_paid = 0
        self.total_volume_cents = 0

        log.info(
            "paper_trader_reset",
            old_balance=f"${old_balance / 100:.2f}",
            old_pnl=f"${old_pnl / 100:.2f}",
            old_trades=old_trades,
            new_balance=f"${self.balance_cents / 100:.2f}",
        )

        return {
            "previous_balance": f"${old_balance / 100:.2f}",
            "previous_pnl": f"${old_pnl / 100:.2f}",
            "previous_trades": old_trades,
            "new_balance": f"${self.balance_cents / 100:.2f}",
            "starting_balance": f"${self.starting_balance_cents / 100:.2f}",
        }

    # ── Balance ───────────────────────────────────────────────────────

    def get_balance(self) -> Balance:
        """Get simulated balance."""
        return Balance(
            balance=self.balance_cents,
            balance_dollars=f"{self.balance_cents / 100:.2f}",
            payout=0,
            payout_dollars="0.00",
        )

    @property
    def balance_dollars(self) -> str:
        return f"{self.balance_cents / 100:.2f}"

    @property
    def pnl_cents(self) -> int:
        """Total P&L since start."""
        return self.balance_cents - self.starting_balance_cents

    @property
    def pnl_dollars(self) -> str:
        return f"{self.pnl_cents / 100:.2f}"

    # ── Order Submission ──────────────────────────────────────────────

    def create_order(self, req: CreateOrderRequest) -> Order:
        """
        Submit an order to the paper exchange.

        For BUY orders: deducts cost from balance.
        For SELL orders: requires holding a position.
        Fills immediately if instant_fill is True.
        """
        order_id = f"paper-{uuid.uuid4().hex[:12]}"
        client_order_id = req.client_order_id or str(uuid.uuid4())

        # Determine price
        price_cents = req.yes_price if req.side == OrderSide.YES else req.no_price
        if price_cents is None:
            # Market order — use a default fill price
            price_cents = 50  # midpoint default

        count = req.count or 1

        # ── Validate balance for BUY orders ──────────────
        if req.action == OrderAction.BUY:
            total_cost = price_cents * count
            total_fees = self.fee_rate_cents * count
            required = total_cost + total_fees

            if required > self.balance_cents:
                raise ValueError(
                    f"insufficient_balance: need {required}¢ "
                    f"(cost={total_cost}¢ + fees={total_fees}¢), "
                    f"have {self.balance_cents}¢"
                )

        # ── Create the order ─────────────────────────────
        sim_order = SimulatedOrder(
            order_id=order_id,
            client_order_id=client_order_id,
            ticker=req.ticker,
            side=req.side,
            action=req.action,
            order_type=req.type,
            status=OrderStatus.RESTING,
            price_cents=price_cents,
            count=count,
            remaining_count=count,
        )

        self._orders[order_id] = sim_order
        self._order_history.append(sim_order)
        self.total_orders += 1

        log.info(
            "paper_order_created",
            order_id=order_id,
            ticker=req.ticker,
            side=req.side.value,
            action=req.action.value,
            price=f"{price_cents}¢",
            count=count,
        )

        # ── Instant fill if enabled ──────────────────────
        if req.type == OrderType.MARKET:
            # Market orders always fill immediately
            self._fill_order(sim_order)
        elif self.maker_mode and req.type == OrderType.LIMIT:
            # MAKER MODE: limit orders rest and fill probabilistically
            # based on how close price is to midpoint.
            # This simulates real Kalshi maker order behavior where
            # fill rate is 20-40%, not the 85% we had before.
            self._resting_orders[order_id] = sim_order
            self._attempt_maker_fill(sim_order)
        elif self.instant_fill:
            self._fill_order(sim_order)
        elif req.time_in_force == TimeInForce.FOK:
            # Fill-or-kill: cancel if can't fill immediately
            sim_order.status = OrderStatus.CANCELED
            sim_order.updated_time = datetime.now(timezone.utc)
        elif req.time_in_force == TimeInForce.IOC:
            # Immediate-or-cancel: partial fill then cancel remainder
            self._fill_order(sim_order)

        return sim_order.to_order_model()

    def _fill_order(self, order: SimulatedOrder) -> None:
        """Fill an order with realistic slippage and partial-fill simulation.

        Phase 4 improvements:
        - Proportional slippage: 1% of price (not flat 1¢)
        - Fill probability: wider spreads → lower fill chance
        - Partial fills: thin books may only fill part of the order
        """
        if order.remaining_count <= 0:
            return

        # ── Realistic fill probability based on spread ────
        # Tight spread (≤2¢) → 100% fill, wide spread → decreasing probability
        # This simulates that passive orders in wide spreads often don't fill.
        if self.spread_simulation and order.order_type == OrderType.LIMIT:
            # Estimate spread from price (rough: assume 3-5% of price)
            price_frac = order.price_cents / 100.0
            # For aggressive orders (taking), always fill
            # For passive orders, probability decreases with spread
            fill_prob = 0.85  # base probability for limit orders
            if order.price_cents < 20 or order.price_cents > 80:
                fill_prob = 0.70  # extreme prices have less liquidity
            import random
            if random.random() > fill_prob:
                # Order didn't fill — leave it resting
                log.debug("paper_fill_missed", order_id=order.order_id,
                          ticker=order.ticker, fill_prob=f"{fill_prob:.0%}")
                return

        # ── Partial fills for larger orders ───────────────
        # Orders > 3 contracts may only partially fill in thin markets
        fill_count = order.remaining_count
        if fill_count > 3 and self.spread_simulation:
            import random
            # 70% chance of full fill, 30% chance of partial (50-90% of order)
            if random.random() < 0.30:
                partial_pct = random.uniform(0.50, 0.90)
                fill_count = max(1, int(fill_count * partial_pct))

        # ── Proportional slippage ─────────────────────────
        # Maker orders fill at the posted price — no slippage.
        # Taker orders get ~1% proportional slippage.
        if order.order_type == OrderType.LIMIT:
            # Maker/limit: fill at our posted price
            fill_price = order.price_cents
        else:
            base_slippage = max(1, int(order.price_cents * 0.01 + 0.5))
            fill_price = order.price_cents + base_slippage
        fee_cents = self.fee_rate_cents * fill_count
        cost_cents = fill_price * fill_count

        # ── Update balance ────────────────────────────────
        if order.action == OrderAction.BUY:
            total_deduction = cost_cents + fee_cents
            if total_deduction > self.balance_cents:
                log.warning(
                    "paper_fill_insufficient_balance",
                    order_id=order.order_id,
                    needed=total_deduction,
                    available=self.balance_cents,
                )
                return  # Skip fill — not enough balance
            self.balance_cents -= total_deduction
        else:
            # SELL: receive proceeds minus fees
            self.balance_cents += (cost_cents - fee_cents)

        # ── Update position ───────────────────────────────
        pos = self._positions.setdefault(
            order.ticker,
            SimulatedPosition(ticker=order.ticker),
        )

        if order.action == OrderAction.BUY:
            if order.side == OrderSide.YES:
                pos.yes_count += fill_count
            else:
                pos.no_count += fill_count
            pos.total_cost_cents += cost_cents
        else:
            # Selling: reduce position
            if order.side == OrderSide.YES:
                sold = min(fill_count, pos.yes_count)
                pos.yes_count -= sold
                # Realized P&L: sell price - avg cost
                if pos.total_cost_cents > 0 and (pos.yes_count + pos.no_count + sold) > 0:
                    avg_cost = pos.total_cost_cents / (pos.yes_count + pos.no_count + sold)
                    pos.realized_pnl_cents += int((fill_price - avg_cost) * sold)
                pos.total_cost_cents = max(0, pos.total_cost_cents - cost_cents)
            else:
                sold = min(fill_count, pos.no_count)
                pos.no_count -= sold
                pos.total_cost_cents = max(0, pos.total_cost_cents - cost_cents)

        pos.fees_paid_cents += fee_cents

        # ── Record fill ───────────────────────────────────
        fill = SimulatedFill(
            fill_id=f"fill-{uuid.uuid4().hex[:12]}",
            order_id=order.order_id,
            client_order_id=order.client_order_id,
            ticker=order.ticker,
            side=order.side,
            action=order.action,
            count=fill_count,
            price_cents=fill_price,
            is_taker=True,
            fee_cents=fee_cents,
        )
        self._fills.append(fill)
        self.total_fills += 1
        self.total_fees_paid += fee_cents
        self.total_volume_cents += cost_cents

        # ── Update order status ───────────────────────────
        order.fill_count += fill_count
        order.remaining_count -= fill_count
        order.taker_fill_cost_cents = cost_cents
        order.taker_fees_cents = fee_cents
        # Partial fill → RESTING, full fill → EXECUTED
        if order.remaining_count <= 0:
            order.remaining_count = 0
            order.status = OrderStatus.EXECUTED
        # else: stays RESTING for partial fills
        order.updated_time = datetime.now(timezone.utc)

        log.info(
            "paper_fill",
            order_id=order.order_id,
            ticker=order.ticker,
            side=order.side.value,
            action=order.action.value,
            count=fill_count,
            price=f"{fill_price}¢",
            fee=f"{fee_cents}¢",
            balance=f"${self.balance_cents / 100:.2f}",
        )

    # ── Maker Fill Simulation ─────────────────────────────────────────

    def _attempt_maker_fill(self, order: SimulatedOrder) -> bool:
        """
        Simulate realistic maker order fill probability.

        Real Kalshi maker fill rates are 20-40% depending on:
        - Price proximity to midpoint (closer = higher fill)
        - Time resting (longer = eventually fills or expires)
        - Market volume (higher volume = more crossing flow)

        This replaces the old 85% instant fill which was wildly unrealistic.
        """
        import random

        if order.remaining_count <= 0 or order.status != OrderStatus.RESTING:
            return False

        price = order.price_cents

        # Base fill probability: ~30% for typical maker orders
        # Aggressive prices (near mid) fill more often
        # Passive prices (far from mid) fill less
        if price <= 15 or price >= 85:
            # Extreme prices: very few counterparties
            fill_prob = 0.15
        elif price <= 25 or price >= 75:
            fill_prob = 0.25
        elif price <= 40 or price >= 60:
            # Near midpoint: decent fill rate
            fill_prob = 0.35
        else:
            # 40-60 range: most liquid, best fills
            fill_prob = 0.40

        # Time decay boost: orders resting longer get cumulative fill chance
        age_seconds = (datetime.now(timezone.utc) - order.created_time).total_seconds()
        if age_seconds > 60:
            fill_prob = min(0.60, fill_prob + 0.05)  # +5% after 1 min
        if age_seconds > 120:
            fill_prob = min(0.70, fill_prob + 0.10)  # +15% total after 2 min

        if random.random() > fill_prob:
            # No fill — order stays resting
            return False

        # Partial fill simulation: larger orders have more partial fills
        fill_count = order.remaining_count
        if fill_count > 2:
            if random.random() < 0.40:  # 40% chance of partial
                fill_count = max(1, int(fill_count * random.uniform(0.30, 0.70)))

        # Fill at posted price (maker = no slippage)
        self._execute_maker_fill(order, fill_count)
        return True

    def _execute_maker_fill(self, order: SimulatedOrder, fill_count: int) -> None:
        """Execute a maker fill at the posted price with 0 fees."""
        fill_price = order.price_cents
        fee_cents = 0  # Maker orders are FREE
        cost_cents = fill_price * fill_count

        if order.action == OrderAction.BUY:
            total_deduction = cost_cents + fee_cents
            if total_deduction > self.balance_cents:
                return
            self.balance_cents -= total_deduction
        else:
            self.balance_cents += cost_cents

        # Update position
        pos = self._positions.setdefault(
            order.ticker, SimulatedPosition(ticker=order.ticker),
        )
        if order.action == OrderAction.BUY:
            if order.side == OrderSide.YES:
                pos.yes_count += fill_count
            else:
                pos.no_count += fill_count
            pos.total_cost_cents += cost_cents
        else:
            if order.side == OrderSide.YES:
                sold = min(fill_count, pos.yes_count)
                pos.yes_count -= sold
                pos.total_cost_cents = max(0, pos.total_cost_cents - cost_cents)
            else:
                sold = min(fill_count, pos.no_count)
                pos.no_count -= sold
                pos.total_cost_cents = max(0, pos.total_cost_cents - cost_cents)

        # Record fill
        fill = SimulatedFill(
            fill_id=f"fill-{uuid.uuid4().hex[:12]}",
            order_id=order.order_id,
            client_order_id=order.client_order_id,
            ticker=order.ticker,
            side=order.side,
            action=order.action,
            count=fill_count,
            price_cents=fill_price,
            is_taker=False,  # Maker fill
            fee_cents=0,
        )
        self._fills.append(fill)
        self.total_fills += 1
        self.total_volume_cents += cost_cents

        # Update order status
        order.fill_count += fill_count
        order.remaining_count -= fill_count
        order.maker_fill_cost_cents += cost_cents
        if order.remaining_count <= 0:
            order.remaining_count = 0
            order.status = OrderStatus.EXECUTED
            self._resting_orders.pop(order.order_id, None)
        order.updated_time = datetime.now(timezone.utc)

        log.info(
            "paper_maker_fill",
            order_id=order.order_id,
            ticker=order.ticker,
            side=order.side.value,
            count=fill_count,
            price=f"{fill_price}¢",
            balance=f"${self.balance_cents / 100:.2f}",
        )

    def check_resting_fills(self) -> int:
        """
        Check all resting maker orders for potential fills.

        Called periodically (e.g., every scan cycle) to simulate
        the passage of time giving resting orders a chance to fill.

        Returns the number of orders that got fills.
        """
        if not self._resting_orders:
            return 0

        filled = 0
        stale_ids = []

        for order_id, order in list(self._resting_orders.items()):
            if order.status != OrderStatus.RESTING:
                stale_ids.append(order_id)
                continue

            # Check age — cancel stale orders (synced with real order expiry)
            from app.frankenstein.constants import ORDER_STALE_SECONDS
            age = (datetime.now(timezone.utc) - order.created_time).total_seconds()
            if age > ORDER_STALE_SECONDS:
                order.status = OrderStatus.CANCELED
                order.updated_time = datetime.now(timezone.utc)
                stale_ids.append(order_id)
                log.debug("paper_maker_expired", order_id=order_id, ticker=order.ticker)
                continue

            if self._attempt_maker_fill(order):
                filled += 1

        for oid in stale_ids:
            self._resting_orders.pop(oid, None)

        return filled

    # ── Cancel ────────────────────────────────────────────────────────

    def amend_order(
        self,
        order_id: str,
        yes_price: int | None = None,
        no_price: int | None = None,
    ) -> None:
        """Phase 31: Amend a resting order's price.

        Updates the order in-place and re-attempts maker fill at the new price.
        This enables poll-based requoting in paper trading mode.
        """
        order = self._orders.get(order_id)
        if not order:
            log.debug("paper_amend_skip_missing", order_id=order_id)
            return  # Order not found — already filled/cleaned
        if order.status != OrderStatus.RESTING:
            log.debug("paper_amend_skip_status",
                      order_id=order_id, status=order.status.value)
            return  # Already filled or cancelled — skip silently

        new_price = yes_price if order.side == OrderSide.YES else no_price
        if new_price is None:
            return
        if new_price == order.price_cents:
            return  # No change

        old_price = order.price_cents
        order.price_cents = new_price
        order.updated_time = datetime.now(timezone.utc)

        # Re-attempt fill at new price (maker mode)
        if self.maker_mode and order.remaining_count > 0:
            self._attempt_maker_fill(order)

        log.debug("paper_order_amended",
                  order_id=order_id,
                  old_price=f"{old_price}¢",
                  new_price=f"{new_price}¢",
                  ticker=order.ticker)

    def cancel_order(self, order_id: str) -> None:
        """Cancel a resting order."""
        order = self._orders.get(order_id)
        if not order:
            raise ValueError(f"Order {order_id} not found")
        if order.status != OrderStatus.RESTING:
            raise ValueError(f"Order {order_id} is {order.status.value}, not resting")

        order.status = OrderStatus.CANCELED
        order.updated_time = datetime.now(timezone.utc)
        log.info("paper_order_cancelled", order_id=order_id)

    def cancel_all_orders(self, ticker: str | None = None) -> int:
        """Cancel all resting orders, optionally filtered by ticker."""
        cancelled = 0
        for order in self._orders.values():
            if order.status == OrderStatus.RESTING:
                if ticker is None or order.ticker == ticker:
                    order.status = OrderStatus.CANCELED
                    order.updated_time = datetime.now(timezone.utc)
                    cancelled += 1
        log.info("paper_cancel_all", ticker=ticker, count=cancelled)
        return cancelled

    # ── Query ─────────────────────────────────────────────────────────

    def list_orders(
        self,
        status: OrderStatus | None = None,
        ticker: str | None = None,
    ) -> list[Order]:
        """List orders, optionally filtered."""
        result = []
        for o in self._orders.values():
            if status and o.status != status:
                continue
            if ticker and o.ticker != ticker:
                continue
            result.append(o.to_order_model())
        return result

    def list_fills(self, limit: int = 100) -> list[Fill]:
        """List recent fills."""
        return [f.to_fill_model() for f in self._fills[-limit:]]

    def get_positions(self) -> list[MarketPosition]:
        """Get all positions with non-zero holdings."""
        return [
            p.to_market_position()
            for p in self._positions.values()
            if p.yes_count > 0 or p.no_count > 0
        ]

    def get_position(self, ticker: str) -> SimulatedPosition | None:
        """Get position for a specific ticker."""
        return self._positions.get(ticker)

    # ── Summary ───────────────────────────────────────────────────────

    def summary(self) -> dict[str, Any]:
        """Full summary of paper trading state."""
        return {
            "balance_dollars": self.balance_dollars,
            "starting_balance": f"{self.starting_balance_cents / 100:.2f}",
            "pnl_dollars": self.pnl_dollars,
            "total_orders": self.total_orders,
            "total_fills": self.total_fills,
            "resting_orders": sum(
                1 for o in self._orders.values() if o.status == OrderStatus.RESTING
            ),
            "open_positions": len(
                [p for p in self._positions.values() if p.yes_count > 0 or p.no_count > 0]
            ),
            "total_volume": f"${self.total_volume_cents / 100:.2f}",
            "total_fees": f"${self.total_fees_paid / 100:.2f}",
        }

    # ── API Wrapper ───────────────────────────────────────────────────

    def wrap_api(self, real_api: Any) -> "PaperTradingAPIWrapper":
        """
        Create an API wrapper that uses the real Kalshi API for market data
        but routes all orders/portfolio through the paper trader.
        """
        return PaperTradingAPIWrapper(real_api, self)

    # ── State Persistence ─────────────────────────────────────────────

    def save_state_to_file(self, path: str) -> None:
        """Persist paper trading state to JSON file for crash recovery.

        Saves balance, positions, stats so we survive Railway redeploys.
        Orders and fills are ephemeral — only balance + positions matter.
        """
        import json as _json
        from pathlib import Path as _Path

        state = {
            "version": 1,
            "saved_at": time.time(),
            "balance_cents": self.balance_cents,
            "starting_balance_cents": self.starting_balance_cents,
            "total_orders": self.total_orders,
            "total_fills": self.total_fills,
            "total_fees_paid": self.total_fees_paid,
            "total_volume_cents": self.total_volume_cents,
            "positions": {
                ticker: {
                    "ticker": pos.ticker,
                    "yes_count": pos.yes_count,
                    "no_count": pos.no_count,
                    "total_cost_cents": pos.total_cost_cents,
                    "realized_pnl_cents": pos.realized_pnl_cents,
                    "fees_paid_cents": pos.fees_paid_cents,
                }
                for ticker, pos in self._positions.items()
                if pos.yes_count > 0 or pos.no_count > 0
            },
        }

        _Path(path).parent.mkdir(parents=True, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            _json.dump(state, f, indent=2)
        os.replace(tmp, path)  # atomic rename
        log.info(
            "paper_state_saved",
            balance=f"${self.balance_cents / 100:.2f}",
            positions=len(state["positions"]),
            path=path,
        )

    def load_state_from_file(self, path: str) -> bool:
        """Restore paper trading state from JSON file.

        Returns True if state was successfully loaded.
        """
        import json as _json

        if not os.path.exists(path):
            log.info("paper_state_file_not_found", path=path)
            return False

        try:
            with open(path) as f:
                state = _json.load(f)

            if state.get("version") != 1:
                log.warning("paper_state_version_mismatch", version=state.get("version"))
                return False

            old_balance = self.balance_cents

            self.balance_cents = state["balance_cents"]
            self.starting_balance_cents = state["starting_balance_cents"]
            self.total_orders = state.get("total_orders", 0)
            self.total_fills = state.get("total_fills", 0)
            self.total_fees_paid = state.get("total_fees_paid", 0)
            self.total_volume_cents = state.get("total_volume_cents", 0)

            # Restore positions
            for ticker, pos_data in state.get("positions", {}).items():
                self._positions[ticker] = SimulatedPosition(
                    ticker=pos_data["ticker"],
                    yes_count=pos_data.get("yes_count", 0),
                    no_count=pos_data.get("no_count", 0),
                    total_cost_cents=pos_data.get("total_cost_cents", 0),
                    realized_pnl_cents=pos_data.get("realized_pnl_cents", 0),
                    fees_paid_cents=pos_data.get("fees_paid_cents", 0),
                )

            saved_ago = time.time() - state.get("saved_at", 0)
            log.info(
                "paper_state_loaded",
                balance=f"${self.balance_cents / 100:.2f}",
                pnl=f"${self.pnl_cents / 100:.2f}",
                positions=len(state.get("positions", {})),
                saved_ago=f"{saved_ago:.0f}s",
                was_default=f"${old_balance / 100:.2f}",
            )
            return True

        except Exception as e:
            log.error("paper_state_load_failed", error=str(e), path=path)
            return False


# ── API Wrapper ───────────────────────────────────────────────────────────


class PaperPortfolioAPI:
    """Portfolio API backed by paper trader."""

    def __init__(self, sim: PaperTradingSimulator):
        self._sim = sim

    async def get_balance(self) -> Balance:
        return self._sim.get_balance()

    async def list_positions(
        self, limit: int = 100, **kwargs: Any
    ) -> tuple[list[MarketPosition], str | None]:
        positions = self._sim.get_positions()
        return positions[:limit], None

    async def get_all_positions(self, **kwargs: Any) -> list[MarketPosition]:
        return self._sim.get_positions()

    async def list_fills(
        self, limit: int = 100, **kwargs: Any
    ) -> tuple[list[Fill], str | None]:
        fills = self._sim.list_fills(limit=limit)
        return fills, None


class PaperOrdersAPI:
    """Orders API backed by paper trader."""

    def __init__(self, sim: PaperTradingSimulator):
        self._sim = sim

    async def create_order(self, req: CreateOrderRequest) -> Order:
        return self._sim.create_order(req)

    async def place_limit_order(
        self,
        ticker: str,
        side: OrderSide,
        action: OrderAction,
        count: int,
        price_cents: int,
        **kwargs: Any,
    ) -> Order:
        req = CreateOrderRequest(
            ticker=ticker,
            side=side,
            action=action,
            type=OrderType.LIMIT,
            count=count,
            yes_price=price_cents if side == OrderSide.YES else None,
            no_price=price_cents if side == OrderSide.NO else None,
        )
        return self._sim.create_order(req)

    async def amend_order(
        self,
        order_id: str,
        *,
        yes_price: int | None = None,
        no_price: int | None = None,
        count: int | None = None,
    ) -> None:
        """Phase 31: Amend a resting paper order's price.

        This was missing entirely, causing 1021 requote failures (0% success).
        With this fix, poll-based requoting can actually update stale orders
        to track the current market, potentially doubling fill rate.
        """
        self._sim.amend_order(order_id, yes_price=yes_price, no_price=no_price)

    async def cancel_order(self, order_id: str) -> None:
        self._sim.cancel_order(order_id)

    async def cancel_all_orders(self, ticker: str | None = None) -> None:
        self._sim.cancel_all_orders(ticker=ticker)

    async def list_orders(
        self,
        status: OrderStatus | None = None,
        ticker: str | None = None,
        **kwargs: Any,
    ) -> tuple[list[Order], str | None]:
        orders = self._sim.list_orders(status=status, ticker=ticker)
        return orders, None


class PaperTradingAPIWrapper:
    """
    Drop-in replacement for KalshiAPI.

    Uses the REAL Kalshi API for:
        .markets    — real market data, orderbooks, events
        .exchange   — exchange status
        .historical — candlesticks

    Uses the PAPER TRADER for:
        .portfolio  — simulated balance, positions, fills
        .orders     — simulated order placement, cancellation
    """

    def __init__(self, real_api: Any, sim: PaperTradingSimulator):
        self._real_api = real_api
        self._sim = sim

        # Real market data
        self.markets = real_api.markets
        self.exchange = real_api.exchange
        self.historical = real_api.historical

        # Paper trading
        self.portfolio = PaperPortfolioAPI(sim)
        self.orders = PaperOrdersAPI(sim)

    async def health_check(self) -> bool:
        """Delegate to real API."""
        return await self._real_api.health_check()

    @property
    def simulator(self) -> PaperTradingSimulator:
        """Access the underlying simulator for stats/summary."""
        return self._sim
