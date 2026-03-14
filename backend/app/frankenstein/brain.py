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
from pathlib import Path
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
from app.frankenstein.categories import CategoryStrategyRegistry
from app.kalshi.models import Market, MarketStatus, OrderAction, OrderSide, OrderType
from app.logging_config import get_logger
from app.pipeline import market_cache
from app.engine.advanced_risk import AdvancedRiskManager
from app.production import SQLiteStore, ExchangeSchedule, HealthMonitor

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
    last_scan_debug: dict = field(default_factory=dict)


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
        self.categories = CategoryStrategyRegistry()
        self.scheduler = FrankensteinScheduler()

        # Phase 10: Production hardening
        _persist_dir = str(Path(self.config.memory_persist_path).parent)
        self._sqlite = SQLiteStore(db_path=f"{_persist_dir}/frankenstein.db")
        self._health = HealthMonitor()
        self._schedule = ExchangeSchedule()

        # Phase 7: Advanced portfolio risk manager
        self._adv_risk = AdvancedRiskManager()

        # Sports components (injected by main.py)
        self._sports_detector = None
        self._odds_client = None
        self._sports_feat = None
        self._sports_predictor = None
        self._sports_risk = None
        self._live_engine = None
        self._sports_monitor = None
        self._sports_only = True  # default: only trade sports

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

        # Auto-bootstrap if model is untrained (cold-start fix)
        if self._state.model_version == "untrained":
            asyncio.create_task(
                self._auto_bootstrap(),
                name="frankenstein_bootstrap",
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
        """One full scan cycle: manage positions → find opportunities → trade."""
        start = time.monotonic()
        self._state.total_scans += 1

        # Phase 10: Exchange schedule check — skip during overnight/low-liquidity
        should_trade, session = ExchangeSchedule.should_trade()
        if not should_trade:
            log.debug("scan_skipped_schedule", reason=session)
            return

        # Liquidity factor for position sizing adjustment
        liquidity = ExchangeSchedule.liquidity_factor()

        # 1. Get active markets
        markets = market_cache.get_active()
        if not markets:
            return

        # ── PHASE 2: Manage existing positions (exits) ────
        await self._manage_positions(markets)

        # 2. Filter candidates
        candidates = self._filter_candidates(markets)
        if not candidates:
            return

        # 3. Compute features for all candidates
        features_list = [self._features.compute(m) for m in candidates]

        # 4. Batch predict
        predictions = self._model.predict_batch(features_list)

        # 5. Evaluate each signal through adaptive strategy
        # Phase 9: Collect all valid signals, then rank by expected value
        params = self.strategy.params
        signals_generated = 0
        trades_executed = 0
        trades_rejected = 0
        trade_candidates: list[dict[str, Any]] = []

        for market, features, prediction in zip(candidates, features_list, predictions):
            # Phase 8: Apply category-specific adjustments
            prediction, cat_adj = self.categories.adjust_prediction(
                prediction, features,
                market_title=market.title or "",
                category_hint=market.category or "",
            )

            # 🏀 Sports: use sports predictor (Vegas baseline) if available
            sports_pred = None
            sports_features = None
            if self._sports_detector and self._sports_predictor and self._sports_feat:
                info = self._sports_detector.detect(market)
                if info.is_sports:
                    sports_features = self._sports_feat.compute(market, features)
                    sports_pred = self._sports_predictor.predict(sports_features, features)

            # If sports predictor gave a signal, use it (override base model)
            if sports_pred is not None:
                prediction = sports_pred.to_base_prediction()
                # Sports risk check
                if self._sports_risk and self._sports_detector:
                    info = self._sports_detector.detect(market)
                    passed, reason = self._sports_risk.check(
                        ticker=market.ticker,
                        event_ticker=market.event_ticker,
                        sport_id=info.sport_id,
                        count=1,
                        price_cents=int(features.midpoint * 100),
                        is_live=info.is_live,
                        edge=prediction.edge,
                    )
                    if not passed:
                        continue

            # Apply adaptive thresholds
            # 🏀 Sports markets get slightly relaxed thresholds when
            # no Vegas data is available (base model is still useful)
            effective_min_conf = params.min_confidence
            effective_min_edge = params.min_edge
            if self._sports_only and sports_pred is None:
                # Without Vegas, base model produces smaller edges.
                # Lower threshold so we can at least paper trade and learn.
                effective_min_conf = min(params.min_confidence, 0.50)
                effective_min_edge = min(params.min_edge, 0.015)

            if prediction.confidence < effective_min_conf:
                continue
            if abs(prediction.edge) < effective_min_edge:
                continue

            signals_generated += 1
            self._state.total_signals += 1

            # Kelly criterion position sizing (binary contract formula)
            kelly = self._kelly_size(prediction, features, params)
            if kelly <= 0:
                continue

            # Phase 7: Adjust Kelly with advanced risk (drawdown/position scaling)
            kelly = self._adv_risk.adjusted_kelly(kelly)

            # Phase 10: Scale by liquidity (reduce size in low-liquidity sessions)
            kelly *= liquidity

            count = max(1, int(kelly * params.max_position_size))
            price_cents = self._compute_price(prediction, features)

            # Phase 9: Expected value for ranking
            # EV = edge * count * (1 - cost) — expected profit per trade
            cost_frac = price_cents / 100.0
            ev = abs(prediction.edge) * count * (1.0 - cost_frac)

            trade_candidates.append({
                "market": market,
                "prediction": prediction,
                "features": features,
                "count": count,
                "price_cents": price_cents,
                "kelly": kelly,
                "ev": ev,
            })

        # Phase 9: Rank by expected value and take top opportunities
        # ── Strategy Engine Signals ─────────────────────────────────
        # Merge signals from the pre-built strategy engine alongside
        # the model-based signals evaluated above.
        try:
            from app.state import state as _app_state

            if _app_state.strategy_engine:
                from app.pipeline.portfolio_tracker import portfolio_state as _ps

                balance_cents = _ps.balance_cents or 1000000
                strat_signals = _app_state.strategy_engine.scan_all_markets(
                    candidates,
                    {m.ticker: self._features.compute(m) for m in candidates},
                    {m.ticker: pred for m, pred in zip(candidates, predictions)},
                    balance_cents,
                )
                for sig in strat_signals[:20]:
                    # Avoid duplicate tickers already in trade_candidates
                    existing_tickers = {c["market"].ticker for c in trade_candidates}
                    if sig.ticker in existing_tickers:
                        continue

                    # Find corresponding market
                    market_match = next((m for m in candidates if m.ticker == sig.ticker), None)
                    if not market_match:
                        continue

                    feat = self._features.compute(market_match)
                    pred_for_sig = Prediction(
                        predicted_prob=sig.confidence,
                        confidence=sig.confidence,
                        side=sig.side,
                        edge=sig.edge,
                        model_name=sig.strategy,
                    )

                    count = max(1, sig.recommended_count)
                    price_cents = self._compute_price(pred_for_sig, feat)
                    cost_frac = price_cents / 100.0
                    ev = abs(sig.edge) * count * (1.0 - cost_frac)

                    trade_candidates.append({
                        "market": market_match,
                        "prediction": pred_for_sig,
                        "features": feat,
                        "count": count,
                        "price_cents": price_cents,
                        "kelly": sig.edge * 0.25,
                        "ev": ev,
                    })
                    signals_generated += 1
                    self._state.total_signals += 1
        except Exception as e:
            log.debug("strategy_engine_merge_error", error=str(e))

        trade_candidates.sort(key=lambda c: c["ev"], reverse=True)
        max_trades_per_scan = min(
            params.max_simultaneous_positions - self._count_open_positions(),
            5,  # cap at 5 new trades per scan cycle
        )

        # Debug: record scan state
        scan_debug = {
            "candidates": len(candidates),
            "trade_candidates": len(trade_candidates),
            "max_trades": max_trades_per_scan,
            "open_positions": self._count_open_positions(),
            "signals": signals_generated,
            "portfolio_rejections": 0,
            "exec_rejections": 0,
            "exec_successes": 0,
            "top_candidates": [],
        }

        for candidate in trade_candidates[:max(max_trades_per_scan, 0)]:
            market = candidate["market"]
            prediction = candidate["prediction"]
            features = candidate["features"]
            count = candidate["count"]
            price_cents = candidate["price_cents"]

            # Phase 7: Portfolio-level risk check before trade
            passed, reject_reason = self._adv_risk.portfolio_check(
                ticker=market.ticker,
                count=count,
                price_cents=price_cents,
                event_ticker=getattr(market, "event_ticker", ""),
                category=getattr(market, "category", ""),
            )
            if not passed:
                trades_rejected += 1
                self._state.total_trades_rejected += 1
                scan_debug["portfolio_rejections"] += 1
                scan_debug["top_candidates"].append({"ticker": market.ticker, "stage": "portfolio_rejected", "reason": reject_reason, "count": count, "price": price_cents})
                log.info("portfolio_risk_rejected", ticker=market.ticker, reason=reject_reason, count=count, price=price_cents)
                continue

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
                scan_debug["exec_successes"] += 1
                scan_debug["top_candidates"].append({"ticker": market.ticker, "stage": "executed", "order_id": result.order_id})

                # Phase 7: Register position with advanced risk manager
                self._adv_risk.register_position(
                    ticker=market.ticker,
                    event_ticker=getattr(market, "event_ticker", ""),
                    category=getattr(market, "category", ""),
                    side=prediction.side,
                    count=count,
                    cost_cents=count * price_cents,
                    hours_to_expiry=features.hours_to_expiry,
                )

                # 🏀 Register with sports risk manager
                if self._sports_risk and self._sports_detector:
                    info = self._sports_detector.detect(market)
                    if info.is_sports:
                        self._sports_risk.register_position(
                            ticker=market.ticker,
                            event_ticker=market.event_ticker,
                            sport_id=info.sport_id,
                            cost_cents=count * price_cents,
                            is_live=info.is_live,
                        )

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

                # Phase 10: Persist to SQLite
                try:
                    self._sqlite.save_trade({
                        "trade_id": result.order_id or f"{market.ticker}_{int(time.time())}",
                        "ticker": market.ticker,
                        "timestamp": time.time(),
                        "predicted_side": prediction.side,
                        "confidence": prediction.confidence,
                        "predicted_prob": prediction.predicted_prob,
                        "edge": prediction.edge,
                        "action": "buy",
                        "count": count,
                        "price_cents": price_cents,
                        "total_cost_cents": count * price_cents,
                        "order_id": result.order_id or "",
                        "model_version": self.learner.current_version,
                    })
                except Exception as e:
                    log.debug("sqlite_save_error", error=str(e))
            else:
                trades_rejected += 1
                self._state.total_trades_rejected += 1
                err = getattr(result, 'error', None) or getattr(result, 'risk_rejection_reason', None) or 'unknown'
                scan_debug["exec_rejections"] += 1
                scan_debug["top_candidates"].append({"ticker": market.ticker, "stage": "exec_rejected", "error": err, "count": count, "price": price_cents})
                log.info("execute_trade_rejected", ticker=market.ticker, error=err, count=count, price=price_cents)

        self._state.last_scan_debug = scan_debug
        elapsed = (time.monotonic() - start) * 1000
        self._state.current_scan_time_ms = elapsed
        self._state.last_scan_time = time.time()

        if signals_generated > 0:
            log.info(
                "🧟 SCAN",
                candidates=len(candidates),
                signals=signals_generated,
                trade_candidates=len(trade_candidates),
                max_trades=max_trades_per_scan,
                executed=trades_executed,
                rejected=trades_rejected,
                ms=f"{elapsed:.1f}",
                gen=self._state.generation,
            )

    # ── Trade Execution ───────────────────────────────────────────────

    async def _manage_positions(self, markets: list[Market]) -> None:
        """
        Active position management — decide whether to hold or exit.

        Exit triggers:
          1. Stop-loss: position lost too much → cut losses
          2. Take-profit: position reached target → lock gains
          3. Edge reversal: model now says the other side → flip
          4. Near-expiry liquidation: uncertain near expiry → close
        """
        from app.pipeline.portfolio_tracker import portfolio_state

        if not portfolio_state.positions:
            return

        params = self.strategy.params
        markets_by_ticker = {m.ticker: m for m in markets}
        exits_executed = 0

        for ticker, pos in list(portfolio_state.positions.items()):
            market = markets_by_ticker.get(ticker)
            if not market:
                continue

            position_count = abs(pos.position or 0) if hasattr(pos, 'position') else 0
            if position_count == 0:
                continue

            # Determine our side and current market value
            # pos.position > 0 means YES contracts, < 0 means NO
            our_side = "yes" if (pos.position or 0) > 0 else "no"

            # Get current features and prediction
            features = self._features.compute(market)
            prediction = self._model.predict(features)

            mid = features.midpoint
            if mid <= 0 or mid >= 1:
                continue

            # Estimate entry price from recorded trades
            entry_price = self._estimate_entry_price(ticker)
            if entry_price <= 0:
                continue

            # Current value and P&L
            if our_side == "yes":
                current_value = mid
                unrealized_pnl_pct = (current_value - entry_price) / entry_price if entry_price > 0 else 0
            else:
                current_value = 1.0 - mid
                unrealized_pnl_pct = (current_value - entry_price) / entry_price if entry_price > 0 else 0

            should_exit = False
            exit_reason = ""

            # ── Stop-loss check ───────────────────────────
            stop_loss_pct = getattr(params, 'stop_loss_pct', 0.20) or 0.20
            # 🏀 Tighter stop-loss for live sports positions
            if self._sports_detector and self._sports_risk:
                info = self._sports_detector.detect(market)
                if info.is_sports:
                    stop_loss_pct = self._sports_risk.get_stop_loss(info.is_live)
            if unrealized_pnl_pct < -stop_loss_pct:
                should_exit = True
                exit_reason = f"stop_loss ({unrealized_pnl_pct:.1%})"

            # ── Take-profit check ─────────────────────────
            take_profit_pct = getattr(params, 'take_profit_pct', 0.50) or 0.50
            if unrealized_pnl_pct > take_profit_pct:
                should_exit = True
                exit_reason = f"take_profit ({unrealized_pnl_pct:.1%})"

            # ── Edge reversal check ───────────────────────
            if not should_exit:
                if our_side == "yes" and prediction.side == "no" and prediction.confidence > 0.60:
                    should_exit = True
                    exit_reason = f"edge_reversal (now predicts NO @ {prediction.confidence:.2f})"
                elif our_side == "no" and prediction.side == "yes" and prediction.confidence > 0.60:
                    should_exit = True
                    exit_reason = f"edge_reversal (now predicts YES @ {prediction.confidence:.2f})"

            # ── Near-expiry liquidation ───────────────────
            if not should_exit and features.hours_to_expiry < 2.0:
                # Close uncertain positions near expiry
                if 0.35 < mid < 0.65:
                    should_exit = True
                    exit_reason = f"near_expiry_uncertain ({features.hours_to_expiry:.1f}h)"

            # ── Execute exit ──────────────────────────────
            if should_exit:
                result = await self._execute_exit(
                    market=market,
                    side=our_side,
                    count=position_count,
                    reason=exit_reason,
                )
                if result and result.success:
                    exits_executed += 1
                    self._state.total_trades_executed += 1
                    # Phase 7: Remove from portfolio risk tracker
                    self._adv_risk.remove_position(ticker)
                    # 🏀 Remove from sports risk tracker
                    if self._sports_risk:
                        self._sports_risk.remove_position(ticker)

        if exits_executed > 0:
            log.info("🧟📤 EXITS", count=exits_executed)

    async def _execute_exit(
        self,
        market: Market,
        side: str,
        count: int,
        reason: str,
    ) -> ExecutionResult | None:
        """Execute a sell order to exit a position."""
        try:
            order_side = OrderSide.YES if side == "yes" else OrderSide.NO
            mid = float(market.midpoint or market.last_price or 50) / 100 if isinstance(market.midpoint, int) else float(market.midpoint or market.last_price or 0.50)

            # Price at or slightly below mid for quick execution
            if side == "yes":
                exit_price = max(int(mid * 100) - 1, 1)
            else:
                exit_price = max(int((1.0 - mid) * 100) - 1, 1)

            result = await self._execution.execute(
                ticker=market.ticker,
                side=order_side,
                action=OrderAction.SELL,
                count=count,
                price_cents=exit_price,
                order_type=OrderType.LIMIT,
                strategy_id="frankenstein_exit",
                signal_id=None,
            )

            if result and result.success:
                log.info(
                    "🧟📤 EXIT_EXECUTED",
                    ticker=market.ticker,
                    side=side,
                    count=count,
                    price=f"{exit_price}¢",
                    reason=reason,
                )

                # Record exit in memory
                self.memory.record_trade(
                    ticker=market.ticker,
                    prediction=Prediction(
                        side=side, confidence=0.0, predicted_prob=0.5,
                        edge=0.0, model_name="exit", model_version="exit",
                    ),
                    features=self._features.compute(market),
                    action="sell",
                    count=count,
                    price_cents=exit_price,
                    order_id=result.order_id or "",
                    latency_ms=result.latency_ms,
                )

            return result
        except Exception as e:
            log.error("exit_failed", ticker=market.ticker, error=str(e))
            return None

    def _estimate_entry_price(self, ticker: str) -> float:
        """Estimate our average entry price for a ticker from memory."""
        trades = self.memory.get_recent_trades(n=1000, ticker=ticker)
        buy_trades = [t for t in trades if t.action == "buy"]
        if not buy_trades:
            return 0.0
        total_cost = sum(t.price_cents for t in buy_trades)
        return (total_cost / len(buy_trades)) / 100.0

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
        """Filter markets to tradeable candidates — SPORTS FOCUSED."""
        params = self.strategy.params
        candidates = []

        # Get spread limit from execution risk manager
        max_spread = 40  # default
        if self._execution._risk_manager:
            max_spread = self._execution._risk_manager.limits.max_spread_cents

        for m in markets:
            if m.status != MarketStatus.ACTIVE:
                continue
            if m.yes_bid is None and m.yes_ask is None and m.last_price is None:
                continue

            # Pre-filter: skip markets with spread wider than risk limit
            if m.spread is not None:
                spread_cents = int(m.spread * 100) if isinstance(m.spread, float) else m.spread
                if spread_cents > max_spread:
                    continue

            # 🏀 Sports-only mode: skip non-sports markets
            if self._sports_only and self._sports_detector:
                if not self._sports_detector.is_sports_market(m):
                    continue

            # Skip if we're at position limit for this market
            from app.pipeline.portfolio_tracker import portfolio_state
            pos = portfolio_state.positions.get(m.ticker)
            if pos and abs(pos.position or 0) >= params.max_position_size:
                continue

            candidates.append(m)

        return candidates[:self.config.max_candidates]

    def _count_open_positions(self) -> int:
        """Count current open positions for portfolio limit enforcement."""
        from app.pipeline.portfolio_tracker import portfolio_state
        return sum(
            1 for pos in portfolio_state.positions.values()
            if (pos.position or 0) != 0
        )

    def _kelly_size(
        self,
        prediction: Prediction,
        features: MarketFeatures,
        params: StrategyParams,
    ) -> float:
        """
        Kelly criterion for binary contracts.

        Binary contract math:
          Buy at cost c (0-1 range, e.g., 0.40 = 40¢ per contract)
          Win:  receive $1, net profit = (1 - c)
          Lose: lose entire cost c

        Kelly optimal fraction:  f* = (p - c) / (1 - c)
        where p = our estimated probability of winning the bet.

        We then apply *fractional* Kelly (default 0.25 = quarter-Kelly)
        to account for parameter uncertainty — a standard practice.
        """
        mid = features.midpoint

        if prediction.side == "yes":
            p = prediction.predicted_prob          # P(YES settles)
            c = min(mid + 0.01, 0.99)              # approximate cost
        else:
            p = 1.0 - prediction.predicted_prob    # P(NO settles)
            c = min(1.0 - mid + 0.01, 0.99)        # cost of NO contract

        # No edge or degenerate cost — skip
        if p <= c or c <= 0.01 or c >= 0.99:
            return 0.0

        # Kelly: f* = (p - c) / (1 - c)
        kelly = (p - c) / (1.0 - c)

        # Apply fractional Kelly for safety
        adjusted = kelly * params.kelly_fraction

        # Clamp to [0, 1]
        return max(0.0, min(adjusted, 1.0))

    def _compute_price(self, prediction: Prediction, features: MarketFeatures) -> int:
        """
        Compute optimal order price — spread-aware placement.

        Strategy: place orders as maker (inside the spread) when possible
        to capture the spread instead of paying it.

        For BUY YES:  bid at (yes_bid + 1¢) — one tick inside the spread
        For BUY NO:   bid at (no_bid + 1¢)  — one tick inside the spread

        If spread is very tight (≤2¢), cross the spread for immediate fill.
        """
        mid = features.midpoint
        spread_cents = max(int(features.spread * 100), 1)

        if prediction.side == "yes":
            if spread_cents <= 2:
                # Tight spread — just take the ask for guaranteed fill
                price_frac = min(mid + features.spread / 2, 0.99)
            elif spread_cents <= 6:
                # Medium spread — place inside (closer to mid)
                price_frac = min(mid + 0.01, 0.99)
            else:
                # Wide spread — be more aggressive as maker
                # Place at mid - 1¢ to capture spread
                price_frac = max(mid - 0.01, 0.01)
        else:
            # For NO contracts
            no_mid = 1.0 - mid
            if spread_cents <= 2:
                price_frac = min(no_mid + features.spread / 2, 0.99)
            elif spread_cents <= 6:
                price_frac = min(no_mid + 0.01, 0.99)
            else:
                price_frac = max(no_mid - 0.01, 0.01)

        return max(1, min(99, int(price_frac * 100)))

    # ── Scheduled Tasks ───────────────────────────────────────────────

    async def _auto_bootstrap(self) -> None:
        """Auto-bootstrap training data on cold start (runs once at startup)."""
        # Wait for market cache to populate first
        for _ in range(30):
            if market_cache.get_active():
                break
            await asyncio.sleep(2)

        log.info("🧟🧪 AUTO-BOOTSTRAP: Model is untrained, bootstrapping training data...")
        try:
            result = await self.bootstrap_training_data()
            trained = result.get("retrain_result", {}).get("success", False)
            log.info(
                "🧟🧪 AUTO-BOOTSTRAP COMPLETE",
                trained=trained,
                memory=self.memory.total_resolved,
                version=self._state.model_version,
            )
        except Exception as e:
            log.error("auto_bootstrap_failed", error=str(e))

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

        # Phase 10: Record health checks
        try:
            self._health.record_check("scan_loop", self._state.is_alive, f"scans={self._state.total_scans}")
            self._health.record_check("trading", self._state.is_trading and not self._state.is_paused, self._state.pause_reason or "ok")
            self._health.record_check("model", self._state.model_version != "untrained", f"v={self._state.model_version}")
        except Exception:
            pass

        # Phase 10: Persist performance snapshot to SQLite
        try:
            snapshot = self.performance.summary()
            self._sqlite.save_snapshot({
                "timestamp": time.time(),
                "total_pnl": snapshot.get("total_pnl_cents", 0) / 100.0,
                "win_rate": snapshot.get("win_rate", 0),
                "sharpe_ratio": snapshot.get("sharpe_ratio", 0),
                "max_drawdown": snapshot.get("max_drawdown_pct", 0),
                "total_trades": snapshot.get("total_trades", 0),
                "model_version": self._state.model_version,
            })
        except Exception:
            pass

    async def _resolve_outcomes_task(self) -> None:
        """Check for settled markets and resolve pending trades.
        
        FIX #2: Uses Kalshi portfolio settlements API instead of
        checking a non-existent market.result field.  Also checks
        market status == 'settled' via direct API lookup.
        """
        pending = self.memory.get_pending_trades()
        if not pending:
            return

        # Batch-fetch recent settlements from Kalshi
        settlements_by_ticker: dict[str, Any] = {}
        try:
            from app.state import state as _st
            if _st.kalshi_api:
                slist, _ = await _st.kalshi_api.portfolio.list_settlements(limit=200)
                for s in slist:
                    settlements_by_ticker[s.ticker] = s
        except Exception as e:
            log.debug("settlement_fetch_error", error=str(e))

        for trade in pending:
            try:
                # Method 1: Check settlements API
                settlement = settlements_by_ticker.get(trade.ticker)
                if settlement and settlement.market_result is not None:
                    result_str = settlement.market_result.value.lower()
                    correct = trade.predicted_side == result_str

                    if result_str == "void":
                        self.memory.resolve_trade(
                            trade.trade_id, TradeOutcome.CANCELLED,
                        )
                    elif correct:
                        pnl_cents = trade.count * 100 - trade.total_cost_cents
                        self.memory.resolve_trade(
                            trade.trade_id, TradeOutcome.WIN,
                            pnl_cents=pnl_cents, market_result=result_str,
                        )
                        # FIX #7: Report to sports monitor
                        self._report_sports_outcome(trade, pnl_cents)
                    else:
                        pnl_cents = -trade.total_cost_cents
                        self.memory.resolve_trade(
                            trade.trade_id, TradeOutcome.LOSS,
                            pnl_cents=pnl_cents, market_result=result_str,
                        )
                        self._report_sports_outcome(trade, pnl_cents)
                    continue

                # Method 2: Check market status via API
                try:
                    from app.state import state as _st
                    if _st.kalshi_api:
                        mkt = await _st.kalshi_api.markets.get_market(trade.ticker)
                        if mkt.status.value == "settled":
                            # Market settled but we didn't find in settlements
                            # This happens with demo/paper trades
                            # Mark as expired for now (better than permanent pending)
                            self.memory.resolve_trade(
                                trade.trade_id, TradeOutcome.EXPIRED,
                            )
                            continue
                except Exception:
                    pass

                # Method 3: Timeout after 48 hours
                if time.time() - trade.timestamp > 172800:  # 48 hours
                    self.memory.resolve_trade(
                        trade.trade_id, TradeOutcome.EXPIRED,
                    )
            except Exception as e:
                log.debug("outcome_check_error", ticker=trade.ticker, error=str(e))

    def _report_sports_outcome(self, trade: TradeRecord, pnl_cents: int) -> None:
        """FIX #7: Report trade outcome to sports monitor for performance tracking."""
        if not self._sports_monitor or not self._sports_detector:
            return
        try:
            from app.kalshi.models import Market as _MktModel
            # Build a minimal Market-like object for detection
            info = self._sports_detector.detect(
                _MktModel(ticker=trade.ticker, event_ticker=getattr(trade, 'event_ticker', '') or '')
            )
            if info.is_sports:
                self._sports_monitor.record_trade_outcome(
                    sport_id=info.sport_id,
                    strategy=trade.model_version or "vegas_baseline",
                    pnl_cents=pnl_cents,
                    edge=getattr(trade, 'edge', 0.0),
                    is_live=info.is_live,
                )
        except Exception as e:
            log.debug("sports_monitor_report_error", error=str(e))

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

    async def bootstrap_training_data(self) -> dict[str, Any]:
        """
        Bootstrap training data to solve the cold-start problem.

        Tries two methods:
        1. Fetch settled markets from Kalshi (best quality — real outcomes)
        2. Synthesize from active markets (fallback — probabilistic labels)

        After injecting data, triggers an immediate retrain.
        """
        from app.frankenstein.bootstrap import (
            bootstrap_from_settled_markets,
            bootstrap_from_active_markets,
        )

        result: dict[str, Any] = {
            "settled_stats": {},
            "active_stats": {},
            "retrain_result": None,
            "memory_before": self.memory.total_resolved,
        }

        # Method 1: Settled markets (real outcomes)
        try:
            from app.state import state as _st
            if _st.kalshi_api:
                settled_stats = await bootstrap_from_settled_markets(
                    _st.kalshi_api, self.memory,
                    max_markets=1000, min_target=300,
                )
                result["settled_stats"] = settled_stats
            else:
                result["settled_stats"] = {"error": "Kalshi API not available"}
        except Exception as e:
            log.warning("bootstrap_settled_failed", error=str(e))
            result["settled_stats"] = {"error": str(e)}

        # Method 2: Active markets (if settled didn't give enough)
        if self.memory.total_resolved < self.learner.min_samples:
            try:
                active_stats = await bootstrap_from_active_markets(
                    self.memory, count=500,
                )
                result["active_stats"] = active_stats
            except Exception as e:
                log.warning("bootstrap_active_failed", error=str(e))
                result["active_stats"] = {"error": str(e)}

        result["memory_after"] = self.memory.total_resolved

        # Trigger retrain if we have enough data now
        if self.memory.total_resolved >= self.learner.min_samples:
            retrain_result = await self.force_retrain()
            result["retrain_result"] = retrain_result
        else:
            result["retrain_result"] = {
                "success": False,
                "reason": f"Only {self.memory.total_resolved} resolved trades, need {self.learner.min_samples}",
            }

        log.info(
            "🧟🧪 BOOTSTRAP COMPLETE",
            memory_before=result["memory_before"],
            memory_after=result["memory_after"],
            trained=result["retrain_result"].get("success", False) if result["retrain_result"] else False,
        )
        return result

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
            "last_scan_debug": self._state.last_scan_debug,

            # Subsystem status
            "memory": self.memory.stats(),
            "performance": self.performance.summary(),
            "learner": self.learner.stats(),
            "strategy": self.strategy.stats(),
            "scheduler": self.scheduler.stats(),

            # Phase 7+10: Production systems
            "health": self._health.summary(),
            "portfolio_risk": self._adv_risk.portfolio_summary(),
            "exchange_session": ExchangeSchedule.current_session(),
            "liquidity_factor": ExchangeSchedule.liquidity_factor(),

            # 🏀 Sports
            "sports_only_mode": self._sports_only,
            "sports_detector": self._sports_detector.stats() if self._sports_detector else None,
            "sports_risk": self._sports_risk.summary() if self._sports_risk else None,
            "sports_predictor": self._sports_predictor.stats() if self._sports_predictor else None,
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
