"""
Frankenstein — The Brain (Slim Orchestrator). 🧟

After Phase 1 modular split, the Brain is a ~400-line orchestrator
that wires together the extracted modules:

  • EventBus     — async pub/sub for inter-module communication
  • WSBridge     — WebSocket bridge: real-time Kalshi data → EventBus (Phase 2)
  • OrderManager — order placement, pricing, lifecycle, requoting
  • Scanner      — market scanning, signal evaluation, execution
  • Positions    — active position management, exit logic
  • Resolver     — outcome resolution, calibration, category stats

The Brain owns:
  ✓ __init__ (component wiring + EventBus subscriptions)
  ✓ awaken / sleep (lifecycle + WS bridge start/stop)
  ✓ _scan_loop (periodic full scan — poll fallback)
  ✓ _on_ticker_update (reactive fast-path scan — Phase 2)
  ✓ Scheduled task registration
  ✓ status() for dashboard API
  ✓ pause / resume / force_retrain / bootstrap
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.ai.features import FeatureEngine
from app.ai.models import PredictionModel, XGBoostPredictor
from app.engine.execution import ExecutionEngine
from app.engine.risk import RiskManager
from app.engine.advanced_risk import AdvancedRiskManager
from app.frankenstein.categories import CategoryStrategyRegistry
from app.frankenstein.confidence import ConfidenceScorer
from app.frankenstein.constants import (
    CATEGORY_EDGE_CAPS,
    CIRCUIT_BREAKER_COOLDOWN_HOURS,
    CIRCUIT_BREAKER_MIN_ACCURACY,
    CIRCUIT_BREAKER_MIN_TRADES,
    MAX_DAILY_TRADES,
    ROUND_TRIP_FEE_CENTS,
    TAKER_FEE_CENTS,
    USE_MAKER_ORDERS,
    round_trip_fee_pct,
)
from app.frankenstein.event_bus import EventBus, EventType
from app.frankenstein.fill_predictor import FillPredictor
from app.frankenstein.learner import OnlineLearner
from app.frankenstein.memory import TradeMemory, TradeOutcome
from app.frankenstein.order_manager import OrderManager
from app.frankenstein.performance import PerformanceTracker
from app.frankenstein.positions import PositionManager
from app.frankenstein.pretrained import load_pretrained_model, PRETRAINED_PATH
from app.frankenstein.resolver import OutcomeResolver
from app.frankenstein.scanner import MarketScanner
from app.frankenstein.scheduler import FrankensteinScheduler
from app.frankenstein.strategy import AdaptiveStrategy
from app.frankenstein.ws_bridge import WSBridge
from app.frankenstein.capital_allocator import CapitalAllocator
from app.kalshi.models import Market
from app.logging_config import get_logger
from app.pipeline import market_cache
from app.production import SQLiteStore, ExchangeSchedule, HealthMonitor

log = get_logger("frankenstein.brain")


# ── Re-export constants for backward compatibility ───────────────────
# Several external files import these from brain.py directly:
#   routes/frankenstein.py  → round_trip_fee_pct, ROUND_TRIP_FEE_CENTS
#   main.py                 → USE_MAKER_ORDERS, FrankensteinConfig
#   confidence.py           → USE_MAKER_ORDERS
# Keep re-exports so those imports don't break.
__all__ = [
    "Frankenstein",
    "FrankensteinConfig",
    "FrankensteinState",
    "USE_MAKER_ORDERS",
    "ROUND_TRIP_FEE_CENTS",
    "TAKER_FEE_CENTS",
    "CATEGORY_EDGE_CAPS",
    "MAX_DAILY_TRADES",
    "round_trip_fee_pct",
]


@dataclass
class FrankensteinConfig:
    """Configuration for the Frankenstein brain."""

    scan_interval: float = 30.0
    max_candidates: int = 500
    retrain_interval: float = 3600.0
    min_train_samples: int = 50
    retrain_threshold: int = 25
    memory_persist_path: str = "data/frankenstein_memory.json"
    checkpoint_dir: str = "data/models"
    auto_save_interval: float = 1800.0
    performance_snapshot_interval: float = 300.0
    strategy_adaptation_interval: float = 1800.0
    outcome_check_interval: float = 60.0
    max_daily_loss: float = 50.0
    pause_on_degradation: bool = True

    # Phase 2: WebSocket bridge settings
    ws_enabled: bool = True                   # Enable real-time WS feed
    ws_max_subscriptions: int = 500           # Max tickers to track via WS
    ws_requote_debounce_ms: float = 150.0     # Min ms between requote events per ticker (was 200)
    ws_reactive_scan: bool = True             # Enable reactive single-ticker scans

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
    daily_trade_count: int = 0
    daily_trade_date: str = ""
    circuit_breaker_triggered: bool = False
    circuit_breaker_triggered_at: float = 0.0
    pretrained_loaded: bool = False


class Frankenstein:
    """
    🧟 THE FRANKENSTEIN BRAIN 🧟

    Slim orchestrator that wires together the modular subsystems
    and manages lifecycle (awaken → scan loop → sleep).
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
            model=model, memory=self.memory,
            min_samples=self.config.min_train_samples,
            retrain_threshold=self.config.retrain_threshold,
            checkpoint_dir=self.config.checkpoint_dir,
        )
        self.strategy = AdaptiveStrategy(
            memory=self.memory, performance=self.performance,
            adaptation_interval=self.config.strategy_adaptation_interval,
        )
        self.categories = CategoryStrategyRegistry()
        self.scheduler = FrankensteinScheduler()

        # Production hardening
        _persist_dir = str(Path(self.config.memory_persist_path).parent)
        self._sqlite = SQLiteStore(db_path=f"{_persist_dir}/frankenstein.db")
        self._health = HealthMonitor()
        self._schedule = ExchangeSchedule()
        self._adv_risk = AdvancedRiskManager()

        # ── Event Bus ─────────────────────────────────────────────
        self._bus = EventBus()

        # ── Capital Allocator (Phase 3+4) ─────────────────────────
        self._capital = CapitalAllocator(event_bus=self._bus)

        # ── Fill Predictor (Phase 5) ──────────────────────────────
        self._fill_predictor = FillPredictor()

        # ── WebSocket Bridge (Phase 2) ────────────────────────────
        self._ws_bridge = WSBridge(
            event_bus=self._bus,
            feature_engine=feature_engine,
            max_subscriptions=self.config.ws_max_subscriptions,
            requote_debounce_ms=self.config.ws_requote_debounce_ms,
        )
        self._ws_url: str = ""         # Set by main.py before awaken()
        self._ws_auth: Any = None      # KalshiAuth (RSA-PSS signer) — set by main.py

        # ── Order Manager ─────────────────────────────────────────
        self._order_mgr = OrderManager(
            execution_engine=execution_engine,
            feature_engine=feature_engine,
            memory=self.memory,
            event_bus=self._bus,
            capital_allocator=self._capital,
            fill_predictor=self._fill_predictor,
        )

        # ── Outcome Resolver ──────────────────────────────────────
        self._resolver = OutcomeResolver(
            memory=self.memory, model=self._model,
            event_bus=self._bus,
        )

        # ── Position Manager ──────────────────────────────────────
        self._positions = PositionManager(
            model=self._model, feature_engine=feature_engine,
            strategy=self.strategy, order_manager=self._order_mgr,
            adv_risk=self._adv_risk, event_bus=self._bus,
            memory=self.memory,
        )

        # ── Market Scanner ────────────────────────────────────────
        self._scanner = MarketScanner(
            model=self._model, feature_engine=feature_engine,
            execution_engine=execution_engine, strategy=self.strategy,
            memory=self.memory, learner=self.learner,
            performance=self.performance, categories=self.categories,
            order_manager=self._order_mgr, adv_risk=self._adv_risk,
            schedule=self._schedule, event_bus=self._bus,
            capital_allocator=self._capital,
            fill_predictor=self._fill_predictor,
        )
        # Wire scanner's category stats to resolver
        self._scanner._category_stats_ref = self._resolver.category_stats

        # Sports components (injected by main.py)
        self._sports_detector = None
        self._odds_client = None
        self._sports_feat = None
        self._sports_predictor = None
        self._sports_predictor_v2 = None  # Phase 30: enhanced predictor
        self._sports_risk = None
        self._live_engine = None
        self._sports_monitor = None
        self._sports_only = True

        # Category specialist models
        self._category_models: dict[str, XGBoostPredictor] = {}

        # State
        self._state = FrankensteinState()
        self._scan_task: asyncio.Task | None = None
        self._reactive_trades: int = 0  # Phase 2: count of WS-triggered trades

        # ── Wire EventBus subscriptions (Phase 2+3+4) ───────────
        self._bus.subscribe(EventType.FILL_RECEIVED, self._order_mgr.handle_fill)
        self._bus.subscribe(EventType.BOOK_CHANGED, self._order_mgr.handle_book_changed)
        self._bus.subscribe(EventType.CAPITAL_FREED, self._capital.on_capital_freed)
        if self.config.ws_reactive_scan:
            self._bus.subscribe(EventType.TICKER_UPDATE, self._on_ticker_update)

        # Phase 4: Capital recycling — re-scan when capital is freed
        self._capital.set_rescan_callback(self._on_capital_recycled)

        # Legacy aliases — some routes/tests access these directly
        self._pending_orders = self._order_mgr.pending_orders
        self._fill_rate_stats = self._order_mgr.fill_rate_stats
        self._category_stats = self._resolver.category_stats
        self._recently_traded = self._scanner._recently_traded
        self._recently_traded_events = self._scanner._recently_traded_events
        self._trade_cooldown_seconds = self._scanner._trade_cooldown_seconds

        log.info("🧟 FRANKENSTEIN CREATED", config=self.config.to_dict())

    # ── Sports wiring ─────────────────────────────────────────────────

    def _wire_sports(self) -> None:
        """Propagate sports components to sub-modules after main.py injects them."""
        self._scanner._sports_detector = self._sports_detector
        self._scanner._sports_predictor = self._sports_predictor
        self._scanner._sports_feat = self._sports_feat
        self._scanner._sports_risk = self._sports_risk
        self._scanner._sports_only = self._sports_only
        # Phase 30: Wire V2 predictor
        self._scanner._sports_predictor_v2 = getattr(self, '_sports_predictor_v2', None)
        self._positions._sports_detector = self._sports_detector
        self._positions._sports_risk = self._sports_risk
        self._resolver._sports_detector = self._sports_detector
        self._resolver._sports_monitor = self._sports_monitor
        # Phase 30: Wire V2 predictor to resolver for circuit breaker feedback
        self._resolver._sports_predictor_v2 = getattr(self, '_sports_predictor_v2', None)
        self._resolver._sports_risk = self._sports_risk

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def awaken(self) -> None:
        """🧟 Bring Frankenstein to life."""
        if self._state.is_alive:
            log.warning("frankenstein_already_alive")
            return

        self._state.is_alive = True
        self._state.birth_time = time.time()
        self._state.awaken_time = time.time()  # Track session start for circuit breaker
        self._state.is_trading = True

        # Sync session start to performance tracker so adaptation only
        # reacts to THIS session's trades, not stale historical data
        self.performance.session_start_time = self._state.awaken_time

        # Wire sports components to sub-modules
        self._wire_sports()

        # Register scheduled tasks
        self.scheduler.register("retrain", self._retrain_task, self.config.retrain_interval)
        self.scheduler.register("performance_snapshot", self._performance_task, self.config.performance_snapshot_interval)
        self.scheduler.register("adapt_strategy", self._adaptation_task, self.config.strategy_adaptation_interval)
        self.scheduler.register("auto_save", self._save_task, self.config.auto_save_interval)
        self.scheduler.register("health_check", self._health_check_task, 60.0)
        self.scheduler.register("resolve_outcomes", self._resolve_outcomes_task, self.config.outcome_check_interval)

        await self.scheduler.start()

        self._scan_task = asyncio.create_task(self._scan_loop(), name="frankenstein_scan")

        # ── Phase 2: Start WebSocket bridge ───────────────────────
        if self.config.ws_enabled and self._ws_url:
            try:
                await self._ws_bridge.start(
                    ws_url=self._ws_url,
                    auth=self._ws_auth,  # RSA-PSS signer
                )
                # Subscribe to currently active markets
                active_tickers = [m.ticker for m in market_cache.get_active()[:self.config.ws_max_subscriptions]]
                if active_tickers:
                    await self._ws_bridge.subscribe_tickers(active_tickers)
                log.info("🧟🔌 WS bridge started", tickers=len(active_tickers))
            except Exception as e:
                # Phase 28: Detailed error logging — WS is optional but useful
                import traceback
                tb_str = traceback.format_exc()[-500:]
                log.warning("ws_bridge_start_failed",
                            error=str(e),
                            error_type=type(e).__name__,
                            ws_url=self._ws_url,
                            has_auth=bool(self._ws_auth),
                            traceback=tb_str,
                            hint="Falling back to poll-only — Phase 28 poll requoting will handle order management")

        # Register WS subscription refresh (sync subs with active markets every 2 min)
        self.scheduler.register("ws_refresh_subs", self._ws_refresh_task, 120.0)

        # ── Phase 3+4: Capital management tasks ──────────────────
        from app.frankenstein.constants import FILL_RECONCILE_INTERVAL_S
        self.scheduler.register("reconcile_fills", self._reconcile_fills_task, FILL_RECONCILE_INTERVAL_S)
        self.scheduler.register("sync_capital", self._sync_capital_task, 30.0)
        # ── Phase 5: Fill predictor periodic refit ─────────────
        self.scheduler.register("refit_fill_predictor", self._refit_fill_predictor_task, 1800.0)
        # Initial capital sync
        try:
            from app.pipeline.portfolio_tracker import portfolio_state
            self._capital.sync_balance(portfolio_state.balance_cents)
            log.info("💰 Capital allocator initialized",
                     balance=f"${portfolio_state.balance_cents / 100:.2f}")
        except Exception:
            pass

        # Sync existing positions to risk manager (Issue #5)
        try:
            from app.state import state as _st
            if _st.paper_simulator:
                positions = _st.paper_simulator.get_positions()
                pos_dicts = [
                    {
                        "ticker": p.ticker,
                        "count": abs(p.position),
                        "cost_cents": p.market_exposure,
                        "side": "yes" if p.position > 0 else "no",
                    }
                    for p in positions
                ]
                if pos_dicts:
                    self._adv_risk.sync_positions(pos_dicts)
        except Exception as e:
            log.debug("position_risk_sync_error", error=str(e))

        # Deploy purge (one-time)
        import os
        _purge_flag = os.environ.get("FRANKENSTEIN_PURGE_ON_START", "").strip().lower()
        if _purge_flag in ("1", "true", "yes"):
            log.warning("🧟🗑️ PURGE FLAG SET — wiping poisoned bootstrap data")
            purge_result = self.memory.purge_bootstrap_data()
            log.warning("🧟🗑️ PURGE COMPLETE", **purge_result)
            try:
                ckpt_dir = Path(self.config.checkpoint_dir)
                if ckpt_dir.exists():
                    for f in ckpt_dir.glob("*.pkl"):
                        f.unlink()
                    log.warning("🧟🗑️ OLD CHECKPOINTS DELETED")
            except Exception as e:
                log.error("checkpoint_purge_failed", error=str(e))

        # Checkpoint restoration
        self._try_load_latest_checkpoint()

        # Phase 25b: Validate the loaded checkpoint has real training data.
        # If the checkpoint was trained on garbage data (e.g. all-breakeven
        # churn trades), its predictions are degenerate and worse than
        # the heuristic fallback.  Reset to untrained in that case.
        if self._model.is_trained and self.is_in_learning_mode:
            # Model claims trained but we have < MIN_TRAINING_SAMPLES usable trades.
            # The checkpoint is likely stale/degenerate.  Reset to heuristic.
            log.warning(
                "🧟⚠️ STALE CHECKPOINT DETECTED — loaded model but no usable "
                "training data.  Resetting to heuristic mode.",
                model_version=self._state.model_version,
            )
            self._model._model = None  # Reset to untrained → use heuristic
            self._model._train_samples = 0
            self._state.model_version = "heuristic"
            self._state.pretrained_loaded = False

        # Pretrained model fallback
        if not self._model.is_trained:
            pretrained_result = load_pretrained_model()
            if pretrained_result is not None:
                try:
                    xgb_model, calibration_tracker, metadata = pretrained_result
                    self._model._model = xgb_model
                    if calibration_tracker:
                        self._model._calibration = calibration_tracker
                    self._model._train_samples = metadata.get("train_samples", 5000)
                    self._model._is_trained = True
                    self._model._version = "pretrained_v1"
                    self._state.pretrained_loaded = True
                    self._state.model_version = self._model._version
                    log.info("🧟🧠 PRETRAINED MODEL LOADED",
                             version=self._model._version,
                             train_samples=self._model._train_samples)
                except Exception as e:
                    log.error("pretrained_load_failed", error=str(e))

        # ── Phase 26: Synchronous startup bootstrap ─────────────────
        # The model MUST be trained before trading starts.  Previous approach
        # (fire-and-forget asyncio.create_task) often failed silently, leaving
        # the system trading with heuristic-only forever.
        #
        # New approach:
        # 1. Clean stale memory (old churn trades with no usable labels)
        # 2. Bootstrap from 500+ settled Kalshi markets (known outcomes)
        # 3. Train XGBoost synchronously → model is ready from first scan
        # 4. Fall back to heuristic ONLY if bootstrap fails (network error etc.)
        if not self._model.is_trained:
            try:
                await self._startup_bootstrap()
            except Exception as e:
                log.error("startup_bootstrap_failed", error=str(e),
                          hint="System will trade with heuristic predictions")

        # Load pretrained data for fine-tuning (if pretrained model loaded)
        if self._state.pretrained_loaded:
            try:
                self.learner.load_pretrained_data()
            except Exception as e:
                log.warning("pretrained_data_load_skip", error=str(e))

        # Load backtest recommendations
        try:
            import json
            _rec_path = Path("data/models/backtest_recommendations.json")
            if _rec_path.exists():
                with open(_rec_path) as f:
                    recs = json.load(f)
                if recs.get("recommended_min_edge"):
                    self.strategy.params.min_edge = max(recs["recommended_min_edge"], 0.03)
                if recs.get("recommended_daily_cap"):
                    # Store as runtime override — never mutate module-level constants
                    self._runtime_daily_trade_cap = min(recs["recommended_daily_cap"], 50)
                    log.info("backtest_daily_cap_loaded", cap=self._runtime_daily_trade_cap)
                if recs.get("category_edge_caps"):
                    for cat, cap in recs["category_edge_caps"].items():
                        CATEGORY_EDGE_CAPS[cat] = cap
                # Enforce strategy bounds after loading external recommendations
                self.strategy._clamp_all_params()
        except Exception:
            pass

        log.info("🧟⚡ FRANKENSTEIN IS ALIVE!",
                 model=self._model.name, model_version=self._model.version)

    async def sleep(self) -> None:
        """Put Frankenstein to sleep (graceful shutdown)."""
        if not self._state.is_alive:
            return
        self._state.is_alive = False
        self._state.is_trading = False

        # Stop WS bridge first (no more real-time events)
        try:
            await self._ws_bridge.stop()
        except Exception:
            pass

        if self._scan_task and not self._scan_task.done():
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                pass

        await self.scheduler.stop()
        self.memory.save()

        log.info("🧟💤 FRANKENSTEIN SLEEPS",
                 uptime=f"{time.time() - self._state.birth_time:.0f}s",
                 total_scans=self._state.total_scans,
                 total_trades=self._state.total_trades_executed,
                 reactive_trades=self._reactive_trades)

    # ── Main Scan Loop ────────────────────────────────────────────────

    async def _scan_loop(self) -> None:
        """Main trading loop — delegates to Scanner and PositionManager."""
        try:
            while self._state.is_alive:
                scan_start = time.monotonic()
                try:
                    if self._state.is_trading and not self._state.is_paused:
                        # Phase 21: Check resting maker orders for fills
                        try:
                            from app.state import state as _st
                            if _st.paper_simulator and hasattr(_st.paper_simulator, "check_resting_fills"):
                                _st.paper_simulator.check_resting_fills()
                        except Exception:
                            pass

                        # Manage positions first
                        markets = market_cache.get_active()
                        if markets:
                            await self._positions.manage(markets)

                            # Update unrealized PnL for risk tracking (Issue #13)
                            market_by_ticker = {m.ticker: m for m in markets}
                            for ticker in list(self._adv_risk._position_risks.keys()):
                                m = market_by_ticker.get(ticker)
                                if m:
                                    mid = float(m.midpoint or m.last_price or 0)
                                    if isinstance(mid, int):
                                        mid = mid / 100
                                    self._adv_risk.update_position_price(ticker, int(mid * 100))

                        # Scan for new opportunities
                        scan_debug = await self._scanner.scan(self._state)
                        self._state.last_scan_debug = scan_debug
                except Exception as e:
                    import traceback
                    tb_str = traceback.format_exc()[-500:]
                    log.error("scan_error", error=str(e), traceback=tb_str)
                    self._state.last_scan_debug = {
                        "exit": "scan_exception", "error": str(e), "traceback": tb_str,
                    }

                interval = self.strategy.params.scan_interval
                elapsed = time.monotonic() - scan_start
                await asyncio.sleep(max(1.0, interval - elapsed))
        except asyncio.CancelledError:
            return

    # ── Phase 2: Reactive Event Handlers ──────────────────────────────

    async def _on_ticker_update(self, event: Any) -> None:
        """
        React to real-time ticker updates from the WS bridge.

        Triggers a fast-path single-ticker scan when a price change
        is detected. This is the heart of the reactive architecture:
        instead of waiting for the next 30s poll, we evaluate
        immediately when the book moves.
        """
        if not self._state.is_alive or not self._state.is_trading:
            return
        if self._state.is_paused:
            return

        ticker = event.data.get("ticker", "")
        if not ticker:
            return

        try:
            result = await self._scanner.scan_ticker(
                ticker, self._state,
                book_data=event.data,
            )
            if result and result.get("stage") == "executed_reactive":
                self._reactive_trades += 1
        except Exception as e:
            log.debug("reactive_scan_error", ticker=ticker, error=str(e))

    async def _ws_refresh_task(self) -> None:
        """Periodically sync WS subscriptions with active markets.
        
        Also auto-reconnects if the WS bridge has dropped.
        Phase 2: Never gives up — 24/7 operation requires persistent WS.
        """
        # Auto-reconnect: if bridge died, try restarting it
        if not self._ws_bridge._running or not self._ws_bridge.is_connected:
            if self.config.ws_enabled and self._ws_url:
                log.info("ws_bridge_reconnecting", was_running=self._ws_bridge._running)
                try:
                    await self._ws_bridge.stop()  # clean up old state
                    await self._ws_bridge.start(
                        ws_url=self._ws_url,
                        auth=self._ws_auth,
                    )
                    active = [m.ticker for m in market_cache.get_active()[:self.config.ws_max_subscriptions]]
                    if active:
                        await self._ws_bridge.subscribe_tickers(active)
                    # Reset reconnect counter on the underlying WS client
                    if hasattr(self._ws_bridge, '_ws') and self._ws_bridge._ws:
                        self._ws_bridge._ws._reconnect_attempts = 0
                    log.info("ws_bridge_reconnected", tickers=len(active))
                except Exception as e:
                    # Phase 28: Detailed reconnect failure logging
                    log.warning("ws_reconnect_failed",
                                error=str(e),
                                error_type=type(e).__name__,
                                hint="Will retry in 120s — poll-based requoting covers order management")
            return
        try:
            active = [m.ticker for m in market_cache.get_active()[:self.config.ws_max_subscriptions]]
            await self._ws_bridge.refresh_subscriptions(active)
        except Exception as e:
            log.debug("ws_refresh_error", error=str(e))

    # ── Phase 3+4: Capital Recycling & Fill Reconciliation ────────────

    async def _on_capital_recycled(self) -> None:
        """
        Triggered by CapitalAllocator when capital is freed.

        Runs a fast scan to immediately deploy the freed capital
        into new opportunities. This is the heart of capital recycling:
        settlement → CAPITAL_FREED → re-scan → new trade in seconds.
        """
        if not self._state.is_alive or not self._state.is_trading:
            return
        if self._state.is_paused:
            return

        try:
            scan_debug = await self._scanner.scan(self._state)
            recycled = scan_debug.get("exec_successes", 0)
            if recycled > 0:
                self._reactive_trades += recycled
                log.info("💰🔄 CAPITAL RECYCLED",
                         trades=recycled,
                         available=f"${self._capital.available_cents / 100:.2f}")
        except Exception as e:
            log.debug("capital_recycle_scan_error", error=str(e))

    async def _reconcile_fills_task(self) -> None:
        """
        Periodic fill reconciliation — catch fills missed by WS.

        Queries Kalshi API for order status and detects fills that
        the WebSocket stream might have missed (disconnections, races).
        """
        try:
            result = await self._order_mgr.reconcile_fills()
            missed = result.get("missed_fills", 0)
            if missed > 0:
                log.warning("🧟🔍 FILL RECONCILIATION",
                            missed_fills=missed,
                            checked=result.get("checked", 0))
        except Exception as e:
            log.debug("reconcile_fills_error", error=str(e))

    async def _sync_capital_task(self) -> None:
        """
        Periodic capital sync — keep allocator in sync with reality.

        Updates the capital allocator with the latest portfolio balance
        and rebuilds reservation state from pending orders.
        """
        try:
            from app.pipeline.portfolio_tracker import portfolio_state

            self._capital.sync_balance(portfolio_state.balance_cents)
            self._capital.sync_from_pending_orders(self._order_mgr.pending_orders)
        except Exception as e:
            log.debug("sync_capital_error", error=str(e))

    async def _refit_fill_predictor_task(self) -> None:
        """
        Phase 5: Periodic batch refit of the fill rate prediction model.

        Every 30 minutes, refit the SGDClassifier on all collected
        fill/cancel observations for better prediction accuracy.
        """
        try:
            stats = self._fill_predictor.refit()
            obs = stats.get("total_observations", 0)
            if obs > 0:
                log.info("🧟🎯 FILL PREDICTOR REFIT",
                         observations=obs,
                         fill_rate=f"{stats.get('empirical_fill_rate', 0):.1%}")
        except Exception as e:
            log.debug("refit_fill_predictor_error", error=str(e))

    # ── Scheduled Tasks ───────────────────────────────────────────────

    async def _retrain_task(self) -> None:
        checkpoint = await self.learner.retrain()
        if checkpoint:
            self._state.generation = self.learner.generation
            self._state.model_version = checkpoint.version
            self._state.last_retrain_time = time.time()

        try:
            cat_models = await self.learner.train_category_models()
            if cat_models:
                self._category_models = cat_models
                self._scanner._category_models = cat_models
        except Exception:
            pass

    async def _performance_task(self) -> None:
        self.performance.compute_snapshot()

    async def _adaptation_task(self) -> None:
        snapshot = self.performance.compute_snapshot()
        events = self.strategy.adapt(snapshot)
        if events:
            self._state.last_adaptation_time = time.time()
        # Phase 17: Reweight category budgets from performance
        if self._capital:
            self._capital.reweight_categories()

    async def _save_task(self) -> None:
        self.memory.save()

    async def _resolve_outcomes_task(self) -> None:
        await self._resolver.resolve()
        # Clean up stale resting orders in paper trader (Issue #19)
        try:
            from app.state import state as _st
            if _st.paper_simulator:
                _st.paper_simulator.cleanup_stale_orders(max_age_seconds=3600.0)
        except Exception:
            pass

    async def _health_check_task(self) -> None:
        # Circuit breaker check — only consider trades from THIS session
        # (old pre-upgrade trades should not trigger the breaker)
        resolved = self.memory.get_resolved_trades()
        awaken_time = self._state.awaken_time if hasattr(self._state, "awaken_time") else 0
        if len(resolved) >= CIRCUIT_BREAKER_MIN_TRADES:
            recent = [
                t for t in resolved[-100:]
                if not getattr(t, "is_bootstrap", False)
                and getattr(t, "timestamp", 0) > awaken_time
            ]
            # Phase 22 FIX: Only count WIN and LOSS for accuracy.
            # BREAKEVEN trades are sell/exit records — they are NOT
            # prediction failures and must not drag accuracy to 0%.
            win_loss_only = [
                t for t in recent
                if t.outcome in (TradeOutcome.WIN, TradeOutcome.LOSS)
            ]
            if len(win_loss_only) >= CIRCUIT_BREAKER_MIN_TRADES:
                wins = sum(1 for t in win_loss_only if t.outcome == TradeOutcome.WIN)
                accuracy = wins / len(win_loss_only)
                if accuracy < CIRCUIT_BREAKER_MIN_ACCURACY and not self._state.circuit_breaker_triggered:
                    log.warning("🧟🛑 CIRCUIT BREAKER TRIGGERED",
                                accuracy=f"{accuracy:.1%}", threshold=f"{CIRCUIT_BREAKER_MIN_ACCURACY:.0%}",
                                wins=wins, losses=len(win_loss_only) - wins)
                    self._state.circuit_breaker_triggered = True
                    self._state.circuit_breaker_triggered_at = time.time()
                    self._state.is_paused = True
                    self._state.pause_reason = f"Circuit breaker: accuracy {accuracy:.1%}"
                    await self._retrain_task()
                    return

        _should_pause, _reason = self.performance.should_pause_trading()
        if _reason != "ok":
            log.info("health_note", reason=_reason)

        # Phase 20: Evaluate category retirements
        newly_retired = self.performance.evaluate_retirements()
        if newly_retired:
            log.warning("🧟💀 CATEGORIES RETIRED", categories=newly_retired)

        # Phase 15: Log category analytics every snapshot
        try:
            cat_analytics = self.memory.category_analytics()
            if cat_analytics:
                active_cats = [c for c, s in cat_analytics.items() if s["trades"] >= 3]
                profitable = [c for c in active_cats if cat_analytics[c]["total_pnl"] > 0]
                losing = [c for c in active_cats if cat_analytics[c]["total_pnl"] < 0]
                retired_now = list(self.performance.retired_categories().keys())
                log.info(
                    "🧟📊 CATEGORY HEALTH",
                    active=len(active_cats),
                    profitable=profitable,
                    losing=losing,
                    retired=retired_now,
                )
        except Exception:
            pass

        if self.config.pause_on_degradation and self.performance.is_model_degrading():
            log.warning("🧟⚠️ MODEL DEGRADATION — forcing retrain")
            await self._retrain_task()

        try:
            self._health.record_check("scan_loop", self._state.is_alive, f"scans={self._state.total_scans}")
            self._health.record_check("trading", self._state.is_trading and not self._state.is_paused, self._state.pause_reason or "ok")
            self._health.record_check("model", self._state.model_version != "untrained", f"v={self._state.model_version}")
        except Exception:
            pass

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

    def _try_load_latest_checkpoint(self) -> None:
        try:
            ckpt_dir = Path(self.config.checkpoint_dir)
            if not ckpt_dir.exists():
                return
            pkl_files = sorted(ckpt_dir.glob("frankenstein_gen*.pkl"),
                               key=lambda f: f.stat().st_mtime, reverse=True)
            if not pkl_files:
                return
            latest = pkl_files[0]
            self._model.load(str(latest))
            name = latest.stem
            gen_str = name.split("_")[1].replace("gen", "")
            try:
                gen = int(gen_str)
            except ValueError:
                gen = 1
            version_part = "_".join(name.split("_")[2:])
            self._state.generation = gen
            self._state.model_version = version_part or name
            self.learner._generation = gen
            self.learner._total_promotions = gen
            log.info("🧟✅ CHECKPOINT RESTORED", path=str(latest),
                     generation=gen, version=self._state.model_version)
        except Exception as e:
            log.error("checkpoint_load_failed", error=str(e))

    async def _startup_bootstrap(self) -> None:
        """Phase 26: Synchronous startup bootstrap — model ready from first scan.

        Pipeline:
        1. Clean stale memory (old churn/breakeven trades without labels)
        2. Check if memory already has enough usable labels → retrain
        3. Fetch 500+ settled markets from Kalshi → inject as training data
        4. Train XGBoost with walk-forward CV
        5. Mark model as ready

        This runs BEFORE the scan loop starts, so the model is always
        trained before the first trade opportunity is evaluated.
        """
        import time as _time
        _start = _time.monotonic()

        # Step 1: Clean stale memory — old churn trades are noise.
        # Keep only trades with usable labels (market_result = yes/no + features).
        usable_before = sum(
            1 for t in self.memory._trades
            if t.market_result in ("yes", "no") and t.features
        )
        stale_count = len(self.memory._trades) - usable_before
        if stale_count > 0 and usable_before < self.learner.min_samples:
            log.info(
                "🧟🧹 CLEANING STALE MEMORY",
                total=len(self.memory._trades),
                usable=usable_before,
                stale=stale_count,
                reason="Old trades without usable labels waste memory",
            )
            # Keep ONLY trades with usable labels + any genuine pending
            from collections import deque
            kept = deque(maxlen=self.memory.max_trades)
            for t in self.memory._trades:
                has_label = t.market_result in ("yes", "no") and t.features
                is_fresh_pending = (
                    t.outcome.value == "pending"
                    and t.source == "live"
                    and (_time.time() - t.timestamp) < 86400  # < 24h old
                )
                if has_label or is_fresh_pending:
                    kept.append(t)
            self.memory._trades = kept
            self.memory._important_trades = [
                t for t in self.memory._important_trades
                if t.market_result in ("yes", "no") and t.features
            ]
            self.memory._rebuild_indexes()
            log.info("🧟🧹 MEMORY CLEANED", kept=len(self.memory._trades))

        # Step 2: Check if we already have enough labels
        usable = sum(
            1 for t in self.memory._trades
            if t.market_result in ("yes", "no") and t.features
        )
        if usable >= self.learner.min_samples:
            log.info("🧟🎓 ENOUGH LABELS — retraining from memory", usable=usable)
            result = await self.force_retrain()
            if result.get("success"):
                log.info("🧟✅ MODEL TRAINED FROM EXISTING DATA",
                         version=result["version"], auc=result.get("auc"))
                return

        # Step 3: Bootstrap from settled Kalshi markets
        log.info("🧟🧪 BOOTSTRAP: Fetching settled markets from Kalshi...")
        try:
            from app.state import state as _st
            if _st.kalshi_api:
                from app.frankenstein.bootstrap import bootstrap_from_settled_markets
                stats = await bootstrap_from_settled_markets(
                    _st.kalshi_api,
                    self.memory,
                    max_markets=2000,  # fetch up to 2000
                    min_target=500,    # inject at least 500 labeled records
                )
                log.info("🧟🧪 BOOTSTRAP COMPLETE", **stats)
            else:
                log.warning("bootstrap_skip_no_api")
                return
        except Exception as e:
            log.error("bootstrap_fetch_failed", error=str(e))
            return

        # Step 4: Verify we have enough data and train
        usable_after = sum(
            1 for t in self.memory._trades
            if t.market_result in ("yes", "no") and t.features
        )
        log.info("🧟📊 BOOTSTRAP DATA CHECK", usable=usable_after,
                 required=self.learner.min_samples)

        if usable_after >= self.learner.min_samples:
            result = await self.force_retrain()
            elapsed = _time.monotonic() - _start
            if result.get("success"):
                log.info(
                    "🧟✅ MODEL TRAINED FROM BOOTSTRAP",
                    version=result["version"],
                    auc=result.get("auc"),
                    generation=result.get("generation"),
                    bootstrap_samples=usable_after,
                    elapsed=f"{elapsed:.1f}s",
                )
                self.memory.save()
            else:
                log.warning(
                    "🧟⚠️ BOOTSTRAP RETRAIN FAILED",
                    reason=result.get("reason"),
                    usable=usable_after,
                    elapsed=f"{elapsed:.1f}s",
                )
        else:
            log.warning(
                "🧟⚠️ INSUFFICIENT BOOTSTRAP DATA",
                usable=usable_after,
                required=self.learner.min_samples,
            )

    # ── Manual Controls ───────────────────────────────────────────────

    def pause(self, reason: str = "manual") -> None:
        self._state.is_paused = True
        self._state.pause_reason = reason
        log.info("🧟⏸️ FRANKENSTEIN PAUSED", reason=reason)

    def resume(self) -> None:
        self._state.circuit_breaker_triggered = False
        self._state.is_paused = False
        self._state.pause_reason = ""
        log.info("🧟▶️ FRANKENSTEIN RESUMED")

    async def force_retrain(self) -> dict[str, Any]:
        checkpoint = await self.learner.retrain(force=True)
        if checkpoint:
            self._state.generation = self.learner.generation
            self._state.model_version = checkpoint.version
            return {"success": True, "version": checkpoint.version,
                    "generation": self.learner.generation, "auc": checkpoint.val_auc}
        return {"success": False, "reason": "insufficient_data_or_no_improvement"}

    async def bootstrap_training_data(self) -> dict[str, Any]:
        from app.frankenstein.bootstrap import (
            bootstrap_from_settled_markets, bootstrap_from_active_markets,
        )
        result: dict[str, Any] = {
            "settled_stats": {}, "active_stats": {},
            "retrain_result": None, "memory_before": self.memory.total_resolved,
        }
        try:
            from app.state import state as _st
            if _st.kalshi_api:
                result["settled_stats"] = await bootstrap_from_settled_markets(
                    _st.kalshi_api, self.memory, max_markets=2000, min_target=500)
        except Exception as e:
            result["settled_stats"] = {"error": str(e)}

        if self.memory.total_resolved < self.learner.min_samples:
            try:
                result["active_stats"] = await bootstrap_from_active_markets(self.memory, count=500)
            except Exception as e:
                result["active_stats"] = {"error": str(e)}

        result["memory_after"] = self.memory.total_resolved
        if self.memory.total_resolved >= self.learner.min_samples:
            result["retrain_result"] = await self.force_retrain()
        else:
            result["retrain_result"] = {"success": False, "reason": f"Only {self.memory.total_resolved} resolved"}
        return result

    # ── Learning-Mode Property ─────────────────────────────────────────

    @property
    def is_in_learning_mode(self) -> bool:
        """
        Phase 25b: Unified learning mode based on actual usable training data.

        Previously brain.status() used real_trades < 100 while scanner
        used model.is_trained — creating a dangerous inconsistency when
        a stale checkpoint was loaded.  Now everything uses the count of
        resolved trades with definitive market_result (yes/no).
        """
        from app.frankenstein.constants import MIN_TRAINING_SAMPLES
        usable = 0
        for t in self.memory._trades:
            if t.market_result in ("yes", "no") and t.features:
                usable += 1
                if usable >= MIN_TRAINING_SAMPLES:
                    return False
        return True

    # ── Status ────────────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        uptime = time.time() - self._state.birth_time if self._state.is_alive else 0
        snap = self.performance.compute_snapshot() if self.performance._snapshots else None
        real_trades = snap.real_trades if snap else 0
        _learning = self.is_in_learning_mode

        return {
            "name": "Frankenstein",
            "version": self._state.model_version,
            "generation": self._state.generation,
            "is_alive": self._state.is_alive,
            "is_trading": self._state.is_trading and not self._state.is_paused,
            "is_paused": self._state.is_paused,
            "pause_reason": self._state.pause_reason,
            "learning_mode": _learning,
            "learning_progress": f"{min(real_trades, 100)}/100 real trades" if _learning else "graduated",
            "real_trades": real_trades,
            "uptime_seconds": uptime,
            "uptime_human": self._format_uptime(uptime),
            "total_scans": self._state.total_scans,
            "total_signals": self._state.total_signals,
            "total_trades_executed": self._state.total_trades_executed,
            "total_trades_rejected": self._state.total_trades_rejected,
            "last_scan_ms": f"{self._state.current_scan_time_ms:.1f}",
            "last_scan_debug": self._state.last_scan_debug,
            "daily_trades": self._state.daily_trade_count,
            "daily_trade_cap": MAX_DAILY_TRADES,
            "pretrained_loaded": self._state.pretrained_loaded,
            "circuit_breaker_active": self._state.circuit_breaker_triggered,
            "category_stats": dict(self._resolver.category_stats),
            "memory": self.memory.stats(),
            "performance": self.performance.summary(),
            "learner": self.learner.stats(),
            "strategy": self.strategy.stats(),
            "scheduler": self.scheduler.stats(),
            "health": self._health.summary(),
            "portfolio_risk": self._adv_risk.portfolio_summary(),
            "exchange_session": ExchangeSchedule.current_session(),
            "liquidity_factor": ExchangeSchedule.liquidity_factor(),
            "sports_only_mode": self._sports_only,
            "sports_detector": self._sports_detector.stats() if self._sports_detector else None,
            "sports_risk": self._sports_risk.summary() if self._sports_risk else None,
            "sports_predictor": self._sports_predictor.stats() if self._sports_predictor else None,
            # Phase 2: WebSocket bridge
            "ws_bridge": self._ws_bridge.stats(),
            "reactive_trades": self._reactive_trades,
            "event_bus": self._bus.stats(),
            # Phase 3+4: Capital allocator + smart requoting
            "capital": self._capital.stats(),
            "order_manager": self._order_mgr.stats(),
            # Phase 5: Fill rate prediction
            "fill_predictor": self._fill_predictor.stats(),
        }

    @staticmethod
    def _format_uptime(seconds: float) -> str:
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            return f"{seconds / 60:.0f}m"
        elif seconds < 86400:
            return f"{seconds / 3600:.1f}h"
        else:
            return f"{seconds / 86400:.1f}d"
