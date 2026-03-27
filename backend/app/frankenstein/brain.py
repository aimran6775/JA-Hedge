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
from app.frankenstein.confidence import ConfidenceScorer, ConfidenceBreakdown
from app.kalshi.models import Market, MarketStatus, OrderAction, OrderSide, OrderType
from app.logging_config import get_logger
from app.pipeline import market_cache
from app.engine.advanced_risk import AdvancedRiskManager
from app.production import SQLiteStore, ExchangeSchedule, HealthMonitor

log = get_logger("frankenstein.brain")


# ── Fee constants ────────────────────────────────────────────────────
# Kalshi taker fee: 7¢/contract, maker fee: 0¢.
# A round-trip (buy + sell) as taker costs 14¢/contract in fees.
# This is the single biggest drag on profitability.
TAKER_FEE_CENTS = 7       # per contract, per side
ROUND_TRIP_FEE_CENTS = 14  # buy fee + sell fee

def round_trip_fee_pct(price_cents: int) -> float:
    """Round-trip fee as a percentage of contract cost.
    
    At 22¢: 14/22 = 63.6% (!!)
    At 50¢: 14/50 = 28.0%
    At 75¢: 14/75 = 18.7%
    
    Cheap contracts are fee DEATH TRAPS.
    """
    if price_cents <= 0:
        return 1.0
    return ROUND_TRIP_FEE_CENTS / price_cents


# ── Dynamic edge caps by market category ────────────────────────────
# Sports/finance are highly efficient (Vegas lines, tracked indices).
# Crypto/entertainment are less efficient, larger edges are plausible.
CATEGORY_EDGE_CAPS: dict[str, float] = {
    "sports":        0.08,   # Very efficient — Vegas lines
    "finance":       0.08,   # Very efficient — tracked indices
    "economics":     0.10,   # Somewhat efficient — consensus estimates
    "crypto":        0.12,   # Volatile but tracked
    "politics":      0.10,   # Polling-based, moderate efficiency
    "weather":       0.10,   # NWS forecasts are decent
    "entertainment": 0.12,   # Less efficient, fewer analysts
    "science":       0.12,   # Less efficient
    "general":       0.10,   # Default
}


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
    strategy_adaptation_interval: float = 1800.0   # 30 min (slower to prevent oscillation)
    outcome_check_interval: float = 60.0          # 1 min — fast feedback loop

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

        # Duplicate market protection: {ticker: timestamp} of recent trades
        # Prevents buying the same market every scan cycle.
        self._recently_traded: dict[str, float] = {}
        # Event-level cooldown: {event_ticker: timestamp}
        # Prevents trading different strike prices on the same event.
        self._recently_traded_events: dict[str, float] = {}
        self._trade_cooldown_seconds: float = 1800.0  # 30-min cooldown (learning needs faster data collection)

        # Phase 9: Category performance tracking for gating
        # {category: {"wins": int, "losses": int}}
        self._category_stats: dict[str, dict[str, int]] = {}

        # Phase 17: Order lifecycle tracking
        # {order_id: {"ticker": str, "placed_at": float, "price_cents": int}}
        self._pending_orders: dict[str, dict[str, Any]] = {}
        self._ORDER_STALE_SECONDS = 300.0  # cancel unfilled orders after 5 min
        self._fill_rate_stats: dict[str, int] = {"placed": 0, "filled": 0, "cancelled": 0}

        # Phase 18: Category-specific model registry
        # {category_name: XGBoostPredictor} — specialist models trained per category
        self._category_models: dict[str, XGBoostPredictor] = {}

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

        # ── DEPLOY PURGE: Clean poisoned bootstrap memory ─────────
        # If FRANKENSTEIN_PURGE_ON_START is set, wipe all bootstrap data
        # that was generated with settlement-price leakage.  This is a
        # one-time operation after deploying fixes.  Remove the env var
        # after the first successful restart.
        import os
        _purge_flag = os.environ.get("FRANKENSTEIN_PURGE_ON_START", "").strip().lower()
        if _purge_flag in ("1", "true", "yes"):
            log.warning("🧟🗑️ PURGE FLAG SET — wiping poisoned bootstrap data")
            purge_result = self.memory.purge_bootstrap_data()
            log.warning("🧟🗑️ PURGE COMPLETE", **purge_result)
            # Also delete old model checkpoints trained on poisoned data
            try:
                ckpt_dir = Path(self.config.checkpoint_dir)
                if ckpt_dir.exists():
                    for f in ckpt_dir.glob("*.pkl"):
                        f.unlink()
                    log.warning("🧟🗑️ OLD CHECKPOINTS DELETED — model will retrain from scratch")
            except Exception as e:
                log.error("checkpoint_purge_failed", error=str(e))

        # Try loading latest checkpoint before deciding to bootstrap
        self._try_load_latest_checkpoint()

        # Auto-bootstrap if model is STILL untrained after checkpoint load
        if not self._model.is_trained:
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
                    import traceback
                    tb_str = traceback.format_exc()[-500:]
                    log.error("scan_error", error=str(e), traceback=tb_str)
                    # Record error in scan debug so it's visible via status API
                    self._state.last_scan_debug = {
                        "exit": "scan_exception",
                        "error": str(e),
                        "traceback": tb_str,
                    }

                interval = self.strategy.params.scan_interval
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            return

    async def _scan_and_trade(self) -> None:
        """One full scan cycle: manage positions → find opportunities → trade."""
        start = time.monotonic()
        self._state.total_scans += 1

        # Phase 10: Exchange schedule — note the session for liquidity
        # adjustment, but ALWAYS allow trading (Kalshi is 24/7).
        # Previously this blocked overnight trading entirely, which
        # meant Frankenstein slept for hours and missed opportunities.
        _, session = ExchangeSchedule.should_trade()

        # Liquidity factor for position sizing adjustment
        liquidity = ExchangeSchedule.liquidity_factor()

        # 1. Get active markets
        markets = market_cache.get_active()
        if not markets:
            self._state.last_scan_debug = {
                "exit": "no_active_markets",
                "cache_total": market_cache.count,
            }
            return

        # ── PHASE 17: Cancel stale unfilled orders ──────────
        await self._cleanup_stale_orders()

        # ── PHASE 2: Manage existing positions (exits) ────
        await self._manage_positions(markets)

        # 2. Filter candidates
        candidates = self._filter_candidates(markets)
        if not candidates:
            self._state.last_scan_debug = {
                "exit": "no_candidates_after_filter",
                "active_markets": len(markets),
                "session": session,
                "sports_only": self._sports_only,
            }
            log.debug("scan_no_candidates", total_markets=len(markets),
                      session=session, sports_only=self._sports_only)
            return

        # 3. Pre-filter: skip markets in cooldown or outside price range
        #    BEFORE expensive feature extraction. This saves ~10-30% CPU per scan.
        pre_filtered = []
        for m in candidates:
            ticker = m.ticker
            # Cooldown check: skip recently traded tickers and events
            if ticker in self._recently_traded:
                continue
            _evt = getattr(m, 'event_ticker', '') or ''
            if _evt and _evt in self._recently_traded:
                continue
            # Skip SCALAR markets — binary prediction assumptions don't apply
            if getattr(m, 'market_type', 'binary') != 'binary':
                continue
            # Price range: skip extreme prices (Phase 3: 15-85¢)
            mid = float(m.midpoint or m.last_price or 0)
            if mid < 0.15 or mid > 0.85:
                continue

            # ── FEE-AWARE PRICE FLOOR ────────────────────────────
            # Skip cheap contracts where fees dominate.
            # LEARNING MODE: relax to 56% so we can collect data on
            # mid-priced contracts (25¢+).  TRAINED: strict 35% (40¢+).
            mid_cents = int(mid * 100)
            effective_cost_cents = min(mid_cents, 100 - mid_cents)  # cheapest side
            fee_pct = round_trip_fee_pct(effective_cost_cents)
            _fee_cap = 0.56 if not self._model.is_trained else 0.35
            if fee_pct > _fee_cap:
                continue

            # ── MINIMUM TIME-TO-EXPIRY ────────────────────────────
            # Short-expiry contracts are fee traps.
            # LEARNING MODE: 30 min minimum (need data variety).
            # TRAINED: 2 hour minimum (need time for edge).
            if hasattr(m, 'expiration_time') and m.expiration_time:
                from datetime import datetime, timezone as _tz
                _delta = (m.expiration_time - datetime.now(_tz.utc)).total_seconds() / 3600
                _min_hours = 0.5 if not self._model.is_trained else 2.0
                if _delta < _min_hours:
                    continue

            pre_filtered.append(m)
        candidates = pre_filtered

        if not candidates:
            return

        # 3b. Populate price history buffers for all candidates.
        #     This is CRITICAL — without calling update(), ~40 time-series
        #     features (SMA, EMA, RSI, MACD, Bollinger, volatility, Hurst,
        #     OBV, smart_money_flow, etc.) are always at their defaults (0.0).
        for m in candidates:
            mid = float(m.midpoint or m.last_price or 0)
            vol = float(m.volume or 0)
            oi = float(m.open_interest or 0)
            spread = float(m.spread or 0)
            if mid > 0:
                self._features.update(m.ticker, mid, vol, oi, spread)

        # 3c. Seed price histories from Kalshi candlestick API for markets
        #     we haven't seen before.  Even 60 one-minute candles gives
        #     enough data for SMA-20, RSI-14, Bollinger bands, etc.
        await self._seed_price_histories(candidates)

        # 3d. Phase 6: Enrich orderbook depth for top candidates
        await self._enrich_orderbook_depth(candidates[:20])

        # 4. Compute features for remaining candidates
        features_list = [self._features.compute(m) for m in candidates]

        # 4a. FEATURE COMPLETENESS GATE (Phase 7)
        #     Skip markets where >50% of features are at their defaults
        #     (0.0). These are markets we have no history for — the model
        #     is predicting on garbage inputs and its output is meaningless.
        #     This prevents the vast majority of bad trades.
        filtered_candidates = []
        filtered_features = []
        for m, feat in zip(candidates, features_list):
            arr = feat.to_array()
            zero_pct = (arr == 0.0).sum() / max(len(arr), 1)
            if zero_pct > 0.50:
                log.debug("feature_gate_skip", ticker=m.ticker,
                          zero_pct=f"{zero_pct:.0%}")
                continue
            filtered_candidates.append(m)
            filtered_features.append(feat)
        candidates = filtered_candidates
        features_list = filtered_features

        if not candidates:
            self._state.last_scan_debug = {"exit": "all_failed_feature_gate"}
            return

        # 4b. Cross-event probability arbitrage detection.
        #     Group candidates by event_ticker and compute the sum of YES
        #     midpoints for mutually exclusive sibling markets.  A sum
        #     significantly > 1.0 or < 1.0 indicates structural mispricing.
        event_prob_sums: dict[str, float] = {}
        event_members: dict[str, list[str]] = {}
        for m in candidates:
            evt = getattr(m, 'event_ticker', '') or ''
            if evt:
                mid = float(m.midpoint or m.last_price or 0)
                event_prob_sums[evt] = event_prob_sums.get(evt, 0.0) + mid
                event_members.setdefault(evt, []).append(m.ticker)
        # Inject event_prob_sum into each feature vector
        for m, feat in zip(candidates, features_list):
            evt = getattr(m, 'event_ticker', '') or ''
            if evt and evt in event_prob_sums and len(event_members.get(evt, [])) >= 2:
                feat.event_prob_sum = event_prob_sums[evt]

        # 4c. Phase 20: Enrich features with Intelligence Hub alt-data signals
        try:
            from app.state import state as _hub_st
            hub = _hub_st.intelligence_hub
            if hub and hub._running:
                for m, feat in zip(candidates, features_list):
                    alt_features = hub.get_features_for_ticker(m.ticker)
                    if alt_features:
                        # Use average signal as confidence boost
                        sig_vals = [v for k, v in alt_features.items() if k.endswith("_signal")]
                        conf_vals = [v for k, v in alt_features.items() if k.endswith("_confidence")]
                        if sig_vals:
                            avg_signal = sum(sig_vals) / len(sig_vals)
                            # Nudge implied_prob toward alt-data consensus
                            feat.implied_prob = feat.implied_prob * 0.85 + avg_signal * 0.15
                        if conf_vals:
                            avg_conf = sum(conf_vals) / len(conf_vals)
                            # Boost settlement_confidence with alt-data agreement
                            feat.settlement_confidence = min(1.0,
                                feat.settlement_confidence + avg_conf * 0.1)
        except Exception:
            pass  # Intelligence Hub is optional — never block trading

        # 4d. Batch predict
        predictions = self._model.predict_batch(features_list)

        # 4e. Phase 18: Override predictions with category-specialist models
        for i, (m, feat) in enumerate(zip(candidates, features_list)):
            from app.frankenstein.categories import detect_category
            cat = detect_category(m.title or "", m.category or "", ticker=m.ticker)
            if cat in self._category_models:
                try:
                    spec_pred = self._category_models[cat].predict(feat)
                    if spec_pred and spec_pred.confidence > predictions[i].confidence:
                        # Blend: 60% specialist, 40% generalist
                        blended_prob = 0.60 * spec_pred.predicted_prob + 0.40 * predictions[i].predicted_prob
                        predictions[i] = Prediction(
                            predicted_prob=blended_prob,
                            confidence=spec_pred.confidence,
                            side=spec_pred.side,
                            edge=spec_pred.edge,
                            model_name=f"cat_{cat}",
                        )
                except Exception:
                    pass  # fall back to generalist

        # 5. Evaluate each signal through adaptive strategy
        # Phase 9: Collect all valid signals, then rank by expected value
        params = self.strategy.params
        signals_generated = 0
        trades_executed = 0
        trades_rejected = 0
        trade_candidates: list[dict[str, Any]] = []

        # ⭐ Multi-factor confidence scorer (Phase 11+)
        # Created ONCE outside the loop for performance.
        # LEARNING MODE: B grade (composite ≥ 60) — collect training data.
        # TRAINED MODE: A grade (composite ≥ 80) — only highest conviction.
        # The confidence scorer IS the gatekeeper. Let it decide.
        _is_learning = not self._model.is_trained
        min_grade = "B" if _is_learning else "A"
        conf_scorer = ConfidenceScorer(
            min_grade=min_grade,
            portfolio_heat=self._adv_risk.portfolio_heat if hasattr(self._adv_risk, 'portfolio_heat') else 0.0,
            current_drawdown_pct=self._adv_risk.current_drawdown_pct if hasattr(self._adv_risk, 'current_drawdown_pct') else 0.0,
            open_positions=self._count_open_positions(),
            max_positions=params.max_simultaneous_positions,
        )

        # Clean expired cooldowns (ticker + event level)
        now_ts = time.time()
        self._recently_traded = {
            t: ts for t, ts in self._recently_traded.items()
            if now_ts - ts < self._trade_cooldown_seconds
        }
        self._recently_traded_events = {
            e: ts for e, ts in self._recently_traded_events.items()
            if now_ts - ts < self._trade_cooldown_seconds
        }
        # Track tickers already selected THIS scan to prevent intra-scan dupes
        tickers_this_scan: set[str] = set()

        # ── DIVERSIFICATION TRACKING ────────────────────────────
        # Prevent concentration: max trades per event and per category
        # in a single scan cycle.  Spread bets across different events
        # and categories to avoid correlated losses.
        MAX_PER_EVENT = 1     # max 1 trade on same event (was 2) — no over-concentration
        MAX_PER_CATEGORY = 3  # max 3 trades in same category per scan (was 4)
        events_this_scan: dict[str, int] = {}   # event_ticker → count
        categories_this_scan: dict[str, int] = {}  # category → count

        for market, features, prediction in zip(candidates, features_list, predictions):
            # ── DUPLICATE PROTECTION ──────────────────────────────
            # Skip if we traded this ticker recently (cross-scan cooldown)
            if market.ticker in self._recently_traded:
                continue
            # Skip if we traded this EVENT recently (different strikes, same game)
            _evt_tk = getattr(market, 'event_ticker', '') or ''
            if _evt_tk and _evt_tk in self._recently_traded_events:
                continue
            # Skip if we already selected this ticker in THIS scan
            if market.ticker in tickers_this_scan:
                continue

            # ── DIVERSIFICATION GATE ────────────────────────────
            # Don't over-concentrate on one event or category
            evt = getattr(market, 'event_ticker', '') or ''
            if evt and events_this_scan.get(evt, 0) >= MAX_PER_EVENT:
                continue
            from app.frankenstein.categories import detect_category as _det_cat
            _pre_cat = _det_cat(market.title or "", market.category or "", ticker=market.ticker)
            if categories_this_scan.get(_pre_cat, 0) >= MAX_PER_CATEGORY:
                continue

            # ── CATEGORY PERFORMANCE GATE (Phase 9) ───────────────
            # If we have 20+ resolved trades in a category and the win
            # rate is below 40%, stop trading it.  The model clearly
            # doesn't understand that domain.
            cat_stat = self._category_stats.get(_pre_cat)
            if cat_stat:
                cat_total = cat_stat.get("wins", 0) + cat_stat.get("losses", 0)
                if cat_total >= 20:
                    cat_wr = cat_stat["wins"] / cat_total
                    if cat_wr < 0.40:
                        log.debug("category_gated", category=_pre_cat,
                                  win_rate=f"{cat_wr:.0%}", trades=cat_total)
                        continue

            # Phase 8: Apply category-specific adjustments
            prediction, cat_adj = self.categories.adjust_prediction(
                prediction, features,
                market_title=market.title or "",
                category_hint=market.category or "",
                ticker=market.ticker,
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

            # ── PRICE FLOOR: Skip extreme-probability contracts ────
            # Contracts priced < 15¢ or > 85¢ are lottery tickets.
            # The model cannot reliably predict these — they need
            # near-perfect information to have an edge.
            # Phase 3: Tightened from 10/90 → 15/85. Extreme-price
            # contracts have terrible win rates in our data.
            mid_price = features.midpoint
            if mid_price < 0.15 or mid_price > 0.85:
                continue

            # ── MARKET-ANCHOR SANITY CHECK ────────────────────────
            # If the model's predicted probability diverges from the
            # market price by more than the category-specific cap,
            # the model is almost certainly wrong. Markets are efficient
            # — no heuristic should claim a 60% edge.
            # Category-specific caps: sports are efficient (Vegas lines),
            # crypto is volatile, weather has genuine uncertainty.
            from app.frankenstein.categories import detect_category
            cat = detect_category(market.title or "", market.category or "", ticker=market.ticker)

            # ── DYNAMIC EDGE CAP BY CATEGORY ──────────────────────
            # CATEGORY_EDGE_CAPS is defined at module level
            MAX_ALLOWED_EDGE = CATEGORY_EDGE_CAPS.get(cat, 0.10)

            if abs(prediction.edge) > MAX_ALLOWED_EDGE:
                # Phase 2: REJECT impossible edges — don't clamp.
                # If the model claims a 50% edge over an efficient market,
                # the model is WRONG. Clamping to 8% and still trading
                # was a major source of losses. Skip entirely.
                continue

            # Apply adaptive thresholds
            # LEARNING MODE: low edge bar — let the confidence scorer decide.
            # TRAINED MODE: category-aware thresholds for real profitability.
            if not self._model.is_trained:
                # 🎓 LEARNING: minimum edge = 2% (just need a signal direction)
                # Position sizing is capped at 1 contract so risk is minimal.
                # The confidence scorer + Kelly still gate bad trades.
                effective_min_edge = 0.02
            else:
                effective_min_edge = params.min_edge
                # Category-aware edge thresholds (trained mode only):
                if cat == "sports" and sports_pred is not None:
                    effective_min_edge = max(effective_min_edge, 0.06)
                elif cat == "crypto":
                    effective_min_edge = max(effective_min_edge, 0.10)
                elif cat == "finance":
                    effective_min_edge = max(effective_min_edge, 0.08)
                elif cat == "weather":
                    effective_min_edge = max(effective_min_edge, 0.07)
                elif cat == "politics":
                    effective_min_edge = max(effective_min_edge, 0.08)

            # Gate: minimum edge (absolute value)
            if abs(prediction.edge) < effective_min_edge:
                continue

            # ── Phase 1+: EDGE MUST EXCEED COSTS ──────────
            # TRAINED: Edge must cover spread + round-trip fees.
            # LEARNING: Edge must cover half-spread only (we accept
            #   small losses to collect training data with 1-contract bets).
            half_spread = features.spread / 2.0
            price_cents = int(features.midpoint * 100)
            effective_cost = min(price_cents, 100 - price_cents)
            fee_as_fraction = ROUND_TRIP_FEE_CENTS / 100.0  # 0.14
            if self._model.is_trained:
                total_cost_to_beat = half_spread + fee_as_fraction
            else:
                total_cost_to_beat = half_spread  # learning: just beat the spread
            if abs(prediction.edge) <= total_cost_to_beat:
                continue

            # ⭐ Multi-factor confidence scoring (Phase 11)
            # Only A-grade trades are executed — prioritise quality over quantity.
            conf_breakdown = conf_scorer.score(
                prediction, features,
                model_trained=self._model.is_trained,
                has_vegas=sports_pred is not None,
                is_sports=bool(self._sports_detector and self._sports_detector.detect(market).is_sports) if self._sports_detector else False,
                exchange_session=self._schedule.current_session() if hasattr(self._schedule, 'current_session') else "regular",
            )

            # 🚫 GRADE GATE: reject anything below minimum grade
            if not conf_breakdown.should_trade:
                log.debug("grade_rejected", ticker=market.ticker,
                          grade=conf_breakdown.grade, score=round(conf_breakdown.composite_score, 1))
                continue

            signals_generated += 1
            self._state.total_signals += 1

            # Kelly criterion position sizing (binary contract formula)
            # 🎯 Phase 2: Confidence-driven sizing — scale Kelly by confidence grade
            kelly = self._kelly_size(prediction, features, params, market=market)
            if kelly <= 0:
                continue

            # Confidence-based position scaling:
            # A+ → 100%, A → 85%, B+ → 65%, B → 45%, C+ → 25%
            confidence_scale = {
                "A+": 1.0, "A": 0.85, "B+": 0.65, "B": 0.45, "C+": 0.25, "C": 0.15,
            }.get(conf_breakdown.grade, 0.10)
            kelly *= confidence_scale

            # Phase 7: Adjust Kelly with advanced risk (drawdown/position scaling)
            kelly = self._adv_risk.adjusted_kelly(kelly)

            # Phase 10: Scale by liquidity (reduce size in low-liquidity sessions)
            kelly *= liquidity

            # Position sizing: Kelly fraction × max position size
            # Phase 6: CONSERVATIVE SIZING — default to 1 contract.
            # Only scale up for A/A+ grade signals with trained model.
            # The old 3-contract floor for cheap markets was a major
            # loss multiplier — putting 3 contracts on coin-flip odds.
            raw_count = int(kelly * params.max_position_size)
            price_cents = self._compute_price(prediction, features, market=market)

            # Grade-based sizing: only scale up for proven signals
            # LEARNING MODE: always 1 contract — minimize risk while collecting data
            if not self._model.is_trained:
                min_count = 1
            elif conf_breakdown.grade in ("A+",):
                min_count = 3  # A+ with trained model: confident
            elif conf_breakdown.grade in ("A",):
                min_count = 2  # A with trained model: moderate
            else:
                min_count = 1  # Everything else: minimum bet

            count = max(min_count, raw_count)
            # Cap to risk manager's max position size
            count = min(count, params.max_position_size)

            # Phase 5+: Expected value with ALL costs (spread + fees)
            # EV = (edge - spread_cost - fee_cost) * count * (1 - cost)
            # This is the REAL profitability metric.
            cost_frac = price_cents / 100.0
            spread_cost = features.spread / 2.0
            fee_cost = ROUND_TRIP_FEE_CENTS / 100.0  # 0.14 per contract as fraction
            net_edge = abs(prediction.edge) - spread_cost - fee_cost
            if net_edge <= 0:
                continue  # no profit after spread + fees
            ev = net_edge * count * (1.0 - cost_frac)

            # Enrich confidence breakdown with uncertainty metrics
            breakdown_dict = conf_breakdown.to_dict()
            breakdown_dict["uncertainty"] = {
                "tree_agreement": round(prediction.tree_agreement, 3),
                "prediction_std": round(prediction.prediction_std, 4),
                "is_calibrated": prediction.is_calibrated,
                "calibration_error": round(prediction.calibration_error, 4),
                "calibrated_prob": round(prediction.calibrated_prob, 4) if prediction.calibrated_prob is not None else None,
            }

            trade_candidates.append({
                "market": market,
                "prediction": prediction,
                "features": features,
                "count": count,
                "price_cents": price_cents,
                "kelly": kelly,
                "ev": ev,
                "confidence_breakdown": breakdown_dict,
            })
            # Mark ticker as used in this scan
            tickers_this_scan.add(market.ticker)
            # Update diversification counters
            _evt = getattr(market, 'event_ticker', '') or ''
            if _evt:
                events_this_scan[_evt] = events_this_scan.get(_evt, 0) + 1
            _tcat = detect_category(market.title or "", market.category or "", ticker=market.ticker)
            categories_this_scan[_tcat] = categories_this_scan.get(_tcat, 0) + 1

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

                    # ── Same quality gates as main model path ─────
                    # Cooldown check: don't re-enter recently traded tickers
                    if sig.ticker in self._recently_traded:
                        continue
                    # Event cooldown
                    sig_market_match = next((m for m in candidates if m.ticker == sig.ticker), None)
                    if not sig_market_match:
                        continue
                    _sig_evt = getattr(sig_market_match, 'event_ticker', '') or ''
                    if _sig_evt and _sig_evt in self._recently_traded:
                        continue

                    # Find corresponding market
                    market_match = sig_market_match
                    feat = self._features.compute(market_match)

                    # Price floor: same as main path (15-85¢, not 10-90¢)
                    if feat.midpoint < 0.15 or feat.midpoint > 0.85:
                        continue

                    # Edge-vs-spread check: edge must exceed half-spread
                    half_spread = feat.spread / 2.0 if feat.spread else 0.0
                    if abs(sig.edge) <= half_spread:
                        continue

                    # Edge cap: category-aware (same caps as main path)
                    from app.frankenstein.categories import detect_category as _dc
                    _sig_cat = _dc(market_match.title or "", market_match.category or "", ticker=market_match.ticker)
                    _sig_cap = CATEGORY_EDGE_CAPS.get(_sig_cat, 0.10)
                    clamped_edge = max(-_sig_cap, min(_sig_cap, sig.edge))
                    if abs(clamped_edge) < params.min_edge:
                        continue

                    pred_for_sig = Prediction(
                        predicted_prob=sig.confidence,
                        confidence=min(sig.confidence, 0.60),  # cap confidence
                        side=sig.side,
                        edge=clamped_edge,
                        model_name=sig.strategy,
                    )

                    # Clamp to risk manager's position limit to avoid
                    # silent rejections at execution time.
                    risk_limit = 10
                    if self._execution._risk_manager:
                        risk_limit = self._execution._risk_manager.limits.max_position_size
                    count = max(1, min(sig.recommended_count, risk_limit))
                    price_cents = self._compute_price(pred_for_sig, feat, market=market_match)
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
            3,  # cap at 3 new trades per scan — only the very best
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

            # ── PRE-EXEC SPREAD RECHECK ──────────────────────────────
            # The spread may have widened since the candidate filter ran.
            # Use a wider limit here (risk manager hard wall) since the
            # initial filter already used the tighter strategy limit.
            risk_spread_limit = 40  # hard wall in cents
            if self._execution._risk_manager:
                risk_spread_limit = self._execution._risk_manager.limits.max_spread_cents
            fresh = market_cache.get(market.ticker)
            if fresh and fresh.spread is not None:
                fresh_spread = int(float(fresh.spread) * 100)
                if fresh_spread > risk_spread_limit:
                    trades_rejected += 1
                    self._state.total_trades_rejected += 1
                    scan_debug["exec_rejections"] += 1
                    scan_debug["top_candidates"].append({
                        "ticker": market.ticker, "stage": "spread_recheck_rejected",
                        "spread": fresh_spread, "limit": params.max_spread_cents,
                        "count": count, "price": price_cents,
                    })
                    log.info("spread_recheck_rejected", ticker=market.ticker,
                             spread_cents=fresh_spread, limit=params.max_spread_cents)
                    continue

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

                # Phase 17: Track order for lifecycle management
                self._fill_rate_stats["placed"] += 1
                if result.order_id:
                    self._pending_orders[result.order_id] = {
                        "ticker": market.ticker,
                        "placed_at": time.time(),
                        "price_cents": price_cents,
                    }

                # Register in cooldown to prevent re-buying next scan
                self._recently_traded[market.ticker] = time.time()
                # Also cooldown the entire event (prevents different strikes on same game)
                _evt_cooldown = getattr(market, 'event_ticker', '') or ''
                if _evt_cooldown:
                    self._recently_traded_events[_evt_cooldown] = time.time()

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

                # Detect category for this trade
                from app.frankenstein.categories import detect_category
                trade_category = detect_category(
                    market.title or "", market.category or "",
                    ticker=market.ticker,
                )

                # Record in Frankenstein's memory
                trade_record = self.memory.record_trade(
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
                    confidence_breakdown=candidate.get("confidence_breakdown"),
                )
                # Tag category directly on the trade record
                trade_record.category = trade_category

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

            # Current value and P&L — FEE-AWARE
            # Use realistic exit price: mid - half_spread - estimated_fee
            # This prevents take-profit triggering on paper gains that
            # vanish after execution costs, and makes stop-loss accurate.
            half_spread = features.spread / 2.0
            # Both buy and sell fees (we paid to enter, we'll pay to exit)
            fee_per_side = TAKER_FEE_CENTS / 100.0  # 0.07
            exit_cost = half_spread + fee_per_side  # cost to EXIT (spread + sell fee)

            if our_side == "yes":
                current_value = max(mid - exit_cost, 0.01)
                unrealized_pnl_pct = (current_value - entry_price) / entry_price if entry_price > 0 else 0
            else:
                current_value = max((1.0 - mid) - exit_cost, 0.01)
                unrealized_pnl_pct = (current_value - entry_price) / entry_price if entry_price > 0 else 0

            should_exit = False
            exit_reason = ""

            # ── Stop-loss check ───────────────────────────
            # Phase 10: VOL-ADAPTIVE stop-loss.
            # Base stop = 15%, then scale by market volatility:
            #   - Low-vol markets: wider stop (less noise-triggered exits)
            #   - High-vol markets: tighter stop (cut fast before bigger drop)
            stop_loss_pct = getattr(params, 'stop_loss_pct', 0.15) or 0.15

            # Scale by volatility — vol_20 is std of 20-period returns
            vol_20 = getattr(features, 'volatility_20', 0.0) or 0.0
            if vol_20 > 0.03:
                # High vol: tighten stop (×0.7 at vol=0.06+)
                vol_scale = max(0.7, 1.0 - (vol_20 - 0.03) * 10.0)
                stop_loss_pct *= vol_scale
            elif vol_20 > 0 and vol_20 < 0.01:
                # Low vol: widen stop (×1.3) — less noise
                stop_loss_pct *= 1.3

            # 🏀 Tighter stop-loss for live sports positions
            if self._sports_detector and self._sports_risk:
                info = self._sports_detector.detect(market)
                if info.is_sports:
                    stop_loss_pct = self._sports_risk.get_stop_loss(info.is_live)

            # Adaptive stop-loss: tighter as expiry approaches
            if features.hours_to_expiry < 4:
                stop_loss_pct *= 0.75  # Tighter near expiry
            if unrealized_pnl_pct < -stop_loss_pct:
                should_exit = True
                exit_reason = f"stop_loss ({unrealized_pnl_pct:.1%} < -{stop_loss_pct:.1%})"

            # ── Take-profit check ─────────────────────────
            # Phase 7+: 20% take-profit — must cover ROUND-TRIP fees.
            # Old 15% take-profit was triggering on paper gains that
            # didn't exist after fees.  At 14¢ round-trip fees,
            # a 15% gain on a 50¢ contract = 7.5¢ gain - 14¢ fees = LOSS.
            take_profit_pct = getattr(params, 'take_profit_pct', 0.20) or 0.20
            # Earlier take-profit near expiry (lock in gains)
            if features.hours_to_expiry < 4:
                take_profit_pct *= 0.70
            if unrealized_pnl_pct > take_profit_pct:
                should_exit = True
                exit_reason = f"take_profit ({unrealized_pnl_pct:.1%} > {take_profit_pct:.1%})"

            # ── Phase 20: TRAILING STOP ───────────────────
            # Once a position is up >10%, trail the stop at 50% of peak gain.
            # This locks in profits while giving winners room to run.
            if not should_exit and unrealized_pnl_pct > 0.10:
                # Track peak PnL for this position
                peak_key = f"_peak_pnl_{ticker}"
                prev_peak = getattr(self, '_trailing_peaks', {}).get(peak_key, 0.0)
                current_peak = max(prev_peak, unrealized_pnl_pct)
                if not hasattr(self, '_trailing_peaks'):
                    self._trailing_peaks: dict[str, float] = {}
                self._trailing_peaks[peak_key] = current_peak

                # Trail at 50% of peak — if peak was 20%, stop at 10%
                trailing_stop = current_peak * 0.50
                if unrealized_pnl_pct < trailing_stop:
                    should_exit = True
                    exit_reason = f"trailing_stop (peak {current_peak:.1%}, trail {trailing_stop:.1%}, current {unrealized_pnl_pct:.1%})"

            # ── Edge reversal check ───────────────────────
            if not should_exit:
                if our_side == "yes" and prediction.side == "no" and prediction.confidence > 0.75:
                    should_exit = True
                    exit_reason = f"edge_reversal (now predicts NO @ {prediction.confidence:.2f})"
                elif our_side == "no" and prediction.side == "yes" and prediction.confidence > 0.75:
                    should_exit = True
                    exit_reason = f"edge_reversal (now predicts YES @ {prediction.confidence:.2f})"

            # ── Near-expiry liquidation ───────────────────
            if not should_exit and features.hours_to_expiry < 0.5:
                # Close very uncertain positions near expiry (30 min)
                if 0.30 < mid < 0.70:
                    should_exit = True
                    exit_reason = f"near_expiry_uncertain ({features.hours_to_expiry:.1f}h)"

            # ── Cleanup trailing stop data on exit ────────
            if should_exit and hasattr(self, '_trailing_peaks'):
                peak_key = f"_peak_pnl_{ticker}"
                self._trailing_peaks.pop(peak_key, None)

            # ── Phase 8: TIME-BASED EXIT ─────────────────────
            # Positions held > 8 hours with uncertain outcome
            # should be closed. Frees capital for better opportunities.
            if not should_exit:
                entry_time = self._estimate_entry_time(ticker)
                hours_held = (time.time() - entry_time) / 3600.0 if entry_time > 0 else 0
                if hours_held > 8.0 and 0.25 < mid < 0.75:
                    should_exit = True
                    exit_reason = f"stale_position ({hours_held:.1f}h held, price uncertain at {mid:.0%})"

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
                    # Cooldown after exit — prevent buy-exit-buy loop
                    self._recently_traded[ticker] = time.time()
                    _exit_evt = getattr(market, 'event_ticker', '') or ''
                    if _exit_evt:
                        self._recently_traded_events[_exit_evt] = time.time()
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

    def _estimate_entry_time(self, ticker: str) -> float:
        """Phase 8: Get the earliest entry timestamp for a ticker position."""
        trades = self.memory.get_recent_trades(n=1000, ticker=ticker)
        buy_trades = [t for t in trades if t.action == "buy"]
        if not buy_trades:
            return 0.0
        return min(t.timestamp for t in buy_trades)

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
        """Filter markets to tradeable candidates.

        Uses strategy params max_spread_cents (tighter) for pre-filtering,
        not the risk manager limit (which is the hard safety wall).
        Markets with unknown spread are rejected — if we can't see the
        book, we shouldn't trade it.
        """
        params = self.strategy.params
        candidates = []

        # ── JUNK PREFIX FILTER ────────────────────────────────────
        # Kalshi auto-generates ~8,000+ MVE (Multi-Variable Event)
        # parlays and other zero-volume markets that waste scan time.
        # Skip them immediately before any expensive checks.
        JUNK_PREFIXES = (
            "KXMVE",           # Multi-Variable Event parlays (auto-generated combos)
            "KXSPOTSTREAMGLOBAL",  # Spot stream globals (no liquidity)
            "KXPARLAY",        # Parlay markets
        )

        # Use the TIGHTER of strategy spread limit and risk limit.
        # Strategy params (15¢) is for signal quality; risk (40¢) is the hard wall.
        max_spread = params.max_spread_cents
        if self._execution._risk_manager:
            risk_spread = self._execution._risk_manager.limits.max_spread_cents
            max_spread = min(max_spread, risk_spread)

        for m in markets:
            if m.status not in (MarketStatus.ACTIVE, MarketStatus.OPEN):
                continue
            # Fast junk rejection — ticker prefix check is O(1)
            ticker_upper = (m.ticker or "").upper()
            if ticker_upper.startswith(JUNK_PREFIXES):
                continue
            if m.yes_bid is None and m.yes_ask is None and m.last_price is None:
                continue

            # STRICT spread filter: reject unknown spread (was bypassing)
            # and reject anything wider than the strategy limit.
            if m.spread is None:
                continue  # no book data → untradeable
            spread_cents = int(float(m.spread) * 100)
            if spread_cents > max_spread:
                continue

            # Reject degenerate books: bid=0 AND ask=0 means nobody is quoting.
            # These show spread=0 (fake tight) but are actually illiquid.
            bid = float(m.yes_bid or 0)
            ask = float(m.yes_ask or 0)
            if bid <= 0 and ask <= 0:
                continue
            # Also reject if midpoint is too extreme (< 2¢ or > 98¢)
            mid = float(m.midpoint or m.last_price or 0)
            if mid < 0.02 or mid > 0.98:
                continue

            # ── HARD LIQUIDITY GATES ──────────────────────────────
            # Volume floor: markets with < 10 contracts traded are
            # too thin to trade — bids/asks are unreliable.
            # Kalshi returns volume_fp (Decimal, aliased as .volume)
            # AND volume (int, aliased as .volume_int). Some markets
            # only populate one field, so we fall back.
            vol = float(m.volume if m.volume is not None else (m.volume_int or 0))
            if vol < 10:
                continue

            # Spread-to-price ratio: reject if spread > 30% of midpoint.
            # A 200% spread means the book is empty — we'd be market-making.
            if mid > 0:
                spread_pct = float(spread_cents) / (mid * 100)
                if spread_pct > 0.30:
                    continue

            # Sports-preferred mode: try sports first, but accept
            # non-sports if no sports candidates pass the filter.
            # (Tracked via is_sports flag for later prioritisation.)

            # Skip if we're at position limit for this market
            from app.pipeline.portfolio_tracker import portfolio_state
            pos = portfolio_state.positions.get(m.ticker)
            if pos and abs(pos.position or 0) >= params.max_position_size:
                continue

            candidates.append(m)

        # If sports-only mode is on, prefer sports candidates.
        # But if ZERO sports candidates have acceptable spreads,
        # fall through to all markets so we're not completely idle.
        if self._sports_only and self._sports_detector:
            sports_cands = [c for c in candidates if self._sports_detector.is_sports_market(c)]
            if sports_cands:
                # Mix sports with some non-sports for diversification
                non_sports = [c for c in candidates if c not in sports_cands]
                return (sports_cands + non_sports[:50])[:self.config.max_candidates]
            log.debug("no_liquid_sports", total_candidates=len(candidates))

        return candidates[:self.config.max_candidates]

    async def _enrich_orderbook_depth(self, candidates: list[Market]) -> None:
        """Phase 6: Fetch L2 orderbook depth for top candidates.

        Populates the feature engine's _ob_depth_cache with aggregated
        bid/ask depth and imbalance for each ticker.  Capped at 20
        API calls per scan to avoid rate-limiting.
        """
        try:
            from app.state import state as _st
            if not _st.kalshi_api:
                return
            for m in candidates[:20]:
                try:
                    ob = await _st.kalshi_api.markets.get_orderbook(m.ticker, depth=5)
                    # Sum YES-side bid contracts across levels
                    bid_total = 0.0
                    for lvl in ob.yes_bids:
                        bid_total += float(lvl.count or 0)
                    # YES-side ask = NO-side bid (Kalshi convention)
                    ask_total = 0.0
                    for lvl in ob.no_bids:
                        ask_total += float(lvl.count or 0)
                    total = bid_total + ask_total
                    imb = (bid_total - ask_total) / total if total > 0 else 0.0
                    self._features._ob_depth_cache[m.ticker] = {
                        "bid_depth": bid_total,
                        "ask_depth": ask_total,
                        "imbalance": max(-1.0, min(1.0, imb)),
                    }
                except Exception:
                    pass  # skip this ticker — orderbook unavailable
        except Exception as e:
            log.debug("orderbook_depth_error", error=str(e))

    async def _seed_price_histories(self, candidates: list[Market]) -> None:
        """Seed price history buffers from Kalshi candlestick API.

        For markets we haven't seen before (empty history buffer),
        fetch 1-minute candles for the last 2 hours.  This gives ~120
        data points — enough for SMA-20, RSI-14, Bollinger bands,
        MACD, Hurst exponent, and other time-series features to produce
        real values instead of defaults (0.0).

        We limit API calls to MAX_SEEDS per scan to avoid rate limits.
        """
        MAX_SEEDS_PER_SCAN = 15
        seeded = 0

        for m in candidates:
            if seeded >= MAX_SEEDS_PER_SCAN:
                break
            hist = self._features._histories.get(m.ticker)
            # Only seed if history has < 10 data points (essentially fresh)
            if hist and len(hist.prices) >= 10:
                continue
            # Need series_ticker for candlestick endpoint
            series_ticker = getattr(m, 'series_ticker', None)
            if not series_ticker:
                continue
            try:
                from app.state import state as _st
                if not _st.kalshi_api:
                    continue
                import time as _time
                end_ts = int(_time.time())
                start_ts = end_ts - 14400  # 4 hours of 1-minute candles
                candles = await _st.kalshi_api.historical.get_candlesticks(
                    series_ticker=series_ticker,
                    market_ticker=m.ticker,
                    start_ts=start_ts,
                    end_ts=end_ts,
                    period_interval=1,  # 1-minute candles
                )
                if candles:
                    for c in candles:
                        ts = c.end_period_ts or end_ts
                        # Compute midpoint from yes_bid.close and yes_ask.close
                        bid_close = float(c.yes_bid.close or 0) / 100.0 if c.yes_bid and c.yes_bid.close else 0
                        ask_close = float(c.yes_ask.close or 0) / 100.0 if c.yes_ask and c.yes_ask.close else 0
                        if bid_close > 0 and ask_close > 0:
                            price = (bid_close + ask_close) / 2.0
                        elif c.price and c.price.close:
                            price = float(c.price.close) / 100.0
                        else:
                            continue
                        vol = float(c.volume or 0)
                        spread = (ask_close - bid_close) if ask_close > bid_close else 0
                        self._features.update(m.ticker, price, vol, 0, spread)
                    seeded += 1
                    log.debug("history_seeded", ticker=m.ticker, candles=len(candles))

                    # Phase 19: Also fetch 60-minute candles for 24h
                    # for deeper context (longer-term SMA, trend)
                    try:
                        start_ts_h = end_ts - 86400  # 24 hours
                        hourly = await _st.kalshi_api.historical.get_candlesticks(
                            series_ticker=series_ticker,
                            market_ticker=m.ticker,
                            start_ts=start_ts_h,
                            end_ts=start_ts,  # up to where 1-min starts
                            period_interval=60,  # 60-minute candles
                        )
                        if hourly:
                            for c in hourly:
                                ts = c.end_period_ts or end_ts
                                bid_close = float(c.yes_bid.close or 0) / 100.0 if c.yes_bid and c.yes_bid.close else 0
                                ask_close = float(c.yes_ask.close or 0) / 100.0 if c.yes_ask and c.yes_ask.close else 0
                                if bid_close > 0 and ask_close > 0:
                                    price = (bid_close + ask_close) / 2.0
                                elif c.price and c.price.close:
                                    price = float(c.price.close) / 100.0
                                else:
                                    continue
                                vol = float(c.volume or 0)
                                spread = (ask_close - bid_close) if ask_close > bid_close else 0
                                self._features.update(m.ticker, price, vol, 0, spread)
                    except Exception:
                        pass  # hourly candles are bonus, not critical
            except Exception:
                pass  # Non-critical — features will just use fewer data points

    def _count_open_positions(self) -> int:
        """Count current open positions for portfolio limit enforcement."""
        from app.pipeline.portfolio_tracker import portfolio_state
        return sum(
            1 for pos in portfolio_state.positions.values()
            if (pos.position or 0) != 0
        )

    async def _cleanup_stale_orders(self) -> None:
        """Phase 17: Cancel orders that haven't filled within timeout.

        Limit orders that rest in the book too long waste capital
        (reserved balance) and may fill at stale prices.  Cancel
        after 5 minutes and let the next scan re-evaluate.
        """
        if not self._pending_orders:
            return

        now = time.time()
        stale_ids = [
            oid for oid, info in self._pending_orders.items()
            if now - info.get("placed_at", now) > self._ORDER_STALE_SECONDS
        ]
        if not stale_ids:
            return

        try:
            from app.state import state as _st
            if not _st.kalshi_api:
                return
            for oid in stale_ids:
                try:
                    await _st.kalshi_api.orders.cancel_order(oid)
                    self._fill_rate_stats["cancelled"] += 1
                    log.info("stale_order_cancelled", order_id=oid,
                             age_s=f"{now - self._pending_orders[oid].get('placed_at', now):.0f}")
                except Exception:
                    pass  # order may have already filled
                self._pending_orders.pop(oid, None)
        except Exception as e:
            log.debug("cleanup_stale_orders_error", error=str(e))

    def _kelly_size(
        self,
        prediction: Prediction,
        features: MarketFeatures,
        params: StrategyParams,
        market: Market | None = None,
    ) -> float:
        """
        Kelly criterion for binary contracts.

        Binary contract math:
          Buy at cost c (0-1 range, e.g., 0.40 = 40¢ per contract)
          Win:  receive $1, net profit = (1 - c)
          Lose: lose entire cost c

        Kelly optimal fraction:  f* = (p - c) / (1 - c)
        where p = our estimated probability of winning the bet.

        We use the ACTUAL ask price from the orderbook (not mid+1¢)
        because that's what we'd really pay as a taker.
        """
        mid = features.midpoint

        if prediction.side == "yes":
            p = prediction.predicted_prob          # P(YES settles)
            # Use real ask if available — that's our actual cost
            if market and market.yes_ask is not None and float(market.yes_ask) > 0:
                c = min(float(market.yes_ask), 0.99)
            else:
                c = min(mid + 0.01, 0.99)  # fallback: mid + 1¢
        else:
            p = 1.0 - prediction.predicted_prob    # P(NO settles)
            # NO cost = 1 - yes_bid (what we pay to buy NO)
            if market and market.no_ask is not None and float(market.no_ask) > 0:
                c = min(float(market.no_ask), 0.99)
            elif market and market.yes_bid is not None and float(market.yes_bid) > 0:
                c = min(1.0 - float(market.yes_bid), 0.99)
            else:
                c = min(1.0 - mid + 0.01, 0.99)  # fallback

        # Include taker fee in cost basis — this is what we actually pay.
        # For a BUY at 40¢: real cost = 40¢ + 7¢ fee = 47¢.
        # On WIN we get $1 and pay 7¢ sell fee, net = 100 - 7 = 93¢.
        # So: net win = (93 - price*100)/100 instead of (1 - c).
        fee_per_side = TAKER_FEE_CENTS / 100.0  # 0.07
        real_cost = c + fee_per_side             # cost + buy fee
        net_win = (1.0 - fee_per_side) - c       # payout minus sell fee minus cost

        # No edge or degenerate cost — skip
        if p <= real_cost or real_cost <= 0.01 or real_cost >= 0.99 or net_win <= 0:
            return 0.0

        # Fee-adjusted Kelly: f* = (p * net_win - (1-p) * real_cost) / net_win
        # Simplified for binary: f* = (p - real_cost) / net_win
        kelly = (p - real_cost) / net_win

        # Apply fractional Kelly for safety
        adjusted = kelly * params.kelly_fraction

        # Scale by uncertainty — high prediction variance = smaller position.
        # This is standard Bayesian Kelly: when model is uncertain, shrink
        # the bet toward zero.  prediction_std of 0.15+ means "very unsure".
        if hasattr(prediction, 'prediction_std') and prediction.prediction_std > 0:
            uncertainty_scale = max(0.2, 1.0 - prediction.prediction_std * 3.0)
            adjusted *= uncertainty_scale

        # Clamp to [0, 1]
        return max(0.0, min(adjusted, 1.0))

    def _compute_price(self, prediction: Prediction, features: MarketFeatures,
                        market: Market | None = None) -> int:
        """
        Compute optimal order price — spread-aware placement.

        Strategy for profitability:
        - Use REAL bid/ask from the market when available
        - Always try to be maker (inside spread) to avoid paying spread
        - Confidence-aware: high confidence → cross spread for fill
        - Low confidence → post passive limit for better fill price
        """
        mid = features.midpoint
        spread_cents = max(int(features.spread * 100), 1)
        confidence = prediction.confidence

        # Extract real bid/ask when market data is available
        if market:
            real_yes_bid = float(market.yes_bid) if market.yes_bid is not None else None
            real_yes_ask = float(market.yes_ask) if market.yes_ask is not None else None
            real_no_bid = float(market.no_bid) if market.no_bid is not None else None
            real_no_ask = float(market.no_ask) if market.no_ask is not None else None
        else:
            real_yes_bid = real_yes_ask = real_no_bid = real_no_ask = None

        if prediction.side == "yes":
            bid = real_yes_bid if real_yes_bid and real_yes_bid > 0 else (mid - features.spread / 2)
            ask = real_yes_ask if real_yes_ask and real_yes_ask > 0 else (mid + features.spread / 2)

            if spread_cents <= 2:
                # Tight spread — take the ask for guaranteed fill
                price_frac = min(ask, 0.99)
            elif confidence >= 0.75:
                # High confidence — cross spread, get filled quickly
                price_frac = min(ask, 0.99)
            elif confidence >= 0.60:
                # Medium confidence — place inside the spread (bid + 1¢)
                price_frac = min(bid + 0.01, ask)
            else:
                # Lower confidence — be passive, place at bid + 1¢
                price_frac = max(bid + 0.01, 0.01)
        else:
            # For NO contracts: use real no_bid/no_ask when available
            if real_no_bid is not None and real_no_ask is not None and real_no_ask > 0:
                no_bid = real_no_bid if real_no_bid > 0 else 0.01
                no_ask = real_no_ask
            else:
                no_bid = 1.0 - (mid + features.spread / 2)
                no_ask = 1.0 - (mid - features.spread / 2)

            if spread_cents <= 2:
                price_frac = min(no_ask, 0.99)
            elif confidence >= 0.75:
                price_frac = min(no_ask, 0.99)
            elif confidence >= 0.60:
                price_frac = min(no_bid + 0.01, no_ask)
            else:
                price_frac = max(no_bid + 0.01, 0.01)

        return max(1, min(99, int(price_frac * 100)))

    # ── Scheduled Tasks ───────────────────────────────────────────────

    def _try_load_latest_checkpoint(self) -> None:
        """Try to load the latest model checkpoint from disk.

        This is critical: without this, every restart loses the trained model
        and falls back to the heuristic (which has no real predictive power).
        """
        try:
            ckpt_dir = Path(self.config.checkpoint_dir)
            if not ckpt_dir.exists():
                log.info("no_checkpoint_dir", path=str(ckpt_dir))
                return

            pkl_files = sorted(
                ckpt_dir.glob("frankenstein_gen*.pkl"),
                key=lambda f: f.stat().st_mtime,
                reverse=True,
            )
            if not pkl_files:
                log.info("no_checkpoints_found", path=str(ckpt_dir))
                return

            latest = pkl_files[0]
            self._model.load(str(latest))

            # Extract generation from filename (frankenstein_genN_...)
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

            log.info(
                "\U0001f9df\u2705 CHECKPOINT RESTORED",
                path=str(latest),
                generation=gen,
                version=self._state.model_version,
                is_trained=self._model.is_trained,
            )
        except Exception as e:
            log.error("checkpoint_load_failed", error=str(e))

    async def _auto_bootstrap(self) -> None:
        """Auto-bootstrap training data on cold start (runs once at startup).
        
        Phase 10: DO NOT clear memory on restart. Accumulated real trade
        data is VALUABLE — it's what teaches the model. The old behavior
        wiped all real trades and re-injected synthetic bootstrap data,
        which was the #1 reason the model never improved across restarts.
        
        Now: only bootstrap if memory is truly empty (first ever start).
        """
        # Wait for market cache to populate first
        for _ in range(30):
            if market_cache.get_active():
                break
            await asyncio.sleep(2)

        # Only bootstrap if memory is truly empty — don't wipe real data
        if self.memory.total_resolved >= self.learner.min_samples:
            log.info(
                "🧟🧪 SKIP BOOTSTRAP: already have enough data",
                resolved=self.memory.total_resolved,
                min_needed=self.learner.min_samples,
            )
            # Still trigger a retrain to make sure model is up to date
            try:
                await self.force_retrain()
            except Exception as e:
                log.warning("startup_retrain_failed", error=str(e))
            return

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

        # Phase 18: Train category-specific specialist models
        try:
            cat_models = await self.learner.train_category_models()
            if cat_models:
                self._category_models = cat_models
                log.info("category_models_updated", count=len(cat_models),
                         categories=list(cat_models.keys()))
        except Exception as e:
            log.debug("category_model_training_error", error=str(e))

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
        """Periodic health check — monitor and retrain, NEVER pause.

        Frankenstein trades 24/7.  Every trade (win or loss) is data.
        Pausing destroys the feedback loop the model needs to learn.
        We only force a retrain if the model is degrading.
        """
        # Always ensure trading is on — undo any stale pause state
        if self._state.is_paused:
            self._state.is_paused = False
            self._state.pause_reason = ""
            log.info("🧟✅ FRANKENSTEIN UNPAUSED (24/7 mode)")

        # Log health warnings (for dashboard visibility)
        _should_pause, _reason = self.performance.should_pause_trading()
        if _reason != "ok":
            log.info("health_note", reason=_reason)

        # Check for model degradation — retrain, but don't pause
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
        
        Resolution strategy (tries multiple methods):
        1. Kalshi settlements API (real/demo trading)
        2. Market status check via API (checks if settled)
        3. Paper trading: check market cache for settled/extreme prices
        4. Timeout after 48 hours → expired
        """
        pending = self.memory.get_pending_trades()
        if not pending:
            return

        resolved_count = 0

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
                # Skip exit/sell records — they don't need resolution
                if trade.action == "sell":
                    self.memory.resolve_trade(
                        trade.trade_id, TradeOutcome.BREAKEVEN,
                    )
                    continue

                # Method 1: Check settlements API
                settlement = settlements_by_ticker.get(trade.ticker)
                if settlement and settlement.market_result is not None:
                    result_str = settlement.market_result.value.lower()
                    correct = trade.predicted_side == result_str

                    # Record calibration data
                    if result_str in ("yes", "no") and hasattr(self._model, 'calibration'):
                        actual_yes = 1 if result_str == "yes" else 0
                        raw_p = getattr(trade, 'raw_predicted_prob', 0.0) or trade.predicted_prob
                        self._model.calibration.record(raw_p, actual_yes)

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
                        self._report_sports_outcome(trade, pnl_cents)
                    else:
                        pnl_cents = -trade.total_cost_cents
                        self.memory.resolve_trade(
                            trade.trade_id, TradeOutcome.LOSS,
                            pnl_cents=pnl_cents, market_result=result_str,
                        )
                        self._report_sports_outcome(trade, pnl_cents)
                    resolved_count += 1
                    continue

                # Method 2: Check market status via API or cache
                resolved_via_market = False
                try:
                    # Check the market cache first (free, no API call)
                    cached_market = market_cache.get(trade.ticker)
                    market_settled = False
                    market_result_str = None

                    if cached_market:
                        status_val = cached_market.status.value if hasattr(cached_market.status, 'value') else str(cached_market.status)
                        if status_val.lower() in ("settled", "closed"):
                            market_settled = True
                            # Infer result from final price
                            final_price = float(cached_market.last_price or cached_market.midpoint or 0.5)
                            if isinstance(final_price, int):
                                final_price = final_price / 100
                            if final_price >= 0.95:
                                market_result_str = "yes"
                            elif final_price <= 0.05:
                                market_result_str = "no"

                    # If cache doesn't show settled, try API
                    if not market_settled:
                        from app.state import state as _st
                        if _st.kalshi_api:
                            mkt = await _st.kalshi_api.markets.get_market(trade.ticker)
                            status_val = mkt.status.value if hasattr(mkt.status, 'value') else str(mkt.status)
                            if status_val.lower() in ("settled", "closed"):
                                market_settled = True
                                result_attr = getattr(mkt, 'result', None) or getattr(mkt, 'market_result', None)
                                if result_attr:
                                    market_result_str = result_attr.value.lower() if hasattr(result_attr, 'value') else str(result_attr).lower()
                                else:
                                    fp = float(mkt.last_price or 0.5)
                                    if isinstance(fp, int):
                                        fp = fp / 100
                                    if fp >= 0.95:
                                        market_result_str = "yes"
                                    elif fp <= 0.05:
                                        market_result_str = "no"

                    if market_settled and market_result_str:
                        correct = trade.predicted_side == market_result_str

                        if hasattr(self._model, 'calibration'):
                            actual_yes = 1 if market_result_str == "yes" else 0
                            raw_p = getattr(trade, 'raw_predicted_prob', 0.0) or trade.predicted_prob
                            self._model.calibration.record(raw_p, actual_yes)

                        if correct:
                            pnl_cents = trade.count * 100 - trade.total_cost_cents
                            self.memory.resolve_trade(
                                trade.trade_id, TradeOutcome.WIN,
                                pnl_cents=pnl_cents, market_result=market_result_str,
                            )
                        else:
                            pnl_cents = -trade.total_cost_cents
                            self.memory.resolve_trade(
                                trade.trade_id, TradeOutcome.LOSS,
                                pnl_cents=pnl_cents, market_result=market_result_str,
                            )
                        self._report_sports_outcome(trade, pnl_cents)
                        resolved_count += 1
                        resolved_via_market = True
                    elif market_settled:
                        # Market settled but can't determine result
                        self.memory.resolve_trade(
                            trade.trade_id, TradeOutcome.EXPIRED,
                        )
                        resolved_count += 1
                        resolved_via_market = True
                except Exception:
                    pass

                # Method 3: Paper trading fast resolution
                # For paper trading, if market price has moved decisively,
                # we can resolve based on price movement even before settlement.
                # This gives the model faster feedback to learn from.
                if not resolved_via_market:
                    try:
                        cached = market_cache.get(trade.ticker)
                        if cached:
                            current_price = float(cached.last_price or cached.midpoint or 0)
                            if isinstance(current_price, int):
                                current_price = current_price / 100
                            
                            # If price moved to extreme (>99¢ or <1¢), resolve
                            # Phase 5: Tightened from 95/5 → 99/1. The old
                            # thresholds resolved trades too early when
                            # markets were still in play, fabricating outcomes.
                            if current_price >= 0.99:
                                correct = trade.predicted_side == "yes"
                                pnl_cents = (trade.count * 100 - trade.total_cost_cents) if correct else -trade.total_cost_cents
                                self.memory.resolve_trade(
                                    trade.trade_id,
                                    TradeOutcome.WIN if correct else TradeOutcome.LOSS,
                                    pnl_cents=pnl_cents,
                                    market_result="yes",
                                )
                                resolved_count += 1
                                continue
                            elif current_price <= 0.01:
                                correct = trade.predicted_side == "no"
                                pnl_cents = (trade.count * 100 - trade.total_cost_cents) if correct else -trade.total_cost_cents
                                self.memory.resolve_trade(
                                    trade.trade_id,
                                    TradeOutcome.WIN if correct else TradeOutcome.LOSS,
                                    pnl_cents=pnl_cents,
                                    market_result="no",
                                )
                                resolved_count += 1
                                continue
                    except Exception:
                        pass

                # Method 4: Timeout after 48 hours → expired
                # Phase 9: REMOVED the 12h timeout inference hack.
                # The old code inferred results from price at 65%/35%
                # thresholds — this FABRICATED outcomes and poisoned
                # training data. Now we only expire after 48h and
                # ONLY if the market hasn't settled via Methods 1-3.
                if time.time() - trade.timestamp > 172800:  # 48 hours
                    self.memory.resolve_trade(
                        trade.trade_id, TradeOutcome.EXPIRED,
                    )
                    resolved_count += 1
            except Exception as e:
                log.debug("outcome_check_error", ticker=trade.ticker, error=str(e))

        if resolved_count > 0:
            log.info("🧟📊 OUTCOMES_RESOLVED", count=resolved_count, remaining=len(pending) - resolved_count)

    def _report_sports_outcome(self, trade: TradeRecord, pnl_cents: int) -> None:
        """FIX #7: Report trade outcome to sports monitor for performance tracking."""
        # Phase 9: Update category win/loss tracking
        try:
            from app.frankenstein.categories import detect_category
            cat = detect_category(trade.market_title or "", trade.category or "", ticker=trade.ticker)
            if cat not in self._category_stats:
                self._category_stats[cat] = {"wins": 0, "losses": 0}
            if pnl_cents > 0:
                self._category_stats[cat]["wins"] += 1
            elif pnl_cents < 0:
                self._category_stats[cat]["losses"] += 1
        except Exception:
            pass

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

        # Compute learning mode status
        snap = self.performance.compute_snapshot() if self.performance._snapshots else None
        real_trades = snap.real_trades if snap else 0
        in_learning_mode = real_trades < 100

        return {
            "name": "Frankenstein",
            "version": self._state.model_version,
            "generation": self._state.generation,
            "is_alive": self._state.is_alive,
            "is_trading": self._state.is_trading and not self._state.is_paused,
            "is_paused": self._state.is_paused,
            "pause_reason": self._state.pause_reason,
            "learning_mode": in_learning_mode,
            "learning_progress": f"{min(real_trades, 100)}/100 real trades",
            "real_trades": real_trades,
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
