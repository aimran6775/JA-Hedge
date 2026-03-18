"""
JA Hedge — AI Trading Strategy.

Orchestrates the full AI trading loop:
1. Feature computation for candidate markets
2. Model prediction (probability + edge)
3. Kelly criterion position sizing
4. Order submission via ExecutionEngine

Configurable via StrategyConfig in the database.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.ai.features import FeatureEngine, MarketFeatures
from app.ai.models import Prediction, PredictionModel, XGBoostPredictor
from app.db.engine import get_session_factory
from app.db.models import AISignal, StrategyConfig
from app.engine.execution import ExecutionEngine, ExecutionResult
from app.engine.risk import RiskManager
from app.kalshi.models import Market, MarketStatus, OrderAction, OrderSide, OrderType
from app.logging_config import get_logger
from app.pipeline import market_cache

log = get_logger("ai.strategy")


@dataclass
class StrategyDecision:
    """A single trading decision from the AI strategy."""

    ticker: str
    side: str  # "yes" / "no"
    action: str  # "buy" / "sell"
    count: int
    price_cents: int
    confidence: float
    edge: float
    kelly_fraction: float
    features: dict[str, Any]
    prediction: Prediction
    execution_result: ExecutionResult | None = None


@dataclass
class StrategyStats:
    """Running strategy performance stats."""

    total_signals: int = 0
    signals_executed: int = 0
    signals_filtered: int = 0
    signals_risk_rejected: int = 0
    total_pnl: Decimal = Decimal("0")
    win_count: int = 0
    loss_count: int = 0
    avg_confidence: float = 0
    avg_edge: float = 0


class TradingStrategy:
    """
    Main AI trading strategy.

    Scans markets, generates signals, and executes trades.
    """

    def __init__(
        self,
        model: PredictionModel,
        feature_engine: FeatureEngine,
        execution_engine: ExecutionEngine,
        risk_manager: RiskManager,
        *,
        strategy_id: str = "default",
        min_confidence: float = 0.60,
        min_edge: float = 0.05,
        kelly_fraction: float = 0.25,
        max_positions: int = 20,
        scan_interval: float = 30.0,
    ):
        self._model = model
        self._features = feature_engine
        self._execution = execution_engine
        self._risk = risk_manager
        self._strategy_id = strategy_id
        self._min_confidence = min_confidence
        self._min_edge = min_edge
        self._kelly_fraction = kelly_fraction
        self._max_positions = max_positions
        self._scan_interval = scan_interval
        self._running = False
        self._scan_task: asyncio.Task | None = None
        self._stats = StrategyStats()

    @property
    def stats(self) -> StrategyStats:
        return self._stats

    @property
    def strategy_id(self) -> str:
        return self._strategy_id

    async def start(self) -> None:
        """Start the AI trading loop."""
        self._running = True
        self._scan_task = asyncio.create_task(
            self._scan_loop(), name=f"strategy_{self._strategy_id}"
        )
        log.info(
            "strategy_started",
            strategy_id=self._strategy_id,
            model=self._model.name,
            min_confidence=self._min_confidence,
            min_edge=self._min_edge,
            kelly=self._kelly_fraction,
        )

    async def stop(self) -> None:
        """Stop the trading loop."""
        self._running = False
        if self._scan_task and not self._scan_task.done():
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                pass
        log.info("strategy_stopped", strategy_id=self._strategy_id)

    async def _scan_loop(self) -> None:
        """Main loop: scan markets → predict → execute."""
        try:
            while self._running:
                try:
                    await self._scan_and_trade()
                except Exception as e:
                    log.error("strategy_scan_error", error=str(e))
                await asyncio.sleep(self._scan_interval)
        except asyncio.CancelledError:
            return

    async def _scan_and_trade(self) -> None:
        """One full scan cycle."""
        start = time.monotonic()

        # Get active markets
        markets = market_cache.get_active()
        if not markets:
            return

        # Filter to tradeable markets
        candidates = self._filter_candidates(markets)
        if not candidates:
            return

        # Compute features
        features_list = [self._features.compute(m) for m in candidates]

        # Batch predict
        predictions = self._model.predict_batch(features_list)

        # Generate decisions
        decisions: list[StrategyDecision] = []
        for market, features, pred in zip(candidates, features_list, predictions):
            decision = self._evaluate_signal(market, features, pred)
            if decision:
                decisions.append(decision)

        # Execute decisions
        for decision in decisions:
            result = await self._execute_decision(decision)
            decision.execution_result = result

        elapsed = (time.monotonic() - start) * 1000
        if decisions:
            log.info(
                "scan_complete",
                strategy_id=self._strategy_id,
                candidates=len(candidates),
                signals=len(decisions),
                elapsed_ms=round(elapsed, 2),
            )

    def _filter_candidates(self, markets: list[Market]) -> list[Market]:
        """Filter markets to only tradeable candidates."""
        candidates = []
        for m in markets:
            if m.status not in (MarketStatus.ACTIVE, MarketStatus.OPEN):
                continue
            # Skip markets with no price data
            if m.yes_bid is None and m.yes_ask is None and m.last_price is None:
                continue
            # Skip already maxed positions
            from app.pipeline.portfolio_tracker import portfolio_state
            pos = portfolio_state.positions.get(m.ticker)
            if pos and abs(pos.position or 0) >= self._risk.limits.max_position_size:
                continue
            candidates.append(m)
        return candidates[:500]  # Cap at 500 to limit compute

    def _evaluate_signal(
        self,
        market: Market,
        features: MarketFeatures,
        prediction: Prediction,
    ) -> StrategyDecision | None:
        """
        Evaluate a prediction and decide whether to trade.

        Returns StrategyDecision if signal is strong enough, else None.
        """
        self._stats.total_signals += 1

        # Check confidence threshold
        if prediction.confidence < self._min_confidence:
            self._stats.signals_filtered += 1
            return None

        # Check edge threshold
        if abs(prediction.edge) < self._min_edge:
            self._stats.signals_filtered += 1
            return None

        # Kelly criterion position sizing
        kelly = self._kelly_size(prediction.confidence, prediction.edge)
        if kelly <= 0:
            self._stats.signals_filtered += 1
            return None

        # Determine order params
        side = OrderSide.YES if prediction.side == "yes" else OrderSide.NO
        action = OrderAction.BUY  # Always buying for now

        # Price: use midpoint slightly improved for fill probability
        mid = features.midpoint
        if side == OrderSide.YES:
            price_cents = int(min(mid + 0.01, 0.99) * 100)
        else:
            price_cents = int(max((1 - mid) + 0.01, 0.01) * 100)

        # Count: kelly fraction * max position size
        count = max(1, int(kelly * self._risk.limits.max_position_size))

        # Update running stats
        self._stats.avg_confidence = (
            (self._stats.avg_confidence * (self._stats.total_signals - 1) + prediction.confidence)
            / self._stats.total_signals
        )
        self._stats.avg_edge = (
            (self._stats.avg_edge * (self._stats.total_signals - 1) + abs(prediction.edge))
            / self._stats.total_signals
        )

        return StrategyDecision(
            ticker=market.ticker,
            side=prediction.side,
            action="buy",
            count=count,
            price_cents=price_cents,
            confidence=prediction.confidence,
            edge=prediction.edge,
            kelly_fraction=kelly,
            features=features.to_dict(),
            prediction=prediction,
        )

    def _kelly_size(self, confidence: float, edge: float) -> float:
        """
        Kelly criterion for optimal position sizing.

        f* = (bp - q) / b
        where:
          b = net odds received on the bet (edge/cost)
          p = probability of winning
          q = probability of losing (1 - p)

        We use a fractional Kelly (configurable) for safety.
        """
        p = confidence
        q = 1 - p
        if edge <= 0 or p <= 0.5:
            return 0

        # Simplified Kelly for binary contracts
        b = edge / max(1 - confidence, 0.01)
        kelly = (b * p - q) / max(b, 0.01)

        # Apply fractional Kelly
        adjusted = max(0, kelly * self._kelly_fraction)

        # Cap at 1.0
        return min(adjusted, 1.0)

    async def _execute_decision(self, decision: StrategyDecision) -> ExecutionResult:
        """Submit an order from a strategy decision."""
        # Log signal to DB
        signal_id = await self._log_signal(decision)

        # Execute
        result = await self._execution.execute(
            ticker=decision.ticker,
            side=OrderSide.YES if decision.side == "yes" else OrderSide.NO,
            action=OrderAction.BUY,
            count=decision.count,
            price_cents=decision.price_cents,
            order_type=OrderType.LIMIT,
            strategy_id=self._strategy_id,
            signal_id=signal_id,
        )

        if result.success:
            self._stats.signals_executed += 1
        elif not result.risk_check_passed:
            self._stats.signals_risk_rejected += 1
        else:
            self._stats.signals_filtered += 1

        return result

    async def _log_signal(self, decision: StrategyDecision) -> int | None:
        """Persist AI signal to database. Returns signal ID."""
        try:
            factory = get_session_factory()
            async with factory() as session:
                signal = AISignal(
                    ticker=decision.ticker,
                    strategy_id=self._strategy_id,
                    model_name=self._model.name,
                    model_version=self._model.version,
                    predicted_side=decision.side,
                    confidence=Decimal(str(round(decision.confidence, 6))),
                    predicted_edge=Decimal(str(round(decision.edge, 6))),
                    kelly_fraction=Decimal(str(round(decision.kelly_fraction, 6))),
                    recommended_count=decision.count,
                    recommended_price_cents=decision.price_cents,
                    features=decision.features,
                )
                session.add(signal)
                await session.commit()
                await session.refresh(signal)
                return signal.id
        except Exception as e:
            log.error("signal_log_failed", error=str(e))
            return None
