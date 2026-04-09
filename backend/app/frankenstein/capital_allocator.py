"""
Frankenstein — Capital Allocator. 🧟💰

Tracks reserved vs available capital and gates new trades:
  • reserved_cents    — capital locked in pending (unfilled) orders
  • available_cents   — balance minus reservations
  • can_afford()      — check before placing a new order
  • on_order_placed() — reserve capital
  • on_fill()         — convert reservation to position (buy) or free (sell)
  • on_cancel()       — release reserved capital
  • on_capital_freed()— react to CAPITAL_FREED events (sell fills, settlements)

Integrates with:
  - portfolio_state.balance_cents  (synced from Kalshi API)
  - OrderManager.pending_orders    (resting limit orders)
  - EventBus: CAPITAL_FREED → triggers fast re-scan for new opportunities

Phase 3+4 of the 20-phase profitability plan.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from app.frankenstein.constants import (
    CAPITAL_FREED_RESCAN_DELAY_S,
    CAPITAL_RECYCLE_MIN_BALANCE_CENTS,
    MAX_RESERVED_CAPITAL_PCT,
)
from app.frankenstein.event_bus import Event, EventBus, EventType
from app.logging_config import get_logger

log = get_logger("frankenstein.capital_allocator")


class CapitalAllocator:
    """
    Manages capital budgeting for Frankenstein's trading.

    Capital flow:
        balance (from Kalshi) ── reserved (pending orders) = available

    Responsibilities:
    1. Track how much capital is locked in pending orders
    2. Gate new trades: reject if available < min balance or reserved > max %
    3. React to CAPITAL_FREED: trigger fast re-scan to redeploy freed capital
    4. Provide per-trade budget guidance (max spend per trade)
    5. Phase 17: Dynamic category budgets — winning categories get more capital
    """

    # ── Phase 17: Default category budget shares ──────────────────────
    _DEFAULT_CATEGORY_SHARES: dict[str, float] = {
        # Phase 32: Rebalanced from actual performance data (2640 trades):
        # Crypto: 92.2% WR, +$221.76  →  25% (was 12%)
        # Science: 25.9% WR, +$54.08  →  12% (was 5%)
        # Finance: 31.8% WR, +$24.40  →  12% (keep)
        # Sports: 5.1% WR, +$18.65   →  15% (was 30%, break-even on 1504 trades)
        # Culture: 44.3% WR, -$11.98  →  6% (was 8%, slightly negative)
        # Politics: 0% WR, -$7.32    →  4% (was 12%, losing)
        # Weather: 0% WR, -$2.10     →  3% (was 8%, losing)
        "crypto": 0.25,
        "sports": 0.15,
        "finance": 0.12,
        "science": 0.12,
        "economics": 0.08,
        "entertainment": 0.08,
        "culture": 0.06,
        "politics": 0.04,
        "general": 0.04,
        "weather": 0.03,
        "current_events": 0.03,
    }
    # Min / max share per category (clamp after performance weighting)
    _MIN_CATEGORY_SHARE = 0.03  # No category goes below 3%
    _MAX_CATEGORY_SHARE = 0.40  # No category exceeds 40%
    _PERFORMANCE_WEIGHT = 0.4   # How much performance shifts allocations (0=ignore, 1=all perf)

    def __init__(
        self,
        event_bus: EventBus | None = None,
        *,
        min_balance_cents: int = CAPITAL_RECYCLE_MIN_BALANCE_CENTS,
        max_reserved_pct: float = MAX_RESERVED_CAPITAL_PCT,
        rescan_delay_s: float = CAPITAL_FREED_RESCAN_DELAY_S,
    ) -> None:
        self._bus = event_bus
        self._min_balance_cents = min_balance_cents
        self._max_reserved_pct = max_reserved_pct
        self._rescan_delay_s = rescan_delay_s

        # Capital state
        self._reserved_cents: int = 0        # locked in pending orders
        self._reservations: dict[str, int] = {}  # order_id → reserved_cents
        self._last_balance_cents: int = 0    # snapshot from last sync

        # Capital recycling
        self._pending_rescan: asyncio.Task | None = None
        self._rescan_callback: Any | None = None  # async callable set by brain
        self._last_freed_at: float = 0.0
        self._total_freed_cents: int = 0
        self._total_recycled_trades: int = 0

        # Phase 17: Dynamic category budgets
        self._category_shares: dict[str, float] = dict(self._DEFAULT_CATEGORY_SHARES)
        self._category_deployed: dict[str, int] = {}  # category → cents currently deployed
        self._category_pnl: dict[str, float] = {}     # category → cumulative P&L ($)

        # Metrics
        self._stats = {
            "orders_gated": 0,       # rejected for insufficient capital
            "orders_approved": 0,
            "rescans_triggered": 0,
            "total_reserved_peak": 0,
            "category_gated": 0,     # Phase 17: rejected for category budget
        }

        log.info("capital_allocator_created",
                 min_balance=f"${min_balance_cents / 100:.2f}",
                 max_reserved=f"{max_reserved_pct:.0%}")

    # ── Balance Sync ──────────────────────────────────────────────────

    def sync_balance(self, balance_cents: int) -> None:
        """Update the allocator's view of total balance (called by portfolio sync)."""
        self._last_balance_cents = balance_cents

    def sync_from_pending_orders(self, pending_orders: dict[str, dict[str, Any]]) -> None:
        """
        Rebuild reservation state from OrderManager's pending_orders.

        Called periodically (or at startup) to stay in sync.
        Each pending order reserves count * price_cents of capital.
        """
        new_reservations: dict[str, int] = {}
        for order_id, info in pending_orders.items():
            price = info.get("price_cents", 0)
            count = info.get("count", 1)
            new_reservations[order_id] = price * count

        self._reservations = new_reservations
        self._reserved_cents = sum(new_reservations.values())

    # ── Capital Checks ────────────────────────────────────────────────

    @property
    def balance_cents(self) -> int:
        """Total account balance (from last portfolio sync)."""
        return self._last_balance_cents

    @property
    def reserved_cents(self) -> int:
        """Capital currently reserved in pending orders."""
        return self._reserved_cents

    @property
    def available_cents(self) -> int:
        """Capital available for new trades."""
        return max(0, self._last_balance_cents - self._reserved_cents)

    @property
    def reserved_pct(self) -> float:
        """Fraction of balance currently reserved."""
        if self._last_balance_cents <= 0:
            return 0.0
        return self._reserved_cents / self._last_balance_cents

    def can_afford(self, cost_cents: int) -> tuple[bool, str]:
        """
        Check if we can afford a new trade of the given cost.

        Returns (approved, reason).
        """
        # Check minimum available balance
        after_trade = self.available_cents - cost_cents
        if after_trade < self._min_balance_cents:
            self._stats["orders_gated"] += 1
            return False, (
                f"insufficient_capital: available={self.available_cents}¢, "
                f"cost={cost_cents}¢, would_leave={after_trade}¢, "
                f"min={self._min_balance_cents}¢"
            )

        # Check max reserved percentage
        new_reserved = self._reserved_cents + cost_cents
        if self._last_balance_cents > 0:
            new_reserved_pct = new_reserved / self._last_balance_cents
            if new_reserved_pct > self._max_reserved_pct:
                self._stats["orders_gated"] += 1
                return False, (
                    f"max_reserved_exceeded: reserved={self._reserved_cents}¢+{cost_cents}¢, "
                    f"balance={self._last_balance_cents}¢, "
                    f"would_be={new_reserved_pct:.1%} > {self._max_reserved_pct:.0%}"
                )

        self._stats["orders_approved"] += 1
        return True, "ok"

    def max_trade_budget_cents(self) -> int:
        """
        Maximum capital available for a single trade.

        Respects both minimum balance floor and max reserved percentage.
        """
        # Budget limited by min balance floor
        budget_from_floor = max(0, self.available_cents - self._min_balance_cents)

        # Budget limited by max reserved pct
        max_total_reserved = int(self._last_balance_cents * self._max_reserved_pct)
        budget_from_pct = max(0, max_total_reserved - self._reserved_cents)

        return min(budget_from_floor, budget_from_pct)

    # ── Phase 17: Dynamic Category Budgets ────────────────────────────

    def category_budget_cents(self, category: str) -> int:
        """
        Phase 17: Maximum capital that can be deployed to a given category.

        Based on performance-weighted share of total deployable capital.
        """
        share = self._category_shares.get(category, self._category_shares.get("general", 0.10))
        total_deployable = self._last_balance_cents
        return int(total_deployable * share)

    def category_available_cents(self, category: str) -> int:
        """How much more capital this category can absorb."""
        budget = self.category_budget_cents(category)
        deployed = self._category_deployed.get(category, 0)
        return max(0, budget - deployed)

    def can_afford_category(self, cost_cents: int, category: str) -> tuple[bool, str]:
        """
        Phase 17: Check if a category has budget for this trade.

        Called AFTER the global can_afford() check passes.
        """
        avail = self.category_available_cents(category)
        if cost_cents > avail:
            self._stats["category_gated"] += 1
            budget = self.category_budget_cents(category)
            deployed = self._category_deployed.get(category, 0)
            return False, (
                f"category_budget_exceeded: {category} budget={budget}¢, "
                f"deployed={deployed}¢, requested={cost_cents}¢"
            )
        return True, "ok"

    def on_category_trade(self, category: str, cost_cents: int) -> None:
        """Track capital deployed to a category."""
        self._category_deployed[category] = self._category_deployed.get(category, 0) + cost_cents

    def on_category_close(self, category: str, cost_cents: int, pnl_dollars: float) -> None:
        """Release category capital and record P&L for reweighting."""
        self._category_deployed[category] = max(
            0, self._category_deployed.get(category, 0) - cost_cents,
        )
        self._category_pnl[category] = self._category_pnl.get(category, 0.0) + pnl_dollars

    def reweight_categories(self) -> None:
        """
        Phase 17: Recompute category budget shares from performance.

        Blend default shares with performance-derived shares.
        Winning categories get more capital, losing get less.
        """
        if not self._category_pnl:
            return  # No performance data yet

        # Performance scores: shift P&L so min = 0, then normalise
        cats = set(self._DEFAULT_CATEGORY_SHARES) | set(self._category_pnl)
        pnl_vals = {c: self._category_pnl.get(c, 0.0) for c in cats}
        min_pnl = min(pnl_vals.values()) if pnl_vals else 0.0
        shifted = {c: v - min_pnl + 1.0 for c, v in pnl_vals.items()}  # +1 floor
        total_shifted = sum(shifted.values())

        perf_shares: dict[str, float] = {}
        if total_shifted > 0:
            perf_shares = {c: v / total_shifted for c, v in shifted.items()}
        else:
            perf_shares = dict(self._DEFAULT_CATEGORY_SHARES)

        # Blend: (1-w)*default + w*perf
        w = self._PERFORMANCE_WEIGHT
        for cat in cats:
            default = self._DEFAULT_CATEGORY_SHARES.get(cat, 0.05)
            perf = perf_shares.get(cat, 0.05)
            blended = (1 - w) * default + w * perf
            blended = max(self._MIN_CATEGORY_SHARE, min(self._MAX_CATEGORY_SHARE, blended))
            self._category_shares[cat] = blended

        # Renormalise to sum to ~1.0
        total = sum(self._category_shares.values())
        if total > 0:
            self._category_shares = {c: v / total for c, v in self._category_shares.items()}

        log.info("🧟💰 CATEGORY REWEIGHT",
                 shares={c: f"{s:.1%}" for c, s in sorted(self._category_shares.items())},
                 pnl={c: f"${v:.2f}" for c, v in sorted(self._category_pnl.items())})

    # ── Order Lifecycle ───────────────────────────────────────────────

    def on_order_placed(self, order_id: str, cost_cents: int) -> None:
        """Reserve capital when a new order is placed."""
        self._reservations[order_id] = cost_cents
        self._reserved_cents += cost_cents
        self._stats["total_reserved_peak"] = max(
            self._stats["total_reserved_peak"], self._reserved_cents,
        )

    def on_order_filled(self, order_id: str) -> None:
        """
        Handle a fill event.

        For BUY fills: capital converts from reservation to position.
        For SELL fills: capital is freed (handled by on_capital_freed).
        Either way, release the reservation.
        """
        reserved = self._reservations.pop(order_id, 0)
        self._reserved_cents = max(0, self._reserved_cents - reserved)

    def on_order_cancelled(self, order_id: str) -> None:
        """Release reserved capital when an order is cancelled."""
        reserved = self._reservations.pop(order_id, 0)
        self._reserved_cents = max(0, self._reserved_cents - reserved)

    def on_order_amended(self, order_id: str, new_cost_cents: int) -> None:
        """Update reservation when an order's price is amended."""
        old_reserved = self._reservations.get(order_id, 0)
        delta = new_cost_cents - old_reserved
        self._reservations[order_id] = new_cost_cents
        self._reserved_cents = max(0, self._reserved_cents + delta)

    # ── Capital Recycling (Phase 4) ───────────────────────────────────

    async def on_capital_freed(self, event: Event) -> None:
        """
        React to CAPITAL_FREED events (sell fills, settlements).

        Debounces multiple rapid frees (e.g. batch settlement) and
        triggers a fast re-scan to immediately redeploy freed capital
        into new opportunities.
        """
        freed_cents = event.data.get("freed_cents", 0)
        ticker = event.data.get("ticker", "")

        self._total_freed_cents += freed_cents
        self._last_freed_at = time.time()

        log.info("💰 CAPITAL FREED",
                 ticker=ticker,
                 freed=f"${freed_cents / 100:.2f}",
                 available=f"${self.available_cents / 100:.2f}",
                 total_freed=f"${self._total_freed_cents / 100:.2f}")

        # Debounced re-scan: cancel pending and schedule a new one
        if self._pending_rescan and not self._pending_rescan.done():
            self._pending_rescan.cancel()

        if self._rescan_callback and self.available_cents >= self._min_balance_cents:
            self._pending_rescan = asyncio.create_task(
                self._debounced_rescan(), name="capital_rescan",
            )

    async def _debounced_rescan(self) -> None:
        """Wait for debounce window, then trigger a fast re-scan."""
        try:
            await asyncio.sleep(self._rescan_delay_s)

            if self._rescan_callback and self.available_cents >= self._min_balance_cents:
                self._stats["rescans_triggered"] += 1
                self._total_recycled_trades += 1
                log.info("💰🔄 CAPITAL RECYCLE → re-scan triggered",
                         available=f"${self.available_cents / 100:.2f}")
                await self._rescan_callback()
        except asyncio.CancelledError:
            pass  # Debounce cancelled by a newer CAPITAL_FREED event
        except Exception as e:
            log.error("capital_rescan_failed", error=str(e))

    def set_rescan_callback(self, callback: Any) -> None:
        """Set the async callback to invoke when capital is freed."""
        self._rescan_callback = callback

    # ── Stats ─────────────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        """Capital allocator statistics."""
        return {
            "balance_cents": self._last_balance_cents,
            "reserved_cents": self._reserved_cents,
            "available_cents": self.available_cents,
            "reserved_pct": f"{self.reserved_pct:.1%}",
            "reservation_count": len(self._reservations),
            "max_trade_budget_cents": self.max_trade_budget_cents(),
            "total_freed_cents": self._total_freed_cents,
            "total_recycled_trades": self._total_recycled_trades,
            "orders_gated": self._stats["orders_gated"],
            "orders_approved": self._stats["orders_approved"],
            "rescans_triggered": self._stats["rescans_triggered"],
            "peak_reserved": self._stats["total_reserved_peak"],
            "category_gated": self._stats["category_gated"],
            "category_shares": {c: f"{s:.1%}" for c, s in self._category_shares.items()},
            "category_deployed": {c: f"${v/100:.2f}" for c, v in self._category_deployed.items()},
            "category_pnl": {c: f"${v:.2f}" for c, v in self._category_pnl.items()},
        }
