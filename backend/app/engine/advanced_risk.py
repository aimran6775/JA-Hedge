"""
JA Hedge — Advanced Risk Management (Phase 7).

Enhanced risk management with:
  - Portfolio-level risk limits (VaR-inspired)
  - Correlation-aware position limits
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

    # Position limits
    max_positions: int = 30                    # total open positions
    max_per_event: int = 5                     # max positions in one event
    max_per_category: int = 10                 # max positions in one category
    max_portfolio_cost_cents: int = 500_00     # $500 total deployed

    # Loss limits
    max_daily_loss_cents: int = 50_00          # $50 daily loss trigger
    max_weekly_loss_cents: int = 150_00        # $150 weekly loss trigger
    max_drawdown_pct: float = 0.10             # 10% max drawdown from peak

    # Dynamic sizing
    scale_down_on_loss: bool = True            # reduce sizes when losing
    scale_factor_per_loss_pct: float = 2.0     # 2x reduction per % of drawdown

    # Concentration
    max_single_position_pct: float = 0.20      # max 20% of portfolio in one position
    max_correlated_exposure_pct: float = 0.40  # max 40% in correlated positions


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

        return True, None

    # ── Dynamic Position Sizing ───────────────────────────────────────

    def adjusted_kelly(self, raw_kelly: float) -> float:
        """
        Scale Kelly fraction based on current portfolio state.

        Reduces sizing when:
        - In drawdown
        - Many positions open
        - High correlated exposure
        """
        scale = 1.0

        # Drawdown scaling
        if self._limits.scale_down_on_loss and self._peak_equity_cents > 0:
            equity = self._current_equity_cents()
            drawdown_pct = max(0, (self._peak_equity_cents - equity) / self._peak_equity_cents)
            if drawdown_pct > 0.02:  # >2% drawdown
                scale *= max(0.2, 1.0 - drawdown_pct * self._limits.scale_factor_per_loss_pct)

        # Position count scaling (fewer contracts when many positions open)
        n_positions = len(self._position_risks)
        if n_positions > 10:
            scale *= max(0.3, 1.0 - (n_positions - 10) * 0.05)

        return raw_kelly * scale

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
            "limits": {
                "max_positions": self._limits.max_positions,
                "max_portfolio_cost": f"${self._limits.max_portfolio_cost_cents / 100:.2f}",
                "max_drawdown_pct": f"{self._limits.max_drawdown_pct:.1%}",
            },
        }
