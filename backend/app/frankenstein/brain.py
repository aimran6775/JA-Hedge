"""
Frankenstein — The Brain. 🧟

The central AI orchestrator that controls the entire JA Hedge
trading platform. Frankenstein unifies what were previously two
separate "brains" (TradingStrategy + AutonomousAgent) into a
single self-evolving intelligence.

Frankenstein:
- Scans markets and generates trading signals
- Executes trades through the execution engine
- Learns from every outcome (win or loss)
- Retrains its model hourly with new data
- Adapts strategy parameters to market conditions
- Tracks its own performance and health
- Pauses trading when degrading
- Saves its state for persistence across restarts

This is the god module. Frankenstein has control over everything.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import numpy as np

from app.ai.features import FeatureEngine, MarketFeatures
from app.ai.models import Prediction, PredictionModel, XGBoostPredictor
from app.engine.execution import ExecutionEngine, ExecutionResult
from app.engine.risk import RiskManager
from app.frankenstein.learner import OnlineLearner
from app.frankenstein.memory import TradeMemory, TradeOutcome, TradeRecord
from app.frankenstein.performance import PerformanceTracker, PerformanceSnapshot
from app.frankenstein.scheduler import FrankensteinScheduler
from app.frankenstein.strategy import AdaptiveStrategy, StrategyParams
from app.kalshi.models import Market, MarketStatus, OrderAction, OrderSide, OrderType
from app.logging_config import get_logger
from app.pipeline import market_cache

log = get_logger("frankenstein.brain")


@dataclass
class FrankensteinConfig:
    """Configuration for the Frankenstein brain."""

    # Scan settings
    scan_interval: float = 30.0           # seconds between market scans
    max_candidates: int = 500             # max markets per scan

    # Learning settings
    retrain_interval: float = 3600.0      # 1 hour between retraining
    min_train_samples: int = 50
    retrain_threshold: int = 25           # new trades before retraining

    # Persistence
    memory_persist_path: str = "data/frankenstein_memory.json"
    checkpoint_dir: str = "data/models"
    auto_save_interval: float = 1800.0    # 30 min auto-save

    # Health
    performance_snapshot_interval: float = 300.0  # 5 min
    strategy_adaptation_interval: float = 900.0   # 15 min
    outcome_check_interval: float = 120.0         # 2 min

    # Risk
    max_daily_loss: float = 50.0
    pause_on_degradation: bool = True

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class FrankensteinState:
    """Current state of the Frankenstein brain."""
    is_alive: bool = False
    is_trading: bool = False
    is_paused: bool = False
    pause_reason: str = ""
    birth_time: float = 0.0
    total_scans: int = 0
    total_signals: int = 0
    total_trades_executed: int = 0
    total_trades_rejected: int = 0
    current_scan_time_ms: float = 0.0
    last_scan_time: float = 0.0
    last_retrain_time: float = 0.0
    last_adaptation_time: float = 0.0
    generation: int = 0
    model_version: str = "untrained"


class Frankenstein:
    """
    🧟 THE FRANKENSTEIN BRAIN 🧟

    A self-evolving AI trading system that:
    1. Scans markets for opportunities
    2. Predicts outcomes with ML
    3. Sizes positions with Kelly criterion
    4. Executes trades through risk management
    5. Records every action in memory
    6. Learns from outcomes
    7. Adapts strategy parameters
    8. Monitors its own health

    Frankenstein is the single brain that controls JA Hedge.
    """

    def __init__(
        self,
        model: XGBoostPredictor,
        feature_engine: FeatureEngine,
        execution_engine: ExecutionEngine,
        risk_manager: RiskManager,
        *,
        config: FrankensteinConfig | None = None,
    ):
        self.config = config or FrankensteinConfig()

        # Core components (injected)
        self._model = model
        self._features = feature_engine
        self._execution = execution_engine
        self._risk = risk_manager

        # Frankenstein's own subsystems
        self.memory = TradeMemory(
            max_trades=50_000,
            persist_path=self.config.memory_persist_path,
        )
        self.performance = PerformanceTracker(memory=self.memory)
        self.learner = OnlineLearner(
            model=model,
            memory=self.memory,
            min_samples=self.config.min_train_samples,
            retrain_threshold=self.config.retrain_threshold,
            checkpoint_dir=self.config.checkpoint_dir,
        )
        self.strategy = AdaptiveStrategy(
            memory=self.memory,
            performance=self.performance,
            adaptation_interval=self.config.strategy_adaptation_interval,
        )
        self.scheduler = FrankensteinScheduler()

        # State
        self._state = FrankensteinState()
        self._scan_task: asyncio.Task | None = None

        log.info("🧟 FRANKENSTEIN CREATED", config=self.config.to_dict())

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def awaken(self) -> None:
        """
        🧟 Bring Frankenstein to life.

        Starts all background tasks: scanning, learning,
        performance tracking, and strategy adaptation.
        """
        if self._state.is_alive:
            log.warning("frankenstein_already_alive")
            return

        self._state.is_alive = True
        self._state.birth_time = time.time()
        self._state.is_trading = True

        # Register scheduled tasks
        self.scheduler.register(
            "retrain",
            self._retrain_task,
            self.config.retrain_interval,
        )
        self.scheduler.register(
            "performance_snapshot",
            self._performance_task,
            self.config.performance_snapshot_interval,
        )
        self.scheduler.register(
            "adapt_strategy",
            self._adaptation_task,
            self.config.strategy_adaptation_interval,
        )
        self.scheduler.register(
            "auto_save",
            self._save_task,
            self.config.auto_save_interval,
        )
        self.scheduler.register(
            "health_check",
            self._health_check_task,
            60.0,  # every minute
        )
        self.scheduler.register(
            "resolve_outcomes",
            self._resolve_outcomes_task,
            self.config.outcome_check_interval,
        )

        # Start scheduler
        await self.scheduler.start()

        # Start the main scan loop
        self._scan_task = asyncio.create_task(
            self._scan_loop(),
            name="frankenstein_scan",
        )

        log.info(
            "🧟⚡ FRANKENSTEIN IS ALIVE!",
            model=self._model.name,
            model_version=self._model.version,
            config=self.config.to_dict(),
        )

    async def sleep(self) -> None:
        """Put Frankenstein to sleep (graceful shutdown)."""
        if not self._state.is_alive:
            return

        self._state.is_alive = False
        self._state.is_trading = False

        # Stop scan loop
        if self._scan_task and not self._scan_task.done():
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                pass

        # Stop scheduler
        await self.scheduler.stop()

        # Save memory
        self.memory.save()

        log.info(
            "🧟💤 FRANKENSTEIN SLEEPS",
            uptime=f"{time.time() - self._state.birth_time:.0f}s",
            total_scans=self._state.total_scans,
            total_trades=self._state.total_trades_executed,
            generation=self._state.generation,
        )

    # ── Main Scan Loop ────────────────────────────────────────────────

    async def _scan_loop(self) -> None:
        """Main trading loop — scan → predict → decide → execute."""
        try:
            while self._state.is_alive:
                try:
                    if self._state.is_trading and not self._state.is_paused:
                        await self._scan_and_trade()
                except Exception as e:
                    log.error("scan_error", error=str(e))

                interval = self.strategy.params.scan_interval
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            return

    async def _scan_and_trade(self) -> None:
        """One full scan cycle: find opportunities → trade."""
        start = time.monotonic()
        self._state.total_scans += 1

        # 1. Get active markets
        markets = market_cache.get_active()
        if not markets:
            return

        # 2. Filter candidates
        candidates = self._filter_candidates(markets)
        if not candidates:
            return

        # 3. Compute features for all candidates
        features_list = [self._features.compute(m) for m in candidates]

        # 4. Batch predict
        predictions = self._model.predict_batch(features_list)

        # 5. Evaluate each signal through adaptive strategy
        params = self.strategy.params
        signals_generated = 0
        trades_executed = 0
        trades_rejected = 0

        for market, features, prediction in zip(candidates, features_list, predictions):
            # Apply adaptive thresholds
            if prediction.confidence < params.min_confidence:
                continue
            if abs(prediction.edge) < params.min_edge:
                continue

            signals_generated += 1
            self._state.total_signals += 1

            # Kelly criterion position sizing
            kelly = self._kelly_size(prediction, params)
            if kelly <= 0:
                continue

            count = max(1, int(kelly * params.max_position_size))
            price_cents = self._compute_price(prediction, features)

            # Record snapshot for regime detection
            self.memory.record_snapshot(
                ticker=market.ticker,
                midpoint=features.midpoint,
                spread=features.spread,
                volume=features.volume,
            )

            # Execute through risk manager
            result = await self._execute_trade(
                market=market,
                prediction=prediction,
                features=features,
                count=count,
                price_cents=price_cents,
            )

            if result and result.success:
                trades_executed += 1
                self._state.total_trades_executed += 1

                # Record in Frankenstein's memory
                self.memory.record_trade(
                    ticker=market.ticker,
                    prediction=prediction,
                    features=features,
                    action="buy",
                    count=count,
                    price_cents=price_cents,
                    order_id=result.order_id or "",
                    latency_ms=result.latency_ms,
                    market_bid=int((market.yes_bid or 0) * 100) if isinstance(market.yes_bid, float) else (market.yes_bid or 0),
                    market_ask=int((market.yes_ask or 0) * 100) if isinstance(market.yes_ask, float) else (market.yes_ask or 0),
                    model_version=self.learner.current_version,
                )
            else:
                trades_rejected += 1
                self._state.total_trades_rejected += 1

        elapsed = (time.monotonic() - start) * 1000
        self._state.current_scan_time_ms = elapsed
        self._state.last_scan_time = time.time()

        if signals_generated > 0:
            log.info(
                "🧟 SCAN",
                candidates=len(candidates),
                signals=signals_generated,
                executed=trades_executed,
                rejected=trades_rejected,
                ms=f"{elapsed:.1f}",
                gen=self._state.generation,
            )

    # ── Trade Execution ───────────────────────────────────────────────

    async def _execute_trade(
        self,
        market: Market,
        prediction: Prediction,
        features: MarketFeatures,
        count: int,
        price_cents: int,
    ) -> ExecutionResult | None:
        """Execute a trade through the execution engine."""
        try:
            side = OrderSide.YES if prediction.side == "yes" else OrderSide.NO

            result = await self._execution.execute(
                ticker=market.ticker,
                side=side,
                action=OrderAction.BUY,
                count=count,
                price_cents=price_cents,
                order_type=OrderType.LIMIT,
                strategy_id="frankenstein",
                signal_id=None,
            )

            return result
        except Exception as e:
            log.error("execution_failed", ticker=market.ticker, error=str(e))
            return None

    # ── Signal Processing Helpers ─────────────────────────────────────

    def _filter_candidates(self, markets: list[Market]) -> list[Market]:
        """Filter markets to tradeable candidates."""
        params = self.strategy.params
        candidates = []

        for m in markets:
            if m.status != MarketStatus.ACTIVE:
                continue
            if m.yes_bid is None and m.yes_ask is None and m.last_price is None:
                continue

            # Skip if we're at position limit for this market
            from app.pipeline.portfolio_tracker import portfolio_state
            pos = portfolio_state.positions.get(m.ticker)
            if pos and abs(pos.position or 0) >= params.max_position_size:
                continue

            candidates.append(m)

        return candidates[:self.config.max_candidates]

    def _kelly_size(self, prediction: Prediction, params: StrategyParams) -> float:
        """Kelly criterion with adaptive fractional sizing."""
        p = prediction.confidence
        q = 1 - p
        edge = abs(prediction.edge)

        if edge <= 0 or p <= 0.5:
            return 0.0

        b = edge / max(q, 0.01)
        kelly = (b * p - q) / max(b, 0.01)

        # Apply adaptive fractional Kelly (from strategy engine)
        adjusted = max(0, kelly * params.kelly_fraction)

        # Apply aggression multiplier
        adjusted *= (0.5 + params.aggression)

        return min(adjusted, 1.0)

    def _compute_price(self, prediction: Prediction, features: MarketFeatures) -> int:
        """Compute optimal order price."""
        mid = features.midpoint
        if prediction.side == "yes":
            price = min(mid + 0.01, 0.99)
        else:
            price = max((1 - mid) + 0.01, 0.01)
        return int(price * 100)

    # ── Scheduled Tasks ───────────────────────────────────────────────

    async def _retrain_task(self) -> None:
        """Periodic model retraining."""
        checkpoint = await self.learner.retrain()
        if checkpoint:
            self._state.generation = self.learner.generation
            self._state.model_version = checkpoint.version
            self._state.last_retrain_time = time.time()

    async def _performance_task(self) -> None:
        """Periodic performance snapshot."""
        self.performance.compute_snapshot()

    async def _adaptation_task(self) -> None:
        """Periodic strategy adaptation."""
        snapshot = self.performance.compute_snapshot()
        events = self.strategy.adapt(snapshot)
        if events:
            self._state.last_adaptation_time = time.time()

    async def _save_task(self) -> None:
        """Periodic memory save."""
        self.memory.save()

    async def _health_check_task(self) -> None:
        """Periodic health check — pause if degrading."""
        should_pause, reason = self.performance.should_pause_trading()

        if should_pause and not self._state.is_paused:
            self._state.is_paused = True
            self._state.pause_reason = reason
            log.warning("🧟🛑 FRANKENSTEIN PAUSED", reason=reason)

        elif not should_pause and self._state.is_paused:
            self._state.is_paused = False
            self._state.pause_reason = ""
            log.info("🧟✅ FRANKENSTEIN RESUMED")

        # Check for model degradation
        if self.config.pause_on_degradation and self.performance.is_model_degrading():
            log.warning("🧟⚠️ MODEL DEGRADATION DETECTED — forcing retrain")
            await self._retrain_task()

    async def _resolve_outcomes_task(self) -> None:
        """Check for settled markets and resolve pending trades."""
        pending = self.memory.get_pending_trades()
        if not pending:
            return

        for trade in pending:
            try:
                # Check if market has settled
                markets = market_cache.get_active()
                market = None
                for m in markets:
                    if m.ticker == trade.ticker:
                        market = m
                        break

                if market is None:
                    # Market no longer active — might be settled
                    # We'd need to query the API for result
                    # For now, mark as expired if old enough
                    if time.time() - trade.timestamp > 86400:  # 24 hours
                        self.memory.resolve_trade(
                            trade.trade_id,
                            TradeOutcome.EXPIRED,
                        )
                elif market.result is not None:
                    # Market has settled!
                    result = str(market.result).lower()
                    correct = trade.predicted_side == result

                    if correct:
                        # Won: payout = count * 100 - cost
                        pnl_cents = trade.count * 100 - trade.total_cost_cents
                        outcome = TradeOutcome.WIN
                    else:
                        # Lost: lost the cost
                        pnl_cents = -trade.total_cost_cents
                        outcome = TradeOutcome.LOSS

                    self.memory.resolve_trade(
                        trade.trade_id,
                        outcome,
                        pnl_cents=pnl_cents,
                        market_result=result,
                    )
            except Exception as e:
                log.debug("outcome_check_error", ticker=trade.ticker, error=str(e))

    # ── Manual Controls ───────────────────────────────────────────────

    def pause(self, reason: str = "manual") -> None:
        """Manually pause Frankenstein's trading."""
        self._state.is_paused = True
        self._state.pause_reason = reason
        log.info("🧟⏸️ FRANKENSTEIN PAUSED MANUALLY", reason=reason)

    def resume(self) -> None:
        """Resume Frankenstein's trading."""
        self._state.is_paused = False
        self._state.pause_reason = ""
        log.info("🧟▶️ FRANKENSTEIN RESUMED")

    async def force_retrain(self) -> dict[str, Any]:
        """Force an immediate model retraining."""
        checkpoint = await self.learner.retrain(force=True)
        if checkpoint:
            self._state.generation = self.learner.generation
            self._state.model_version = checkpoint.version
            return {
                "success": True,
                "version": checkpoint.version,
                "generation": self.learner.generation,
                "auc": checkpoint.val_auc,
            }
        return {"success": False, "reason": "insufficient_data_or_no_improvement"}

    # ── Full Status ───────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        """Complete Frankenstein status for dashboard/API."""
        uptime = time.time() - self._state.birth_time if self._state.is_alive else 0

        return {
            "name": "Frankenstein",
            "version": self._state.model_version,
            "generation": self._state.generation,
            "is_alive": self._state.is_alive,
            "is_trading": self._state.is_trading and not self._state.is_paused,
            "is_paused": self._state.is_paused,
            "pause_reason": self._state.pause_reason,
            "uptime_seconds": uptime,
            "uptime_human": self._format_uptime(uptime),

            # Activity
            "total_scans": self._state.total_scans,
            "total_signals": self._state.total_signals,
            "total_trades_executed": self._state.total_trades_executed,
            "total_trades_rejected": self._state.total_trades_rejected,
            "last_scan_ms": f"{self._state.current_scan_time_ms:.1f}",

            # Subsystem status
            "memory": self.memory.stats(),
            "performance": self.performance.summary(),
            "learner": self.learner.stats(),
            "strategy": self.strategy.stats(),
            "scheduler": self.scheduler.stats(),
        }

    @staticmethod
    def _format_uptime(seconds: float) -> str:
        """Format uptime in human-readable form."""
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            return f"{seconds / 60:.0f}m"
        elif seconds < 86400:
            return f"{seconds / 3600:.1f}h"
        else:
            return f"{seconds / 86400:.1f}d"
