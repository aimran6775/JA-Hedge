"""
JA Hedge — Autonomous AI Trading Agent.

Goal-directed trading agent that:
1. Accepts a daily profit target (e.g., "$4100")
2. Scans Kalshi markets for high-edge opportunities
3. Builds a trade plan to hit the target
4. Autonomously places and manages orders
5. Tracks P&L progress toward the goal
6. Stops when target is reached or safety limits hit

Usage:
    agent = AutonomousAgent(...)
    await agent.start(target_profit=4100.0)
    # ... agent runs autonomously ...
    await agent.stop()
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

from app.ai.features import FeatureEngine, MarketFeatures
from app.ai.models import Prediction, PredictionModel
from app.engine.execution import ExecutionEngine, ExecutionResult
from app.engine.risk import RiskManager
from app.kalshi.models import Market, MarketStatus, OrderAction, OrderSide, OrderType
from app.logging_config import get_logger
from app.pipeline import market_cache
from app.pipeline.portfolio_tracker import portfolio_state

log = get_logger("ai.agent")


# ── Enums & Data Classes ─────────────────────────────────────────────────────


class AgentStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    TARGET_HIT = "target_hit"
    STOPPED = "stopped"
    ERROR = "error"


class Aggressiveness(str, Enum):
    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"


# Preset configs per aggressiveness level
AGGRESSIVENESS_PRESETS: dict[Aggressiveness, dict[str, Any]] = {
    Aggressiveness.CONSERVATIVE: {
        "min_confidence": 0.70,
        "min_edge": 0.08,
        "kelly_fraction": 0.15,
        "max_concurrent_positions": 5,
        "max_position_pct": 0.05,  # 5% of balance per trade
        "scan_interval": 30.0,
    },
    Aggressiveness.MODERATE: {
        "min_confidence": 0.60,
        "min_edge": 0.05,
        "kelly_fraction": 0.25,
        "max_concurrent_positions": 10,
        "max_position_pct": 0.10,  # 10% of balance per trade
        "scan_interval": 20.0,
    },
    Aggressiveness.AGGRESSIVE: {
        "min_confidence": 0.55,
        "min_edge": 0.03,
        "kelly_fraction": 0.40,
        "max_concurrent_positions": 20,
        "max_position_pct": 0.20,  # 20% of balance per trade
        "scan_interval": 10.0,
    },
}


@dataclass
class AgentTrade:
    """Record of a single trade made by the agent."""

    id: str
    ticker: str
    side: str  # "yes" / "no"
    action: str  # "buy" / "sell"
    count: int
    price_cents: int
    confidence: float
    edge: float
    expected_profit: float  # edge * count * $1
    status: str = "pending"  # pending / filled / failed / cancelled
    order_id: str | None = None
    fill_pnl: float = 0.0
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ticker": self.ticker,
            "side": self.side,
            "action": self.action,
            "count": self.count,
            "price_cents": self.price_cents,
            "confidence": round(self.confidence, 4),
            "edge": round(self.edge, 4),
            "expected_profit": round(self.expected_profit, 2),
            "status": self.status,
            "order_id": self.order_id,
            "fill_pnl": round(self.fill_pnl, 2),
            "timestamp": self.timestamp,
        }


@dataclass
class AgentStats:
    """Running agent performance stats."""

    target_profit: float = 0.0
    current_pnl: float = 0.0
    progress_pct: float = 0.0
    balance_at_start: float = 0.0
    current_balance: float = 0.0

    # Trading stats
    markets_scanned: int = 0
    signals_found: int = 0
    orders_placed: int = 0
    orders_filled: int = 0
    orders_failed: int = 0

    # Performance
    win_count: int = 0
    loss_count: int = 0
    win_rate: float = 0.0
    total_expected_profit: float = 0.0
    avg_confidence: float = 0.0
    avg_edge: float = 0.0
    best_trade_pnl: float = 0.0
    worst_trade_pnl: float = 0.0

    # Timing
    start_time: str = ""
    elapsed_seconds: float = 0.0
    scan_count: int = 0
    last_scan_time: str = ""

    # Active positions
    active_positions: int = 0
    active_exposure: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_profit": self.target_profit,
            "current_pnl": round(self.current_pnl, 2),
            "progress_pct": round(self.progress_pct, 2),
            "balance_at_start": round(self.balance_at_start, 2),
            "current_balance": round(self.current_balance, 2),
            "markets_scanned": self.markets_scanned,
            "signals_found": self.signals_found,
            "orders_placed": self.orders_placed,
            "orders_filled": self.orders_filled,
            "orders_failed": self.orders_failed,
            "win_count": self.win_count,
            "loss_count": self.loss_count,
            "win_rate": round(self.win_rate, 2),
            "total_expected_profit": round(self.total_expected_profit, 2),
            "avg_confidence": round(self.avg_confidence, 4),
            "avg_edge": round(self.avg_edge, 4),
            "best_trade_pnl": round(self.best_trade_pnl, 2),
            "worst_trade_pnl": round(self.worst_trade_pnl, 2),
            "start_time": self.start_time,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "scan_count": self.scan_count,
            "last_scan_time": self.last_scan_time,
            "active_positions": self.active_positions,
            "active_exposure": round(self.active_exposure, 2),
        }


@dataclass
class Opportunity:
    """A scored trading opportunity."""

    market: Market
    features: MarketFeatures
    prediction: Prediction
    edge: float
    confidence: float
    side: str
    recommended_count: int
    price_cents: int
    expected_profit: float  # edge * count (in dollars)
    score: float  # composite ranking score


# ── Autonomous Agent ──────────────────────────────────────────────────────────


class AutonomousAgent:
    """
    Autonomous AI Trading Agent.

    Takes a profit target and trades autonomously to hit it.
    """

    def __init__(
        self,
        model: PredictionModel,
        feature_engine: FeatureEngine,
        execution_engine: ExecutionEngine,
        risk_manager: RiskManager,
        *,
        aggressiveness: Aggressiveness = Aggressiveness.MODERATE,
    ):
        self._model = model
        self._features = feature_engine
        self._execution = execution_engine
        self._risk = risk_manager

        # Agent state
        self._status = AgentStatus.IDLE
        self._stats = AgentStats()
        self._trades: list[AgentTrade] = []
        self._task: asyncio.Task | None = None
        self._start_ts: float = 0
        self._session_id: str = ""

        # Configuration (set by aggressiveness)
        self._aggressiveness = aggressiveness
        self._apply_aggressiveness(aggressiveness)

        # Safety limits
        self._max_loss_pct: float = 0.20  # Stop if 20% of starting balance lost
        self._max_trades_per_scan: int = 5
        self._traded_tickers: set[str] = set()  # Avoid re-trading same market
        self._failed_tickers: dict[str, float] = {}  # ticker → cooldown expiry ts
        self._failed_ticker_cooldown: float = 300.0  # 5 min cooldown after failure

    def _apply_aggressiveness(self, level: Aggressiveness) -> None:
        """Apply aggressiveness preset."""
        preset = AGGRESSIVENESS_PRESETS[level]
        self._min_confidence: float = preset["min_confidence"]
        self._min_edge: float = preset["min_edge"]
        self._kelly_fraction: float = preset["kelly_fraction"]
        self._max_concurrent_positions: int = preset["max_concurrent_positions"]
        self._max_position_pct: float = preset["max_position_pct"]
        self._scan_interval: float = preset["scan_interval"]

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def status(self) -> AgentStatus:
        return self._status

    @property
    def stats(self) -> AgentStats:
        return self._stats

    @property
    def trades(self) -> list[AgentTrade]:
        return self._trades

    @property
    def is_running(self) -> bool:
        return self._status == AgentStatus.RUNNING

    # ── Control ───────────────────────────────────────────────────────────

    async def start(
        self,
        target_profit: float,
        aggressiveness: str = "moderate",
    ) -> dict[str, Any]:
        """
        Start autonomous trading with a profit target.

        Args:
            target_profit: Dollar amount to target (e.g., 4100.0)
            aggressiveness: "conservative", "moderate", or "aggressive"
        """
        if self._status == AgentStatus.RUNNING:
            return {"error": "Agent is already running"}

        # Set aggressiveness
        try:
            agg = Aggressiveness(aggressiveness.lower())
            self._aggressiveness = agg
            self._apply_aggressiveness(agg)
        except ValueError:
            self._aggressiveness = Aggressiveness.MODERATE
            self._apply_aggressiveness(Aggressiveness.MODERATE)

        # Initialize session
        self._session_id = str(uuid.uuid4())[:8]
        self._start_ts = time.time()
        self._trades = []
        self._traded_tickers = set()

        # Capture starting balance
        balance_dollars = float(portfolio_state.balance_dollars or "0")
        self._stats = AgentStats(
            target_profit=target_profit,
            balance_at_start=balance_dollars,
            current_balance=balance_dollars,
            start_time=datetime.now(timezone.utc).isoformat(),
        )

        self._status = AgentStatus.RUNNING

        # Start the autonomous loop
        self._task = asyncio.create_task(
            self._run_loop(), name=f"agent_{self._session_id}"
        )

        log.info(
            "agent_started",
            session=self._session_id,
            target=target_profit,
            aggressiveness=aggressiveness,
            balance=balance_dollars,
        )

        return {
            "status": "started",
            "session_id": self._session_id,
            "target_profit": target_profit,
            "aggressiveness": aggressiveness,
        }

    async def stop(self) -> dict[str, Any]:
        """Stop the agent gracefully."""
        if self._status not in (AgentStatus.RUNNING, AgentStatus.PAUSED):
            return {"status": self._status.value, "message": "Agent is not running"}

        self._status = AgentStatus.STOPPED

        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        # Update final stats
        self._update_timing()

        log.info(
            "agent_stopped",
            session=self._session_id,
            pnl=self._stats.current_pnl,
            progress=self._stats.progress_pct,
            trades=self._stats.orders_placed,
        )

        return {
            "status": "stopped",
            "session_id": self._session_id,
            "final_pnl": round(self._stats.current_pnl, 2),
            "progress_pct": round(self._stats.progress_pct, 2),
        }

    def get_status(self) -> dict[str, Any]:
        """Get comprehensive agent status."""
        self._update_timing()
        return {
            "status": self._status.value,
            "session_id": self._session_id,
            "aggressiveness": self._aggressiveness.value,
            "stats": self._stats.to_dict(),
            "recent_trades": [t.to_dict() for t in self._trades[-20:]],
            "config": {
                "min_confidence": self._min_confidence,
                "min_edge": self._min_edge,
                "kelly_fraction": self._kelly_fraction,
                "max_concurrent_positions": self._max_concurrent_positions,
                "scan_interval": self._scan_interval,
                "max_loss_pct": self._max_loss_pct,
            },
        }

    # ── Main Loop ─────────────────────────────────────────────────────────

    async def _run_loop(self) -> None:
        """Main autonomous trading loop."""
        try:
            while self._status == AgentStatus.RUNNING:
                try:
                    await self._trading_cycle()
                except Exception as e:
                    log.error("agent_cycle_error", error=str(e))

                # Check if target hit
                if self._stats.current_pnl >= self._stats.target_profit:
                    self._status = AgentStatus.TARGET_HIT
                    log.info(
                        "target_hit",
                        target=self._stats.target_profit,
                        pnl=self._stats.current_pnl,
                    )
                    break

                # Check safety limits
                if self._check_safety_limits():
                    break

                await asyncio.sleep(self._scan_interval)

        except asyncio.CancelledError:
            return

    async def _trading_cycle(self) -> None:
        """One full scan → analyze → trade cycle."""
        cycle_start = time.monotonic()
        self._stats.scan_count += 1
        self._stats.last_scan_time = datetime.now(timezone.utc).isoformat()

        # 1. Get active markets
        markets = market_cache.get_active()
        if not markets:
            # Try to fetch fresh markets
            from app.state import state
            if state.kalshi_api:
                try:
                    fresh = await state.kalshi_api.markets.list_markets(limit=200)
                    for m in fresh:
                        market_cache.upsert(m)
                    markets = market_cache.get_active()
                except Exception as e:
                    log.warning("agent_fetch_markets_failed", error=str(e))

        if not markets:
            log.info("agent_no_markets")
            return

        self._stats.markets_scanned += len(markets)

        # 2. Find opportunities
        opportunities = self._find_opportunities(markets)
        self._stats.signals_found += len(opportunities)

        if not opportunities:
            return

        # 3. Build trade plan
        remaining_target = self._stats.target_profit - self._stats.current_pnl
        trade_plan = self._build_trade_plan(opportunities, remaining_target)

        if not trade_plan:
            return

        # 4. Execute trades
        for opp in trade_plan:
            if self._status != AgentStatus.RUNNING:
                break
            await self._execute_opportunity(opp)
            # Small delay between orders to avoid rate limiting
            await asyncio.sleep(0.5)

        # 5. Update P&L from portfolio state
        self._update_pnl()

        elapsed = (time.monotonic() - cycle_start) * 1000
        log.info(
            "agent_cycle_complete",
            markets=len(markets),
            opportunities=len(opportunities),
            trades=len(trade_plan),
            pnl=round(self._stats.current_pnl, 2),
            progress=round(self._stats.progress_pct, 2),
            elapsed_ms=round(elapsed, 1),
        )

    # ── Opportunity Finding ───────────────────────────────────────────────

    def _find_opportunities(self, markets: list[Market]) -> list[Opportunity]:
        """Scan markets and find trading opportunities."""
        opportunities: list[Opportunity] = []

        # Import sports detector for sports_only filtering
        from app.state import state as app_state
        sports_detector = app_state.sports_detector

        now = time.time()
        # Purge expired cooldowns
        self._failed_tickers = {
            t: exp for t, exp in self._failed_tickers.items() if exp > now
        }

        for market in markets:
            # Skip non-active
            if market.status != MarketStatus.ACTIVE:
                continue

            # Skip markets with no price data
            if market.yes_bid is None and market.yes_ask is None and market.last_price is None:
                continue

            # Skip already-traded tickers (unless aggressive)
            if market.ticker in self._traded_tickers and self._aggressiveness != Aggressiveness.AGGRESSIVE:
                continue

            # Skip tickers on failed cooldown (prevent spam-retrying)
            if market.ticker in self._failed_tickers:
                continue

            # Sports-only filter: skip non-sports markets when sports_only is active
            if sports_detector is not None:
                try:
                    detection = sports_detector.detect(market)
                    if not detection.is_sports:
                        continue
                except Exception:
                    # If detection fails, skip to be safe
                    continue

            # Skip if we already have max positions
            if len(self._traded_tickers) >= self._max_concurrent_positions:
                break

            # Compute features
            try:
                features = self._features.compute(market)
            except Exception:
                continue

            # Get prediction
            try:
                prediction = self._model.predict(features)
            except Exception:
                continue

            # Filter by confidence and edge
            if prediction.confidence < self._min_confidence:
                continue
            if abs(prediction.edge) < self._min_edge:
                continue

            # Calculate position sizing
            side = prediction.side
            edge = abs(prediction.edge)
            confidence = prediction.confidence

            # Kelly criterion for sizing
            kelly = self._kelly_size(confidence, edge)
            if kelly <= 0:
                continue

            # Price calculation
            mid = features.midpoint
            if side == "yes":
                price_cents = int(min(mid + 0.01, 0.99) * 100)
            else:
                price_cents = int(min((1 - mid) + 0.01, 0.99) * 100)

            price_cents = max(1, min(99, price_cents))

            # Position size: balance-aware
            balance = float(portfolio_state.balance_dollars or "0")
            max_cost = balance * self._max_position_pct
            cost_per_contract = price_cents / 100.0
            max_contracts = int(max_cost / cost_per_contract) if cost_per_contract > 0 else 0
            count = max(1, int(kelly * max_contracts))
            count = min(count, self._risk.limits.max_position_size)

            if count <= 0:
                continue

            # Expected profit = edge * count (each contract pays $1 on correct resolution)
            expected_profit = edge * count

            # Composite score: edge * confidence * sqrt(count)
            import math
            score = edge * confidence * math.sqrt(count)

            opportunities.append(Opportunity(
                market=market,
                features=features,
                prediction=prediction,
                edge=edge,
                confidence=confidence,
                side=side,
                recommended_count=count,
                price_cents=price_cents,
                expected_profit=expected_profit,
                score=score,
            ))

        # Sort by score (highest first)
        opportunities.sort(key=lambda o: o.score, reverse=True)

        return opportunities

    def _build_trade_plan(
        self,
        opportunities: list[Opportunity],
        remaining_target: float,
    ) -> list[Opportunity]:
        """
        Select which opportunities to trade to get closest to target.

        Greedily picks highest-score opportunities until expected profit
        covers the remaining target or we hit max trades per scan.
        """
        plan: list[Opportunity] = []
        cumulative_expected = 0.0

        for opp in opportunities:
            if len(plan) >= self._max_trades_per_scan:
                break

            plan.append(opp)
            cumulative_expected += opp.expected_profit

            # If we have enough expected profit to cover remaining target, stop
            # (with 2x buffer since not all trades will work out)
            if cumulative_expected >= remaining_target * 0.5:
                break

        return plan

    # ── Trade Execution ───────────────────────────────────────────────────

    async def _execute_opportunity(self, opp: Opportunity) -> None:
        """Execute a single trading opportunity."""
        trade_id = str(uuid.uuid4())[:8]
        now = datetime.now(timezone.utc).isoformat()

        trade = AgentTrade(
            id=trade_id,
            ticker=opp.market.ticker,
            side=opp.side,
            action="buy",
            count=opp.recommended_count,
            price_cents=opp.price_cents,
            confidence=opp.confidence,
            edge=opp.edge,
            expected_profit=opp.expected_profit,
            status="pending",
            timestamp=now,
        )

        self._trades.append(trade)
        self._stats.orders_placed += 1

        # Update running averages
        n = self._stats.orders_placed
        self._stats.avg_confidence = (
            (self._stats.avg_confidence * (n - 1) + opp.confidence) / n
        )
        self._stats.avg_edge = (
            (self._stats.avg_edge * (n - 1) + opp.edge) / n
        )
        self._stats.total_expected_profit += opp.expected_profit

        try:
            side = OrderSide.YES if opp.side == "yes" else OrderSide.NO

            result: ExecutionResult = await self._execution.execute(
                ticker=opp.market.ticker,
                side=side,
                action=OrderAction.BUY,
                count=opp.recommended_count,
                price_cents=opp.price_cents,
                order_type=OrderType.LIMIT,
                strategy_id=f"agent_{self._session_id}",
            )

            if result.success:
                trade.status = "filled"
                trade.order_id = result.order_id
                self._stats.orders_filled += 1
                self._traded_tickers.add(opp.market.ticker)

                log.info(
                    "agent_trade_executed",
                    trade_id=trade_id,
                    ticker=opp.market.ticker,
                    side=opp.side,
                    count=opp.recommended_count,
                    price=opp.price_cents,
                    edge=round(opp.edge, 4),
                    expected_profit=round(opp.expected_profit, 2),
                    latency_ms=round(result.latency_ms, 1),
                )
            else:
                trade.status = "failed"
                trade.fill_pnl = 0
                self._stats.orders_failed += 1

                # Add to failed cooldown to prevent spam-retrying
                self._failed_tickers[opp.market.ticker] = (
                    time.time() + self._failed_ticker_cooldown
                )

                error_msg = result.error or result.risk_rejection_reason or "unknown"
                log.warning(
                    "agent_trade_failed",
                    trade_id=trade_id,
                    ticker=opp.market.ticker,
                    error=error_msg,
                    cooldown_seconds=self._failed_ticker_cooldown,
                )

        except Exception as e:
            trade.status = "failed"
            self._stats.orders_failed += 1
            # Add to failed cooldown on exception too
            self._failed_tickers[opp.market.ticker] = (
                time.time() + self._failed_ticker_cooldown
            )
            log.error("agent_trade_error", trade_id=trade_id, error=str(e))

    # ── P&L Tracking ──────────────────────────────────────────────────────

    def _update_pnl(self) -> None:
        """Update P&L from portfolio state."""
        # Current balance vs starting balance
        current_balance = float(portfolio_state.balance_dollars or "0")
        self._stats.current_balance = current_balance

        # P&L = current - starting + value of open positions
        balance_pnl = current_balance - self._stats.balance_at_start

        # Add unrealized P&L from positions
        unrealized = 0.0
        active_positions = 0
        active_exposure = 0.0

        for ticker in self._traded_tickers:
            pos = portfolio_state.positions.get(ticker)
            if pos and pos.position and pos.position != 0:
                active_positions += 1
                if pos.market_exposure_dollars:
                    active_exposure += abs(float(pos.market_exposure_dollars))
                if pos.realized_pnl_dollars:
                    unrealized += float(pos.realized_pnl_dollars)

        self._stats.current_pnl = balance_pnl + unrealized
        self._stats.active_positions = active_positions
        self._stats.active_exposure = active_exposure

        # Progress
        if self._stats.target_profit > 0:
            self._stats.progress_pct = min(
                (self._stats.current_pnl / self._stats.target_profit) * 100,
                100.0,
            )

        # Also estimate P&L from expected values of filled trades
        # (since positions might not sync immediately)
        if self._stats.current_pnl == 0 and self._stats.orders_filled > 0:
            estimated = sum(
                t.expected_profit for t in self._trades if t.status == "filled"
            )
            self._stats.current_pnl = estimated
            if self._stats.target_profit > 0:
                self._stats.progress_pct = min(
                    (estimated / self._stats.target_profit) * 100,
                    100.0,
                )

    def _update_timing(self) -> None:
        """Update elapsed time stats."""
        if self._start_ts > 0:
            self._stats.elapsed_seconds = time.time() - self._start_ts

    # ── Safety Checks ─────────────────────────────────────────────────────

    def _check_safety_limits(self) -> bool:
        """
        Check if any safety limits are breached.

        Returns True if agent should stop.
        """
        # Max loss check
        if self._stats.balance_at_start > 0:
            loss_pct = abs(min(self._stats.current_pnl, 0)) / self._stats.balance_at_start
            if loss_pct >= self._max_loss_pct:
                self._status = AgentStatus.STOPPED
                log.warning(
                    "agent_max_loss_hit",
                    loss_pct=round(loss_pct * 100, 1),
                    limit=round(self._max_loss_pct * 100, 1),
                )
                return True

        # Kill switch check
        if self._risk.kill_switch_active:
            self._status = AgentStatus.STOPPED
            log.warning("agent_stopped_kill_switch")
            return True

        return False

    # ── Helpers ───────────────────────────────────────────────────────────

    def _kelly_size(self, confidence: float, edge: float) -> float:
        """
        Kelly criterion for optimal position sizing.

        f* = (bp - q) / b  with fractional Kelly for safety.
        """
        p = confidence
        q = 1 - p
        if edge <= 0 or p <= 0.5:
            return 0

        b = edge / max(1 - confidence, 0.01)
        kelly = (b * p - q) / max(b, 0.01)
        adjusted = max(0, kelly * self._kelly_fraction)
        return min(adjusted, 1.0)
