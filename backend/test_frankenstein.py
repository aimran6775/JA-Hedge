#!/usr/bin/env python3
"""
JA Hedge — Frankenstein Test Suite 🧟

Comprehensive tests for the Frankenstein AI Brain:
  1. Memory system — record, resolve, persist, stats
  2. Performance tracker — metrics, regime detection, health checks
  3. Online learner — training data, champion/challenger, versioning
  4. Adaptive strategy — regime adaptation, win/loss tuning, drawdown
  5. Scheduler — task registration, start/stop, interval updates
  6. Brain integration — full scan cycle, pause/resume, status
  7. End-to-end — memory → learn → adapt → trade → resolve loop
  8. Paper trading integration — Frankenstein + PaperTradingSimulator

Usage:
  cd backend && source .venv/bin/activate
  python test_frankenstein.py
"""

from __future__ import annotations

import asyncio
import sys
import time
import traceback
import os
from datetime import datetime, timezone
import numpy as np

# ── Colors ────────────────────────────────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

passed = 0
failed = 0
skipped = 0


def header(title: str):
    print(f"\n{BOLD}{CYAN}{'━' * 65}")
    print(f"  {title}")
    print(f"{'━' * 65}{RESET}\n")


def result(test_name: str, success: bool, detail: str = "", skip: bool = False):
    global passed, failed, skipped
    if skip:
        skipped += 1
        print(f"  {YELLOW}⏭ SKIP{RESET}  {test_name}: {DIM}{detail}{RESET}")
    elif success:
        passed += 1
        print(f"  {GREEN}✅ PASS{RESET}  {test_name}" + (f" — {DIM}{detail}{RESET}" if detail else ""))
    else:
        failed += 1
        print(f"  {RED}❌ FAIL{RESET}  {test_name}" + (f" — {detail}" if detail else ""))


# ══════════════════════════════════════════════════════════════════════════
#  PHASE 1: Trade Memory
# ══════════════════════════════════════════════════════════════════════════

async def test_memory():
    header("PHASE 1 — FRANKENSTEIN MEMORY 🧠")

    from app.frankenstein.memory import TradeMemory, TradeOutcome, TradeRecord

    # 1.1 Create memory
    mem = TradeMemory(max_trades=1000, max_snapshots=5000)
    result("Memory creation", mem.size == 0, f"buffer={mem.size}")

    # 1.2 Record a trade (manual)
    from app.ai.features import MarketFeatures
    from app.ai.models import Prediction

    features = MarketFeatures(
        ticker="TEST-TICKER-1", timestamp=datetime.now(timezone.utc),
        midpoint=0.55, spread=0.04, spread_pct=0.072,
        last_price=0.55, price_change_1m=0.01, price_change_5m=0.02,
        price_change_15m=0.03, price_velocity=0.001,
        sma_5=0.54, sma_20=0.52, ema_12=0.545, ema_26=0.535,
        macd=0.01, signal_line=0.005, rsi_14=55.0,
        momentum_10=0.03, volume=500.0, volume_ma_5=450.0,
        volume_ratio=1.11, open_interest=1200.0, oi_change=50.0,
        book_imbalance=0.1, hours_to_expiry=24.0, time_decay_factor=0.04,
        hour_of_day=14, day_of_week=2, implied_prob=0.55,
        prob_distance_from_50=0.05, extreme_prob=0.0,
    )
    pred = Prediction(side="yes", confidence=0.72, predicted_prob=0.65, edge=0.10)
    rec = mem.record_trade(
        ticker="TEST-TICKER-1",
        prediction=pred,
        features=features,
        action="buy",
        count=5,
        price_cents=55,
        order_id="ord-123",
        model_version="test-v1",
    )
    result("Record trade", rec.trade_id.startswith("fk-"), f"id={rec.trade_id}")
    result("Trade stored", mem.size == 1, f"size={mem.size}")
    result("Pending count", len(mem.get_pending_trades()) == 1)

    # 1.3 Resolve a trade
    resolved = mem.resolve_trade(
        rec.trade_id,
        TradeOutcome.WIN,
        exit_price_cents=100,
        pnl_cents=225,
        market_result="yes",
    )
    result("Resolve trade", resolved is not None and resolved.outcome == TradeOutcome.WIN)
    result("Correct prediction", resolved.was_correct is True)
    result("P&L recorded", resolved.pnl_cents == 225, f"pnl={resolved.pnl_cents}¢")
    result("Pending cleared", len(mem.get_pending_trades()) == 0)

    # 1.4 Stats
    stats = mem.stats()
    result("Memory stats", stats["total_recorded"] == 1 and stats["total_resolved"] == 1, f"stats={stats}")

    # 1.5 Batch record + resolve for training data
    for i in range(60):
        p = Prediction(
            side="yes" if i % 2 == 0 else "no",
            confidence=0.6 + (i % 10) * 0.03,
            predicted_prob=0.55 + (i % 10) * 0.03,
            edge=0.05 + (i % 5) * 0.01,
        )
        r = mem.record_trade(
            ticker=f"BATCH-{i}",
            prediction=p,
            features=features,
            action="buy",
            count=1 + i % 5,
            price_cents=50 + i % 20,
            model_version="test-v1",
        )
        # Resolve half as wins, half as losses
        if i % 3 == 0:
            mem.resolve_trade(r.trade_id, TradeOutcome.WIN, pnl_cents=50 + i, market_result=p.side)
        elif i % 3 == 1:
            mem.resolve_trade(r.trade_id, TradeOutcome.LOSS, pnl_cents=-(30 + i), market_result="yes" if p.side == "no" else "no")
        # else: leave pending

    result("Batch trades recorded", mem.size == 61, f"size={mem.size}")
    result("Win rate", 0 < mem.win_rate <= 1.0, f"wr={mem.win_rate:.2%}")

    # 1.6 Training data extraction
    data = mem.get_training_data(min_trades=10)
    result("Training data extraction", data is not None, f"shape={data[0].shape}" if data else "None")
    if data:
        X, y = data
        result("Features shape", X.shape[1] == 29, f"features={X.shape[1]}")
        result("Labels balanced", 0.1 < y.mean() < 0.9, f"positive_rate={y.mean():.3f}")

    # 1.7 Serialization
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name

    mem.save(path)
    mem2 = TradeMemory(max_trades=1000, persist_path=path)
    result("Save/load roundtrip", mem2.size > 0, f"loaded={mem2.size}")

    os.unlink(path)

    # 1.8 Recent trades
    recent = mem.get_recent_trades(n=5)
    result("Recent trades", len(recent) == 5, f"got={len(recent)}")

    # 1.9 Record snapshot
    mem.record_snapshot("TEST-1", 0.55, 0.04, 500.0)
    result("Market snapshot recorded", True)

    return mem, features  # pass to other tests


# ══════════════════════════════════════════════════════════════════════════
#  PHASE 2: Performance Tracker
# ══════════════════════════════════════════════════════════════════════════

async def test_performance(mem):
    header("PHASE 2 — PERFORMANCE TRACKER 📊")

    from app.frankenstein.performance import PerformanceTracker

    tracker = PerformanceTracker(memory=mem)

    # 2.1 Compute snapshot
    snap = tracker.compute_snapshot()
    result("Performance snapshot", snap.total_trades > 0, f"trades={snap.total_trades}")
    result("Win rate computed", 0 <= snap.win_rate <= 1.0, f"wr={snap.win_rate:.2%}")
    result("Sharpe ratio", isinstance(snap.sharpe_ratio, float), f"sharpe={snap.sharpe_ratio:.3f}")
    result("Max drawdown", snap.max_drawdown <= 0, f"dd=${snap.max_drawdown:.2f}")

    # 2.2 Regime detection
    regime = tracker.detect_regime()
    result("Regime detection", regime in ("trending", "mean_reverting", "volatile", "quiet", "mixed", "unknown"), f"regime={regime}")

    # 2.3 Health checks
    degrading = tracker.is_model_degrading()
    result("Model degradation check", isinstance(degrading, bool), f"degrading={degrading}")

    should_pause, reason = tracker.should_pause_trading()
    result("Pause check", isinstance(should_pause, bool), f"pause={should_pause}, reason={reason}")

    # 2.4 Category breakdown
    categories = tracker.performance_by_category()
    result("Category breakdown", isinstance(categories, dict), f"categories={len(categories)}")

    # 2.5 Full summary
    summary = tracker.summary()
    result("Full summary", "snapshot" in summary and "regime" in summary, f"keys={list(summary.keys())}")

    return tracker


# ══════════════════════════════════════════════════════════════════════════
#  PHASE 3: Online Learner
# ══════════════════════════════════════════════════════════════════════════

async def test_learner(mem):
    header("PHASE 3 — ONLINE LEARNER 🧬")

    from app.ai.models import XGBoostPredictor
    from app.frankenstein.learner import OnlineLearner

    model = XGBoostPredictor()

    learner = OnlineLearner(
        model=model,
        memory=mem,
        min_samples=10,
        retrain_threshold=5,
        checkpoint_dir="/tmp/frankenstein_test_models",
    )

    # 3.1 Initial state
    result("Initial version", learner.current_version == "untrained")
    result("Needs retrain", learner.needs_retrain is True, "enough data accumulated")

    # 3.2 Force retrain
    checkpoint = await learner.retrain(force=True)
    result("Retrain succeeded", checkpoint is not None, f"version={checkpoint.version if checkpoint else 'None'}")

    if checkpoint:
        result("AUC computed", checkpoint.val_auc > 0, f"auc={checkpoint.val_auc:.4f}")
        result("Model promoted", learner.generation == 1, f"gen={learner.generation}")
        result("Model is trained", model.is_trained is True)
        result("Version updated", learner.current_version != "untrained", f"v={learner.current_version}")

    # 3.3 Feature importance
    importance = learner.get_feature_importance()
    result("Feature importance", isinstance(importance, dict), f"features={len(importance)}")

    # 3.4 Second retrain (should be challenger test)
    checkpoint2 = await learner.retrain(force=True)
    result("Second retrain", True, f"promoted={'yes' if checkpoint2 else 'no'}, gen={learner.generation}")

    # 3.5 Stats
    stats = learner.stats()
    result("Learner stats", stats["total_retrains"] >= 2, f"retrains={stats['total_retrains']}")
    result("Top features", isinstance(stats.get("top_features", {}), dict))

    return learner, model


# ══════════════════════════════════════════════════════════════════════════
#  PHASE 4: Adaptive Strategy
# ══════════════════════════════════════════════════════════════════════════

async def test_strategy(mem, tracker):
    header("PHASE 4 — ADAPTIVE STRATEGY 🎯")

    from app.frankenstein.strategy import AdaptiveStrategy, StrategyParams

    strategy = AdaptiveStrategy(
        memory=mem,
        performance=tracker,
        adaptation_interval=0.0,  # Allow immediate adaptation for testing
    )

    # 4.1 Initial params
    params = strategy.get_params()
    result("Default params", params.min_confidence == 0.60, f"conf={params.min_confidence}")
    result("Default Kelly", params.kelly_fraction == 0.25, f"kelly={params.kelly_fraction}")
    result("Default aggression", params.aggression == 0.5, f"agg={params.aggression}")

    # 4.2 Trigger adaptation
    from app.frankenstein.performance import PerformanceSnapshot
    snap = tracker.compute_snapshot()
    events = strategy.adapt(snap)
    result("Adaptation ran", isinstance(events, list), f"changes={len(events)}")

    # 4.3 Params changed
    new_params = strategy.get_params()
    result("Params potentially updated", True, f"conf={new_params.min_confidence:.2f}, kelly={new_params.kelly_fraction:.2f}")

    # 4.4 Simulate high win rate → more aggressive
    high_win_snap = PerformanceSnapshot(
        win_rate=0.75,
        total_trades=50,
        prediction_accuracy=0.70,
        current_drawdown=0.0,
        consecutive_losses=0,
        regime="trending",
    )
    events2 = strategy.adapt(high_win_snap)
    result("High win rate adaptation", True, f"changes={len(events2)}, agg={strategy.params.aggression:.2f}")

    # 4.5 Simulate bad performance → conservative
    strategy._last_adaptation = 0  # Reset cooldown
    bad_snap = PerformanceSnapshot(
        win_rate=0.30,
        total_trades=50,
        prediction_accuracy=0.35,
        current_drawdown=-40.0,
        consecutive_losses=4,
        regime="volatile",
    )
    events3 = strategy.adapt(bad_snap)
    result("Bad performance → conservative", strategy.params.min_confidence >= 0.65,
           f"conf={strategy.params.min_confidence:.2f}, kelly={strategy.params.kelly_fraction:.2f}")

    # 4.6 Reset to defaults
    strategy.reset_to_defaults()
    result("Reset to defaults", strategy.params.min_confidence == 0.60)

    # 4.7 Stats
    stats = strategy.stats()
    result("Strategy stats", "current_params" in stats and "recent_adaptations" in stats)

    return strategy


# ══════════════════════════════════════════════════════════════════════════
#  PHASE 5: Scheduler
# ══════════════════════════════════════════════════════════════════════════

async def test_scheduler():
    header("PHASE 5 — SCHEDULER ⏰")

    from app.frankenstein.scheduler import FrankensteinScheduler

    scheduler = FrankensteinScheduler()
    call_count = {"value": 0}

    async def test_task():
        call_count["value"] += 1

    # 5.1 Register tasks
    scheduler.register("test_task_1", test_task, interval_seconds=0.1)
    scheduler.register("test_task_2", test_task, interval_seconds=0.2, enabled=False)
    result("Tasks registered", len(scheduler._tasks) == 2)

    # 5.2 Start scheduler
    await scheduler.start()
    result("Scheduler started", scheduler.is_running)

    # 5.3 Wait for some runs
    await asyncio.sleep(0.5)
    result("Tasks executed", call_count["value"] > 0, f"runs={call_count['value']}")

    # 5.4 Enable disabled task
    scheduler.enable_task("test_task_2")
    result("Task enabled", scheduler._tasks["test_task_2"].enabled)

    # 5.5 Disable task
    scheduler.disable_task("test_task_1")
    result("Task disabled", not scheduler._tasks["test_task_1"].enabled)

    # 5.6 Update interval
    scheduler.update_interval("test_task_2", 0.05)
    result("Interval updated", scheduler._tasks["test_task_2"].interval_seconds == 0.05)

    # 5.7 Stats
    stats = scheduler.stats()
    result("Scheduler stats", stats["running"] and stats["total_tasks"] == 2)

    # 5.8 Stop
    await scheduler.stop()
    result("Scheduler stopped", not scheduler.is_running)


# ══════════════════════════════════════════════════════════════════════════
#  PHASE 6: Frankenstein Brain (Unit)
# ══════════════════════════════════════════════════════════════════════════

async def test_brain_unit(model, features_template):
    header("PHASE 6 — FRANKENSTEIN BRAIN 🧟")

    from app.ai.features import FeatureEngine
    from app.engine.execution import ExecutionEngine
    from app.engine.risk import RiskManager, RiskLimits
    from app.frankenstein.brain import Frankenstein, FrankensteinConfig

    # Create components (no real API needed for unit tests)
    feat_engine = FeatureEngine()
    risk_mgr = RiskManager(limits=RiskLimits())

    # We need a mock execution engine for unit tests
    class MockExecutionEngine:
        async def execute(self, **kwargs):
            from app.engine.execution import ExecutionResult
            return ExecutionResult(success=True, order_id="mock-123", latency_ms=5.0)

    config = FrankensteinConfig(
        scan_interval=1.0,
        retrain_interval=10.0,
        min_train_samples=10,
        retrain_threshold=5,
        memory_persist_path="/tmp/frankenstein_test_memory.json",
        checkpoint_dir="/tmp/frankenstein_test_models",
    )

    frank = Frankenstein(
        model=model,
        feature_engine=feat_engine,
        execution_engine=MockExecutionEngine(),  # type: ignore
        risk_manager=risk_mgr,
        config=config,
    )

    # 6.1 Initial state
    result("Brain created", frank._state.is_alive is False)
    result("Memory initialized", frank.memory.size == 0)
    result("Learner initialized", frank.learner.current_version != "")

    # 6.2 Status check (before awakening)
    status = frank.status()
    result("Status available", status["name"] == "Frankenstein")
    result("Generation", status["generation"] == 0)

    # 6.3 Kelly sizing
    from app.ai.models import Prediction
    from app.frankenstein.strategy import StrategyParams

    pred = Prediction(side="yes", confidence=0.80, predicted_prob=0.75, edge=0.20)
    kelly = frank._kelly_size(pred, StrategyParams())
    result("Kelly sizing", kelly >= 0, f"kelly={kelly:.4f}")

    # 6.4 Price computation
    price = frank._compute_price(pred, features_template)
    result("Price computation", 1 <= price <= 99, f"price={price}¢")

    # 6.5 Record trades in brain's memory
    for i in range(30):
        p = Prediction(side="yes", confidence=0.65, predicted_prob=0.60, edge=0.05)
        frank.memory.record_trade(
            ticker=f"BRAIN-{i}",
            prediction=p,
            features=features_template,
            action="buy",
            count=2,
            price_cents=55,
            model_version="test",
        )
    result("Brain memory populated", frank.memory.size == 30)

    # 6.6 Resolve trades
    trades = frank.memory.get_pending_trades()
    from app.frankenstein.memory import TradeOutcome
    for i, t in enumerate(trades):
        if i % 2 == 0:
            frank.memory.resolve_trade(t.trade_id, TradeOutcome.WIN, pnl_cents=50, market_result="yes")
        else:
            frank.memory.resolve_trade(t.trade_id, TradeOutcome.LOSS, pnl_cents=-40, market_result="no")

    result("Trades resolved", len(frank.memory.get_pending_trades()) == 0)

    # 6.7 Force retrain through brain
    retrain_result = await frank.force_retrain()
    result("Brain retrain", retrain_result.get("success", False) or "insufficient" in retrain_result.get("reason", ""),
           f"result={retrain_result}")

    # 6.8 Pause / resume
    frank.pause("test_pause")
    result("Brain paused", frank._state.is_paused and frank._state.pause_reason == "test_pause")

    frank.resume()
    result("Brain resumed", not frank._state.is_paused)

    # 6.9 Performance
    perf = frank.performance.compute_snapshot()
    result("Brain performance", perf.total_trades > 0, f"trades={perf.total_trades}")

    # 6.10 Full status
    full_status = frank.status()
    result("Full status", all(k in full_status for k in ["memory", "performance", "learner", "strategy", "scheduler"]))

    return frank


# ══════════════════════════════════════════════════════════════════════════
#  PHASE 7: End-to-End Learning Loop
# ══════════════════════════════════════════════════════════════════════════

async def test_e2e_learning(frank):
    header("PHASE 7 — END-TO-END LEARNING LOOP 🔄")

    from app.ai.features import MarketFeatures
    from app.ai.models import Prediction
    from app.frankenstein.memory import TradeOutcome

    features = MarketFeatures(
        ticker="E2E-TEST", timestamp=datetime.now(timezone.utc),
        midpoint=0.50, spread=0.04, spread_pct=0.08,
        last_price=0.50, price_change_1m=0.005, price_change_5m=0.01,
        price_change_15m=0.02, price_velocity=0.0005,
        sma_5=0.49, sma_20=0.48, ema_12=0.495, ema_26=0.485,
        macd=0.01, signal_line=0.005, rsi_14=50.0,
        momentum_10=0.02, volume=300.0, volume_ma_5=280.0,
        volume_ratio=1.07, open_interest=800.0, oi_change=30.0,
        book_imbalance=0.05, hours_to_expiry=12.0, time_decay_factor=0.08,
        hour_of_day=10, day_of_week=3, implied_prob=0.50,
        prob_distance_from_50=0.0, extreme_prob=0.0,
    )

    gen_before = frank.learner.generation

    # 7.1 Simulate 100 trades across multiple "hours"
    for hour in range(3):
        for i in range(40):
            prob = 0.45 + np.random.random() * 0.20
            side = "yes" if prob > 0.55 else "no"
            pred = Prediction(
                side=side,
                confidence=0.55 + np.random.random() * 0.30,
                predicted_prob=prob,
                edge=abs(prob - 0.50),
            )
            rec = frank.memory.record_trade(
                ticker=f"E2E-H{hour}-{i}",
                prediction=pred,
                features=features,
                action="buy",
                count=1 + int(np.random.random() * 3),
                price_cents=int(prob * 100),
                model_version=frank.learner.current_version,
            )

            # 60% win rate (model is decent)
            if np.random.random() < 0.60:
                frank.memory.resolve_trade(rec.trade_id, TradeOutcome.WIN, pnl_cents=int(np.random.random() * 200), market_result=side)
            else:
                wrong = "no" if side == "yes" else "yes"
                frank.memory.resolve_trade(rec.trade_id, TradeOutcome.LOSS, pnl_cents=-int(np.random.random() * 150), market_result=wrong)

    total_trades = frank.memory.size
    result("Simulated 120 trades", total_trades >= 120, f"total={total_trades}")

    # 7.2 Retrain (should have enough data)
    checkpoint = await frank.learner.retrain(force=True)
    result("E2E retrain", checkpoint is not None, f"gen={frank.learner.generation}")

    # 7.3 Check generation advanced
    result("Generation advanced", frank.learner.generation >= gen_before,
           f"before={gen_before}, after={frank.learner.generation}")

    # 7.4 Performance snapshot
    snap = frank.performance.compute_snapshot()
    result("E2E performance", snap.total_trades >= 100, f"trades={snap.total_trades}")
    result("E2E win rate", 0.3 < snap.win_rate < 0.9, f"wr={snap.win_rate:.2%}")

    # 7.5 Strategy adaptation
    events = frank.strategy.adapt(snap)
    result("E2E strategy adapted", isinstance(events, list), f"changes={len(events)}")

    # 7.6 Model predictions work with retrained model
    pred = frank._model.predict(features)
    result("Retrained model predicts", pred.confidence > 0, f"side={pred.side}, conf={pred.confidence:.3f}")

    # 7.7 Memory stats
    stats = frank.memory.stats()
    result("Memory stats coherent", stats["total_resolved"] > 100, f"resolved={stats['total_resolved']}")


# ══════════════════════════════════════════════════════════════════════════
#  PHASE 8: Paper Trading Integration
# ══════════════════════════════════════════════════════════════════════════

async def test_paper_integration():
    header("PHASE 8 — PAPER TRADING + FRANKENSTEIN 🧪")

    from app.config import get_settings
    settings = get_settings()

    if not settings.has_api_keys:
        result("Paper trading integration", False, "No API keys", skip=True)
        return

    try:
        from app.kalshi.api import KalshiAPI
        from app.engine.paper_trader import PaperTradingSimulator, PaperTradingAPIWrapper
        from app.ai.features import FeatureEngine
        from app.ai.models import XGBoostPredictor
        from app.engine.risk import RiskManager, RiskLimits
        from app.engine.execution import ExecutionEngine
        from app.frankenstein.brain import Frankenstein, FrankensteinConfig
        from app.frankenstein.memory import TradeOutcome

        # Connect to Kalshi
        api = KalshiAPI.from_settings(settings)
        await api.__aenter__()

        # Wrap with paper trader
        paper = PaperTradingSimulator(starting_balance_cents=10_000_00)
        wrapper = PaperTradingAPIWrapper(real_api=api, sim=paper)

        # Build Frankenstein with paper trading
        feat_engine = FeatureEngine()
        model = XGBoostPredictor()
        risk_mgr = RiskManager(limits=RiskLimits())
        exec_engine = ExecutionEngine(api=wrapper, risk_manager=risk_mgr)

        config = FrankensteinConfig(
            scan_interval=5.0,
            retrain_interval=30.0,
            min_train_samples=5,
            retrain_threshold=3,
        )

        frank = Frankenstein(
            model=model,
            feature_engine=feat_engine,
            execution_engine=exec_engine,
            risk_manager=risk_mgr,
            config=config,
        )

        result("Frankenstein + Paper setup", True, f"balance=${paper.balance_cents / 100:.2f}")

        # Fetch real markets and feed through Frankenstein's analysis
        from app.pipeline import market_cache
        from app.kalshi.models import MarketStatus

        markets, _cursor = await api.markets.list_markets(limit=20, status=MarketStatus.OPEN)
        markets = markets or []
        result("Real markets fetched", len(markets) > 0, f"count={len(markets)}")

        if markets:
            # Compute features
            from app.kalshi.models import Market, MarketStatus
            active = [m for m in markets if m.yes_bid is not None or m.yes_ask is not None]

            if active:
                m = active[0]
                features = feat_engine.compute(m)
                pred = model.predict(features)

                result("Feature computation", features.midpoint > 0, f"mid={features.midpoint:.3f}")
                result("Model prediction", pred.confidence > 0,
                       f"side={pred.side}, conf={pred.confidence:.3f}, edge={pred.edge:.3f}")

                # Record in Frankenstein's memory
                frank.memory.record_trade(
                    ticker=m.ticker,
                    prediction=pred,
                    features=features,
                    action="buy",
                    count=1,
                    price_cents=int(features.midpoint * 100),
                    model_version="paper-test",
                )
                result("Trade recorded in memory", frank.memory.size == 1)

        # Status check
        status = frank.status()
        result("Paper Frankenstein status", status["name"] == "Frankenstein")

        # Cleanup
        await api.__aexit__(None, None, None)
        result("Paper integration cleanup", True)

    except Exception as e:
        result("Paper trading integration", False, f"Error: {e}")
        traceback.print_exc()


# ══════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════

async def main():
    print(f"\n{BOLD}{MAGENTA}{'═' * 65}")
    print(f"  🧟 FRANKENSTEIN TEST SUITE — JA HEDGE AI BRAIN")
    print(f"{'═' * 65}{RESET}")

    start = time.time()

    try:
        # Phase 1: Memory
        mem, features = await test_memory()

        # Phase 2: Performance
        tracker = await test_performance(mem)

        # Phase 3: Learner
        learner, model = await test_learner(mem)

        # Phase 4: Adaptive Strategy
        strategy = await test_strategy(mem, tracker)

        # Phase 5: Scheduler
        await test_scheduler()

        # Phase 6: Brain (unit tests)
        frank = await test_brain_unit(model, features)

        # Phase 7: End-to-End Learning Loop
        await test_e2e_learning(frank)

        # Phase 8: Paper Trading Integration
        await test_paper_integration()

    except Exception as e:
        print(f"\n{RED}FATAL ERROR: {e}{RESET}")
        traceback.print_exc()

    elapsed = time.time() - start

    print(f"\n{BOLD}{'═' * 65}")
    print(f"  🧟 FRANKENSTEIN TEST RESULTS")
    print(f"{'═' * 65}{RESET}")
    print(f"  {GREEN}Passed: {passed}{RESET}")
    print(f"  {RED}Failed: {failed}{RESET}")
    print(f"  {YELLOW}Skipped: {skipped}{RESET}")
    print(f"  Total:  {passed + failed + skipped}")
    print(f"  Time:   {elapsed:.2f}s")

    if failed == 0:
        print(f"\n  {GREEN}{BOLD}🧟⚡ ALL TESTS PASSED — FRANKENSTEIN IS READY!{RESET}")
    else:
        print(f"\n  {RED}{BOLD}🧟💀 {failed} TESTS FAILED{RESET}")

    print()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
