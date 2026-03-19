"""
JA Hedge — Risk Management System.

Enforces trading limits and safety controls:
- Position size limits (per-market, per-event, portfolio)
- Daily loss limits with automatic kill switch
- Spread/liquidity filters
- Stop-loss / take-profit monitoring
- Real-time exposure tracking
- Kill switch for emergency shutdown
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from app.db.engine import get_session_factory
from app.db.models import RiskEvent, StrategyConfig
from app.kalshi.models import OrderAction, OrderSide
from app.logging_config import get_logger
from app.pipeline import market_cache
from app.pipeline.portfolio_tracker import portfolio_state

log = get_logger("engine.risk")


@dataclass
class RiskLimits:
    """Active risk parameters — loaded from strategy config + global defaults."""

    max_position_size: int = 10
    max_daily_loss: Decimal = Decimal("75.0")
    max_portfolio_exposure: Decimal = Decimal("750.0")
    max_single_order_cost: Decimal = Decimal("150.0")
    stop_loss_pct: Decimal | None = None
    take_profit_pct: Decimal | None = None
    min_spread_cents: int = 0
    max_spread_cents: int = 40    # hard wall — strategy uses tighter limit
    min_volume: int = 0
    min_time_to_expiry_hours: int = 0  # Allow near-expiry trades (model handles timing)
    kill_switch_active: bool = False


@dataclass
class RiskSnapshot:
    """Point-in-time risk state for monitoring."""

    total_exposure: Decimal = Decimal("0")
    daily_pnl: Decimal = Decimal("0")
    daily_trades: int = 0
    position_count: int = 0
    open_orders: int = 0
    kill_switch_active: bool = False
    last_check: float = 0
    violations: list[str] = field(default_factory=list)


class RiskManager:
    """
    Centralized risk management.

    Called by ExecutionEngine before every trade and
    continuously monitors portfolio for limit breaches.
    """

    def __init__(self, limits: RiskLimits | None = None):
        self._limits = limits or RiskLimits()
        self._snapshot = RiskSnapshot()
        self._kill_switch = False
        self._daily_loss_reset_date: str = ""

    @property
    def limits(self) -> RiskLimits:
        return self._limits

    @property
    def snapshot(self) -> RiskSnapshot:
        return self._snapshot

    @property
    def kill_switch_active(self) -> bool:
        return self._kill_switch

    def update_limits(self, new_limits: RiskLimits) -> None:
        """Update risk limits (e.g., from dashboard config change)."""
        self._limits = new_limits
        log.info("risk_limits_updated", limits=str(new_limits))

    # ── Kill Switch ───────────────────────────────────────────────────────

    def activate_kill_switch(self, reason: str = "manual") -> None:
        """Emergency stop — no new orders allowed."""
        self._kill_switch = True
        self._limits.kill_switch_active = True
        log.critical("kill_switch_activated", reason=reason)

    def deactivate_kill_switch(self) -> None:
        """Re-enable trading."""
        self._kill_switch = False
        self._limits.kill_switch_active = False
        log.warning("kill_switch_deactivated")

    # ── Pre-Trade Checks ──────────────────────────────────────────────────

    async def pre_trade_check(
        self,
        ticker: str,
        side: OrderSide,
        action: OrderAction,
        count: int,
        price_cents: int | None = None,
    ) -> tuple[bool, str | None]:
        """
        Run all pre-trade risk checks.

        Returns:
            (passed, rejection_reason)
        """
        # 1. Kill switch
        if self._kill_switch:
            return False, "Kill switch is active"

        # 2. Daily loss limit
        if portfolio_state.daily_pnl < -self._limits.max_daily_loss:
            self.activate_kill_switch(reason="daily_loss_limit_exceeded")
            await self._log_risk_event(
                "daily_loss_breach",
                "critical",
                ticker=ticker,
                message=f"Daily P&L {portfolio_state.daily_pnl} exceeded limit -{self._limits.max_daily_loss}",
            )
            return False, f"Daily loss limit exceeded: {portfolio_state.daily_pnl}"

        # 3. Position size limit
        existing = portfolio_state.positions.get(ticker)
        current_size = abs(existing.position or 0) if existing else 0
        if action == OrderAction.BUY and current_size + count > self._limits.max_position_size:
            return False, f"Position size limit: {current_size} + {count} > {self._limits.max_position_size}"

        # 4. Portfolio exposure limit
        if portfolio_state.total_exposure > self._limits.max_portfolio_exposure:
            return False, f"Portfolio exposure {portfolio_state.total_exposure} exceeds {self._limits.max_portfolio_exposure}"

        # 5. Single order cost check
        if price_cents is not None and action == OrderAction.BUY:
            estimated_cost = Decimal(price_cents * count) / 100
            if estimated_cost > self._limits.max_single_order_cost:
                return False, f"Order cost ${estimated_cost} exceeds max ${self._limits.max_single_order_cost}"

        # 6. Market liquidity/spread check
        market = market_cache.get(ticker)
        if market:
            if market.spread is not None:
                spread_cents = int(market.spread * 100)
                if spread_cents > self._limits.max_spread_cents:
                    return False, f"Spread {spread_cents}¢ exceeds max {self._limits.max_spread_cents}¢"

            # Volume check
            if self._limits.min_volume > 0:
                vol = market.volume_int or 0
                if vol < self._limits.min_volume:
                    return False, f"Volume {vol} below minimum {self._limits.min_volume}"

            # Time to expiry check
            if market.expiration_time and self._limits.min_time_to_expiry_hours > 0:
                now = datetime.now(timezone.utc)
                hours_to_expiry = (market.expiration_time - now).total_seconds() / 3600
                if hours_to_expiry < self._limits.min_time_to_expiry_hours:
                    return False, f"Only {hours_to_expiry:.1f}h to expiry (min: {self._limits.min_time_to_expiry_hours}h)"

        # All checks passed
        return True, None

    # ── Continuous Monitoring ─────────────────────────────────────────────

    async def check_stop_losses(self) -> list[str]:
        """
        Check all positions against stop-loss thresholds.

        Returns list of tickers that need to be closed.
        """
        tickers_to_close: list[str] = []

        if self._limits.stop_loss_pct is None:
            return tickers_to_close

        for ticker, pos in portfolio_state.positions.items():
            market = market_cache.get(ticker)
            if not market or not pos.realized_pnl_dollars:
                continue

            realized = Decimal(pos.realized_pnl_dollars)
            cost = Decimal(pos.market_exposure_dollars) if pos.market_exposure_dollars else Decimal("1")
            if cost == 0:
                continue

            loss_pct = abs(realized / cost) if realized < 0 else Decimal("0")
            if loss_pct >= self._limits.stop_loss_pct:
                tickers_to_close.append(ticker)
                log.warning(
                    "stop_loss_triggered",
                    ticker=ticker,
                    loss_pct=float(loss_pct),
                    threshold=float(self._limits.stop_loss_pct),
                )

        return tickers_to_close

    async def check_take_profits(self) -> list[str]:
        """Check all positions against take-profit thresholds."""
        tickers_to_close: list[str] = []

        if self._limits.take_profit_pct is None:
            return tickers_to_close

        for ticker, pos in portfolio_state.positions.items():
            if not pos.realized_pnl_dollars or not pos.market_exposure_dollars:
                continue

            realized = Decimal(pos.realized_pnl_dollars)
            cost = Decimal(pos.market_exposure_dollars) if pos.market_exposure_dollars else Decimal("1")
            if cost == 0:
                continue

            profit_pct = realized / cost if realized > 0 else Decimal("0")
            if profit_pct >= self._limits.take_profit_pct:
                tickers_to_close.append(ticker)
                log.info(
                    "take_profit_triggered",
                    ticker=ticker,
                    profit_pct=float(profit_pct),
                    threshold=float(self._limits.take_profit_pct),
                )

        return tickers_to_close

    async def get_exit_candidates(self) -> list[dict[str, Any]]:
        """
        Combine stop-loss and take-profit checks into a single
        list of exit candidates with reasons.
        """
        candidates: list[dict[str, Any]] = []

        sl_tickers = await self.check_stop_losses()
        for t in sl_tickers:
            candidates.append({"ticker": t, "reason": "stop_loss", "urgency": "high"})

        tp_tickers = await self.check_take_profits()
        for t in tp_tickers:
            if t not in sl_tickers:
                candidates.append({"ticker": t, "reason": "take_profit", "urgency": "medium"})

        return candidates

    async def update_snapshot(self) -> RiskSnapshot:
        """Refresh the risk snapshot from portfolio state."""
        self._snapshot = RiskSnapshot(
            total_exposure=portfolio_state.total_exposure,
            daily_pnl=portfolio_state.daily_pnl,
            daily_trades=portfolio_state.daily_trades,
            position_count=portfolio_state.position_count,
            open_orders=portfolio_state.open_order_count,
            kill_switch_active=self._kill_switch,
            last_check=time.time(),
        )
        return self._snapshot

    # ── Risk Event Logging ────────────────────────────────────────────────

    async def _log_risk_event(
        self,
        event_type: str,
        severity: str,
        *,
        ticker: str | None = None,
        strategy_id: str | None = None,
        message: str = "",
        details: dict | None = None,
    ) -> None:
        """Persist a risk event to the database."""
        try:
            factory = get_session_factory()
            async with factory() as session:
                event = RiskEvent(
                    event_type=event_type,
                    severity=severity,
                    strategy_id=strategy_id,
                    ticker=ticker,
                    message=message,
                    details=details or {},
                )
                session.add(event)
                await session.commit()
        except Exception as e:
            log.error("risk_event_log_failed", error=str(e))
