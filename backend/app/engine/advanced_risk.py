"""
JA Hedge — Advanced Risk Management (Phase 7).

Enhanced risk management with:
  - Portfolio-level risk limits (VaR-inspired)
  - Correlation-aware position limits (Phase 18)
  - Dynamic risk scaling based on P&L
  - Concentration limits (per-event, per-category)
  - Drawdown-based position reduction
  - Exchange schedule awareness
"""

from __future__ import annotations

import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import numpy as np

from app.logging_config import get_logger
from app.pipeline import market_cache
from app.pipeline.portfolio_tracker import portfolio_state

log = get_logger("engine.advanced_risk")


@dataclass
class PortfolioRiskLimits:
    """Enhanced risk limits for the whole portfolio."""

    # Position limits — Phase 28c: AGGRESSIVE capital deployment
    max_positions: int = 200                   # Phase 28c: lots of positions
    max_per_event: int = 15                    # Phase 28c: 15 per event (synced with scanner)
    max_per_category: int = 60                 # Phase 28c: 60 per category
    max_portfolio_cost_cents: int = 8000_00    # Phase 28c: $8,000 max deployed (80% of $10k)

    # Loss limits — Phase 27: accept higher drawdowns for higher returns
    max_daily_loss_cents: int = 500_00         # Phase 27: $500 daily loss
    max_weekly_loss_cents: int = 1000_00       # Phase 27: $1,000 weekly loss
    max_drawdown_pct: float = 0.30             # Phase 28c: 30% max drawdown

    # Dynamic sizing
    scale_down_on_loss: bool = True
    scale_factor_per_loss_pct: float = 2.0     # Phase 27: 2x reduction per % (gentler)

    # Concentration — Phase 28c: allow larger single positions
    max_single_position_pct: float = 0.20      # Phase 28c: 20% in one position
    max_correlated_exposure_pct: float = 0.50  # Phase 28c: 50% in correlated

    # Phase 18+28c: Correlation thresholds
    correlation_high_threshold: float = 0.70
    max_same_event_cost_pct: float = 0.40      # Phase 28c: 40% of balance in same event
    max_same_category_cost_pct: float = 0.70   # Phase 28c: 70% of balance in same category


@dataclass
class PositionRisk:
    """Risk metrics for a single position."""
    ticker: str
    event_ticker: str = ""
    category: str = ""
    side: str = ""
    count: int = 0
    cost_cents: int = 0
    current_value_cents: int = 0
    unrealized_pnl_cents: int = 0
    pnl_pct: float = 0.0
    hours_to_expiry: float = 0.0
    max_loss_cents: int = 0     # worst case: lose entire cost
    max_gain_cents: int = 0     # best case: (100 - cost) per contract


class AdvancedRiskManager:
    """
    Portfolio-level risk management system.

    Called by Frankenstein before each trade to ensure the overall
    portfolio stays within acceptable risk bounds.
    """

    def __init__(self, limits: PortfolioRiskLimits | None = None):
        self._limits = limits or PortfolioRiskLimits()

        # Tracking
        self._peak_equity_cents: int = 0
        self._peak_equity_initialized: bool = False
        self._daily_pnl_cents: int = 0
        self._weekly_pnl_cents: int = 0
        self._last_daily_reset: float = 0
        self._last_weekly_reset: float = 0
        self._position_risks: dict[str, PositionRisk] = {}

        # Event/category grouping
        self._event_groups: dict[str, list[str]] = defaultdict(list)
        self._category_groups: dict[str, list[str]] = defaultdict(list)

    def update_limits(self, limits: PortfolioRiskLimits) -> None:
        self._limits = limits

    def sync_positions(self, positions: list[dict[str, Any]]) -> int:
        """Sync _position_risks from existing positions on startup.

        Args:
            positions: List of dicts with keys: ticker, event_ticker, category,
                       side, count, cost_cents, hours_to_expiry (all optional except ticker).

        Returns:
            Number of positions synced.
        """
        synced = 0
        for p in positions:
            ticker = p.get("ticker", "")
            if not ticker or ticker in self._position_risks:
                continue
            self.add_position(
                ticker=ticker,
                event_ticker=p.get("event_ticker", ""),
                category=p.get("category", ""),
                side=p.get("side", ""),
                count=p.get("count", 1),
                cost_cents=p.get("cost_cents", 0),
                hours_to_expiry=p.get("hours_to_expiry", 0),
            )
            synced += 1
        if synced:
            log.info("risk_positions_synced", count=synced)
        return synced

    # ── Pre-Trade Portfolio Check ─────────────────────────────────────

    def portfolio_check(
        self,
        ticker: str,
        count: int,
        price_cents: int,
        *,
        event_ticker: str = "",
        category: str = "",
    ) -> tuple[bool, str | None]:
        """
        Portfolio-level risk check before opening a new position.

        Returns (passed, rejection_reason).
        """
        # 0. Initialize peak equity from portfolio balance on first call
        if not self._peak_equity_initialized:
            balance = portfolio_state.balance_cents or 0
            if balance > 0:
                self._peak_equity_cents = balance
                self._peak_equity_initialized = True
                log.info("peak_equity_initialized", cents=balance)

        # 1. Total position count
        current_count = len(self._position_risks)
        if current_count >= self._limits.max_positions:
            return False, f"Max positions reached: {current_count}/{self._limits.max_positions}"

        # 2. Event concentration
        if event_ticker:
            event_count = len(self._event_groups.get(event_ticker, []))
            if event_count >= self._limits.max_per_event:
                return False, f"Max positions per event: {event_count}/{self._limits.max_per_event}"

        # 3. Category concentration
        if category:
            cat_count = len(self._category_groups.get(category, []))
            if cat_count >= self._limits.max_per_category:
                return False, f"Max positions per category: {cat_count}/{self._limits.max_per_category}"

        # 4. Total cost check
        new_cost = count * price_cents
        total_deployed = sum(pr.cost_cents for pr in self._position_risks.values())
        if total_deployed + new_cost > self._limits.max_portfolio_cost_cents:
            return False, f"Portfolio cost limit: ${(total_deployed + new_cost) / 100:.2f} > ${self._limits.max_portfolio_cost_cents / 100:.2f}"

        # 5. Single position concentration
        # Compare against total PORTFOLIO balance, not just deployed capital,
        # to avoid over-rejecting when deployed capital is small.
        if self._limits.max_single_position_pct > 0:
            portfolio_balance_cents = portfolio_state.balance_cents or 0
            reference_value = max(portfolio_balance_cents, total_deployed + new_cost, 1)
            position_pct = new_cost / reference_value
            if position_pct > self._limits.max_single_position_pct:
                return False, f"Position too concentrated: {position_pct:.1%} > {self._limits.max_single_position_pct:.1%}"

        # 6. Drawdown check
        if self._limits.max_drawdown_pct > 0 and self._peak_equity_cents > 0:
            drawdown = (self._peak_equity_cents - self._current_equity_cents()) / self._peak_equity_cents
            if drawdown > self._limits.max_drawdown_pct:
                return False, f"Max drawdown exceeded: {drawdown:.1%} > {self._limits.max_drawdown_pct:.1%}"

        # 7. Phase 18: Correlation-aware exposure — same event
        if event_ticker and self._limits.max_same_event_cost_pct > 0:
            event_cost = self._event_cost_cents(event_ticker) + new_cost
            balance = max(self._last_balance_or_portfolio(), 1)
            event_pct = event_cost / balance
            if event_pct > self._limits.max_same_event_cost_pct:
                return False, (
                    f"Event correlation limit: {event_ticker} cost "
                    f"${event_cost/100:.2f} = {event_pct:.1%} > "
                    f"{self._limits.max_same_event_cost_pct:.0%}"
                )

        # 8. Phase 18: Correlation-aware exposure — same category
        if category and self._limits.max_same_category_cost_pct > 0:
            cat_cost = self._category_cost_cents(category) + new_cost
            balance = max(self._last_balance_or_portfolio(), 1)
            cat_pct = cat_cost / balance
            if cat_pct > self._limits.max_same_category_cost_pct:
                return False, (
                    f"Category correlation limit: {category} cost "
                    f"${cat_cost/100:.2f} = {cat_pct:.1%} > "
                    f"{self._limits.max_same_category_cost_pct:.0%}"
                )

        return True, None

    # ── Phase 18: Correlation Helpers ─────────────────────────────────

    def _event_cost_cents(self, event_ticker: str) -> int:
        """Total capital deployed to positions sharing the same event."""
        total = 0
        for t in self._event_groups.get(event_ticker, []):
            pr = self._position_risks.get(t)
            if pr:
                total += pr.cost_cents
        return total

    def _category_cost_cents(self, category: str) -> int:
        """Total capital deployed to positions in the same category."""
        total = 0
        for t in self._category_groups.get(category, []):
            pr = self._position_risks.get(t)
            if pr:
                total += pr.cost_cents
        return total

    def _last_balance_or_portfolio(self) -> int:
        """Best estimate of total balance for correlation ratio."""
        bal = portfolio_state.balance_cents or 0
        if bal > 0:
            return bal
        deployed = sum(pr.cost_cents for pr in self._position_risks.values())
        return max(deployed, 1000_00)  # $10 floor to avoid div-by-zero

    def correlated_exposure_summary(self) -> dict[str, Any]:
        """Phase 18: Summary of correlated exposure by event and category."""
        balance = max(self._last_balance_or_portfolio(), 1)
        event_exposure = {}
        for evt, tickers in self._event_groups.items():
            cost = self._event_cost_cents(evt)
            if cost > 0:
                event_exposure[evt] = {
                    "cost": f"${cost/100:.2f}",
                    "pct": f"{cost/balance:.1%}",
                    "positions": len(tickers),
                }
        cat_exposure = {}
        for cat, tickers in self._category_groups.items():
            cost = self._category_cost_cents(cat)
            if cost > 0:
                cat_exposure[cat] = {
                    "cost": f"${cost/100:.2f}",
                    "pct": f"{cost/balance:.1%}",
                    "positions": len(tickers),
                }
        return {"by_event": event_exposure, "by_category": cat_exposure}

    # ── Dynamic Position Sizing ───────────────────────────────────────

    def adjusted_kelly(self, raw_kelly: float) -> float:
        """
        Scale Kelly fraction based on current portfolio state.

        Phase 20: More aggressive scaling down. Reduces sizing when:
        - In drawdown (trigger at 5% instead of 10%)
        - Many positions open (trigger at 15 instead of 50)
        - Cap Kelly at 20% regardless of input
        """
        # Phase 20: Hard cap Kelly at 20% — no matter what the raw calc says
        kelly = min(raw_kelly, 0.20)
        scale = 1.0

        # Drawdown scaling — Phase 20: trigger earlier at 5% (was 10%)
        if self._limits.scale_down_on_loss and self._peak_equity_cents > 0:
            equity = self._current_equity_cents()
            drawdown_pct = max(0, (self._peak_equity_cents - equity) / self._peak_equity_cents)
            if drawdown_pct > 0.05:
                scale *= max(0.3, 1.0 - (drawdown_pct - 0.05) * self._limits.scale_factor_per_loss_pct)

        # Position count scaling — Phase 20: start reducing at 15 positions (was 50)
        n_positions = len(self._position_risks)
        if n_positions > 15:
            scale *= max(0.4, 1.0 - (n_positions - 15) * 0.03)

        return kelly * scale

    # ── Position Tracking ─────────────────────────────────────────────

    def register_position(
        self,
        ticker: str,
        event_ticker: str,
        category: str,
        side: str,
        count: int,
        cost_cents: int,
        hours_to_expiry: float = 0,
    ) -> None:
        """Register a new position for risk tracking."""
        pr = PositionRisk(
            ticker=ticker,
            event_ticker=event_ticker,
            category=category,
            side=side,
            count=count,
            cost_cents=cost_cents,
            hours_to_expiry=hours_to_expiry,
            max_loss_cents=cost_cents,
            max_gain_cents=(100 * count) - cost_cents,
        )
        self._position_risks[ticker] = pr

        if event_ticker:
            if ticker not in self._event_groups[event_ticker]:
                self._event_groups[event_ticker].append(ticker)
        if category:
            if ticker not in self._category_groups[category]:
                self._category_groups[category].append(ticker)

    def remove_position(self, ticker: str) -> None:
        """Remove a closed position."""
        pr = self._position_risks.pop(ticker, None)
        if pr:
            if pr.event_ticker and ticker in self._event_groups.get(pr.event_ticker, []):
                self._event_groups[pr.event_ticker].remove(ticker)
            if pr.category and ticker in self._category_groups.get(pr.category, []):
                self._category_groups[pr.category].remove(ticker)

    def update_position_price(self, ticker: str, current_price_cents: int) -> None:
        """Update a position's unrealized PnL from current market price.

        Args:
            ticker: Market ticker
            current_price_cents: Current midpoint price in cents (0-100)
        """
        pr = self._position_risks.get(ticker)
        if not pr or pr.count <= 0:
            return
        avg_cost_per_contract = pr.cost_cents / pr.count if pr.count > 0 else 0
        if pr.side == "yes":
            current_value = current_price_cents * pr.count
        else:
            current_value = (100 - current_price_cents) * pr.count
        pr.current_value_cents = current_value
        pr.unrealized_pnl_cents = current_value - pr.cost_cents
        pr.pnl_pct = pr.unrealized_pnl_cents / pr.cost_cents if pr.cost_cents > 0 else 0.0

    # ── Portfolio Analytics ───────────────────────────────────────────

    def _current_equity_cents(self) -> int:
        """Estimate current equity from positions."""
        total = 0
        for pr in self._position_risks.values():
            total += pr.cost_cents + pr.unrealized_pnl_cents
        return max(total, 0)

    def update_equity(self, equity_cents: int) -> None:
        """Update peak equity tracking."""
        self._peak_equity_cents = max(self._peak_equity_cents, equity_cents)

    def portfolio_summary(self) -> dict[str, Any]:
        """Full portfolio risk summary."""
        total_cost = sum(pr.cost_cents for pr in self._position_risks.values())
        total_max_loss = sum(pr.max_loss_cents for pr in self._position_risks.values())
        total_max_gain = sum(pr.max_gain_cents for pr in self._position_risks.values())

        by_category = defaultdict(int)
        by_event = defaultdict(int)
        for pr in self._position_risks.values():
            by_category[pr.category or "unknown"] += 1
            by_event[pr.event_ticker or "unknown"] += 1

        return {
            "total_positions": len(self._position_risks),
            "total_deployed": f"${total_cost / 100:.2f}",
            "max_loss": f"${total_max_loss / 100:.2f}",
            "max_gain": f"${total_max_gain / 100:.2f}",
            "peak_equity": f"${self._peak_equity_cents / 100:.2f}",
            "by_category": dict(by_category),
            "by_event": dict(by_event),
            "correlation_exposure": self.correlated_exposure_summary(),
            "limits": {
                "max_positions": self._limits.max_positions,
                "max_portfolio_cost": f"${self._limits.max_portfolio_cost_cents / 100:.2f}",
                "max_drawdown_pct": f"{self._limits.max_drawdown_pct:.1%}",
                "max_same_event_cost_pct": f"{self._limits.max_same_event_cost_pct:.0%}",
                "max_same_category_cost_pct": f"{self._limits.max_same_category_cost_pct:.0%}",
            },
        }
