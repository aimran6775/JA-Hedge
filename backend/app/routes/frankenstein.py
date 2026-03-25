"""
JA Hedge — Frankenstein API Routes.

Endpoints to monitor, control, and interact with the
Frankenstein AI brain.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.state import state
from app.logging_config import get_logger
from app.frankenstein.confidence import explain_decision_logic

log = get_logger("routes.frankenstein")
router = APIRouter(prefix="/frankenstein", tags=["frankenstein"])


def _get_frank():
    """Get Frankenstein or raise 503."""
    if state.frankenstein is None:
        raise HTTPException(503, "Frankenstein not initialized")
    return state.frankenstein


# ── Status ────────────────────────────────────────────────────────────────────

@router.get("/cache-check")
async def cache_check() -> dict:
    """Minimal cache diagnostic."""
    try:
        from app.pipeline import market_cache
        all_m = market_cache.get_all()
        active_m = market_cache.get_active()
        sample = []
        for m in all_m[:3]:
            sample.append({
                "ticker": m.ticker[:30],
                "status_type": type(m.status).__name__,
                "status_val": str(m.status),
            })
        return {
            "total": len(all_m),
            "active": len(active_m),
            "sample": sample,
        }
    except Exception as e:
        import traceback
        return {"error": str(e), "tb": traceback.format_exc()}


@router.get("/status")
async def frankenstein_status() -> dict:
    """Get full Frankenstein status — the brain's self-report."""
    frank = _get_frank()
    return frank.status()


@router.get("/health")
async def frankenstein_health() -> dict:
    """Quick health check for Frankenstein."""
    frank = _get_frank()
    s = frank._state
    should_pause, reason = frank.performance.should_pause_trading()
    return {
        "alive": s.is_alive,
        "trading": s.is_trading and not s.is_paused,
        "paused": s.is_paused,
        "pause_reason": s.pause_reason,
        "generation": s.generation,
        "model_version": s.model_version,
        "total_trades": s.total_trades_executed,
        "should_pause": should_pause,
        "should_pause_reason": reason,
    }


# ── Controls ──────────────────────────────────────────────────────────────────

@router.post("/awaken")
async def awaken_frankenstein() -> dict:
    """🧟⚡ Bring Frankenstein to life."""
    frank = _get_frank()
    if frank._state.is_alive:
        return {"status": "already_alive", "message": "Frankenstein is already awake!"}
    await frank.awaken()
    return {"status": "alive", "message": "🧟⚡ FRANKENSTEIN IS ALIVE!"}


@router.post("/sleep")
async def sleep_frankenstein() -> dict:
    """🧟💤 Put Frankenstein to sleep."""
    frank = _get_frank()
    await frank.sleep()
    return {"status": "sleeping", "message": "🧟💤 Frankenstein is sleeping."}


@router.post("/pause")
async def pause_frankenstein(reason: str = "manual") -> dict:
    """Pause Frankenstein's trading."""
    frank = _get_frank()
    frank.pause(reason)
    return {"status": "paused", "reason": reason}


@router.post("/resume")
async def resume_frankenstein() -> dict:
    """Resume Frankenstein's trading."""
    frank = _get_frank()
    frank.resume()
    return {"status": "resumed"}


# ── Learning ──────────────────────────────────────────────────────────────────

@router.post("/retrain")
async def force_retrain() -> dict:
    """Force an immediate model retraining."""
    frank = _get_frank()
    result = await frank.force_retrain()
    return result


@router.post("/bootstrap")
async def bootstrap_training_data() -> dict:
    """Bootstrap training data from settled/active markets to solve cold-start."""
    frank = _get_frank()
    result = await frank.bootstrap_training_data()
    return result


@router.post("/purge-bootstrap")
async def purge_bootstrap_data() -> dict:
    """Purge all bootstrap/synthetic records from memory.

    Used to clear poisoned training data.  After purging, the model
    will be untrained and will re-bootstrap with clean data.
    """
    frank = _get_frank()
    purge_result = frank.memory.purge_bootstrap_data()
    return {
        "status": "purged",
        **purge_result,
        "next_step": "Model will re-bootstrap and retrain on next scan cycle",
    }


@router.get("/debug/rejections")
async def debug_rejections() -> dict:
    """Debug: show why trades are being rejected."""
    frank = _get_frank()
    from app.pipeline import market_cache
    from app.ai.features import MarketFeatures

    markets = market_cache.get_active()
    candidates = frank._filter_candidates(markets)

    if not candidates:
        return {"error": "no_candidates", "total_active": len(markets)}

    # Try one candidate
    m = candidates[0]
    features = frank._features.compute(m)
    predictions = frank._model.predict_batch([features])
    pred = predictions[0] if predictions else None

    if pred is None:
        return {"error": "no_prediction", "ticker": m.ticker}

    params = frank.strategy.params
    kelly = frank._kelly_size(pred, features, params)
    count = max(1, int(kelly * params.max_position_size))
    price_cents = frank._compute_price(pred, features)

    # Check portfolio risk
    passed, reject_reason = frank._adv_risk.portfolio_check(
        ticker=m.ticker,
        count=count,
        price_cents=price_cents,
        event_ticker=getattr(m, "event_ticker", ""),
        category=getattr(m, "category", ""),
    )

    # Check execution risk (without actually executing)
    risk_ok, risk_reason = None, None
    if frank._execution._risk_manager:
        from app.kalshi.models import OrderSide, OrderAction
        side = OrderSide.YES if pred.side == "yes" else OrderSide.NO
        import asyncio
        risk_ok, risk_reason = await frank._execution._risk_manager.pre_trade_check(
            ticker=m.ticker, side=side, action=OrderAction.BUY,
            count=count, price_cents=price_cents,
        )

    return {
        "ticker": m.ticker,
        "title": m.title,
        "prediction": {"side": pred.side, "confidence": pred.confidence, "edge": pred.edge, "prob": pred.predicted_prob},
        "features": {"midpoint": features.midpoint, "spread": features.spread, "volume": features.volume},
        "sizing": {"kelly": kelly, "count": count, "price_cents": price_cents},
        "params": {"min_confidence": params.min_confidence, "min_edge": params.min_edge},
        "portfolio_check": {"passed": passed, "reason": reject_reason},
        "execution_risk": {"passed": risk_ok, "reason": risk_reason},
        "total_candidates": len(candidates),
        "total_active": len(markets),
    }


@router.post("/debug/test-trade")
async def debug_test_trade() -> dict:
    """Debug: actually try to execute one trade and return full result."""
    frank = _get_frank()
    from app.pipeline import market_cache
    from app.kalshi.models import OrderSide, OrderAction, OrderType

    markets = market_cache.get_active()
    candidates = frank._filter_candidates(markets)

    if not candidates:
        return {"error": "no_candidates"}

    m = candidates[0]
    features = frank._features.compute(m)
    predictions = frank._model.predict_batch([features])
    pred = predictions[0] if predictions else None
    if pred is None:
        return {"error": "no_prediction"}

    params = frank.strategy.params
    kelly = frank._kelly_size(pred, features, params)
    count = max(1, int(kelly * params.max_position_size))
    price_cents = frank._compute_price(pred, features)

    try:
        result = await frank._execute_trade(
            market=m,
            prediction=pred,
            features=features,
            count=count,
            price_cents=price_cents,
        )
        if result is None:
            return {"error": "execute_returned_none", "ticker": m.ticker}
        return {
            "ticker": m.ticker,
            "success": result.success,
            "order_id": result.order_id,
            "error": result.error,
            "risk_check_passed": result.risk_check_passed,
            "risk_rejection_reason": result.risk_rejection_reason,
            "latency_ms": result.latency_ms,
            "count": count,
            "price_cents": price_cents,
            "side": pred.side,
        }
    except Exception as e:
        return {"error": str(e), "type": type(e).__name__, "ticker": m.ticker}


@router.get("/learner")
async def learner_status() -> dict:
    """Get the online learner's status."""
    frank = _get_frank()
    return frank.learner.stats()


@router.get("/features")
async def feature_importance() -> dict:
    """Get current feature importance rankings."""
    frank = _get_frank()
    return {
        "current": frank.learner.get_feature_importance(),
        "trends": frank.learner.get_importance_trends(),
    }


# ── Performance ───────────────────────────────────────────────────────────────

@router.get("/performance")
async def performance_summary() -> dict:
    """Full performance breakdown."""
    frank = _get_frank()
    return frank.performance.summary()


@router.get("/performance/snapshot")
async def performance_snapshot() -> dict:
    """Compute and return a fresh performance snapshot."""
    frank = _get_frank()
    snap = frank.performance.compute_snapshot()
    return snap.to_dict()


@router.get("/performance/categories")
async def performance_by_category() -> dict:
    """Performance broken down by market category."""
    frank = _get_frank()
    return frank.performance.performance_by_category()


# ── Memory ────────────────────────────────────────────────────────────────────

@router.get("/memory")
async def memory_stats() -> dict:
    """Get trade memory statistics."""
    frank = _get_frank()
    return frank.memory.stats()


@router.get("/memory/recent")
async def recent_trades(n: int = 20, ticker: str | None = None) -> list[dict]:
    """Get most recent trades from memory."""
    frank = _get_frank()
    trades = frank.memory.get_recent_trades(n=n, ticker=ticker)
    return [t.to_dict() for t in trades]


@router.get("/memory/pending")
async def pending_trades() -> list[dict]:
    """Get all pending (unresolved) trades."""
    frank = _get_frank()
    trades = frank.memory.get_pending_trades()
    return [t.to_dict() for t in trades]


@router.get("/analytics")
async def analytics() -> dict:
    """Comprehensive PnL analytics, category breakdown, and performance metrics."""
    frank = _get_frank()
    from app.frankenstein.categories import detect_category
    import time as _time

    all_trades = frank.memory.get_recent_trades(n=10000)

    # Overall stats
    resolved = [t for t in all_trades if t.outcome.value != "pending" and t.action == "buy"]
    pending = [t for t in all_trades if t.outcome.value == "pending" and t.action == "buy"]
    wins = [t for t in resolved if t.outcome.value == "win"]
    losses = [t for t in resolved if t.outcome.value == "loss"]

    total_pnl_cents = sum(t.pnl_cents for t in resolved)
    total_cost_cents = sum(t.total_cost_cents for t in resolved) or 1
    win_rate = len(wins) / len(resolved) if resolved else 0
    avg_win = sum(t.pnl_cents for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t.pnl_cents for t in losses) / len(losses) if losses else 0
    profit_factor = abs(sum(t.pnl_cents for t in wins)) / abs(sum(t.pnl_cents for t in losses)) if losses and sum(t.pnl_cents for t in losses) != 0 else 0

    # Category breakdown
    cat_stats: dict[str, dict] = {}
    for t in resolved:
        cat = detect_category(t.market_title or "", t.category or "", ticker=t.ticker)
        if cat not in cat_stats:
            cat_stats[cat] = {"trades": 0, "wins": 0, "losses": 0, "pnl_cents": 0, "cost_cents": 0}
        cat_stats[cat]["trades"] += 1
        cat_stats[cat]["pnl_cents"] += t.pnl_cents
        cat_stats[cat]["cost_cents"] += t.total_cost_cents
        if t.outcome.value == "win":
            cat_stats[cat]["wins"] += 1
        elif t.outcome.value == "loss":
            cat_stats[cat]["losses"] += 1
    for cat, s in cat_stats.items():
        s["win_rate"] = s["wins"] / s["trades"] if s["trades"] > 0 else 0
        s["pnl_dollars"] = round(s["pnl_cents"] / 100, 2)
        s["roi_pct"] = round(s["pnl_cents"] / s["cost_cents"] * 100, 1) if s["cost_cents"] > 0 else 0

    # Confidence band performance
    conf_bands: dict[str, dict] = {}
    for t in resolved:
        if t.confidence >= 0.8:
            band = "0.80-1.00"
        elif t.confidence >= 0.7:
            band = "0.70-0.80"
        elif t.confidence >= 0.6:
            band = "0.60-0.70"
        elif t.confidence >= 0.5:
            band = "0.50-0.60"
        else:
            band = "0.00-0.50"
        if band not in conf_bands:
            conf_bands[band] = {"trades": 0, "wins": 0, "pnl_cents": 0}
        conf_bands[band]["trades"] += 1
        conf_bands[band]["pnl_cents"] += t.pnl_cents
        if t.outcome.value == "win":
            conf_bands[band]["wins"] += 1
    for band, s in conf_bands.items():
        s["win_rate"] = s["wins"] / s["trades"] if s["trades"] > 0 else 0
        s["pnl_dollars"] = round(s["pnl_cents"] / 100, 2)

    # Recent PnL curve (last 50 resolved trades)
    pnl_curve = []
    running_pnl = 0
    for t in sorted(resolved, key=lambda x: x.timestamp):
        running_pnl += t.pnl_cents
        pnl_curve.append({
            "timestamp": t.timestamp,
            "pnl_cents": running_pnl,
            "pnl_dollars": round(running_pnl / 100, 2),
        })

    return {
        "overview": {
            "total_trades": len(resolved),
            "pending_trades": len(pending),
            "win_rate": round(win_rate, 3),
            "total_pnl_cents": total_pnl_cents,
            "total_pnl_dollars": round(total_pnl_cents / 100, 2),
            "avg_win_cents": round(avg_win, 1),
            "avg_loss_cents": round(avg_loss, 1),
            "profit_factor": round(profit_factor, 2),
            "roi_pct": round(total_pnl_cents / total_cost_cents * 100, 1),
            "total_cost_dollars": round(total_cost_cents / 100, 2),
        },
        "by_category": cat_stats,
        "by_confidence": conf_bands,
        "pnl_curve": pnl_curve[-200:],  # last 200 points
        "category_distribution": frank.categories.stats().get("category_distribution", {}),
        "model_version": frank.learner.current_version,
        "generation": frank.learner.generation,
    }


# ── Strategy ──────────────────────────────────────────────────────────────────

@router.get("/strategy")
async def strategy_status() -> dict:
    """Get adaptive strategy status and current parameters."""
    frank = _get_frank()
    return frank.strategy.stats()


@router.post("/strategy/reset")
async def reset_strategy() -> dict:
    """Reset strategy parameters to conservative defaults."""
    frank = _get_frank()
    frank.strategy.reset_to_defaults()
    return {"status": "reset", "params": frank.strategy.params.to_dict()}


# ── Scheduler ─────────────────────────────────────────────────────────────────

@router.get("/scheduler")
async def scheduler_status() -> dict:
    """Get background scheduler status."""
    frank = _get_frank()
    return frank.scheduler.stats()


# ── Chat ──────────────────────────────────────────────────────────────────────

def _get_chat():
    """Get or create the Frankenstein chat engine."""
    frank = _get_frank()
    if not hasattr(frank, '_chat') or frank._chat is None:
        from app.frankenstein.chat import FrankensteinChat
        frank._chat = FrankensteinChat(brain=frank)
    return frank._chat


@router.get("/chat/welcome")
async def chat_welcome() -> dict:
    """Get Frankenstein's welcome message when chat opens."""
    chat = _get_chat()
    msg = chat.get_welcome()
    return msg.to_dict()


@router.post("/chat")
async def chat_message(body: dict) -> dict:
    """Send a message to Frankenstein and get a response."""
    message = body.get("message", "").strip()
    if not message:
        raise HTTPException(400, "Message cannot be empty")

    chat = _get_chat()

    # Handle slash commands
    if message.startswith("/"):
        return await _handle_command(message, chat)

    response = chat.chat(message)
    return response.to_dict()


@router.get("/chat/history")
async def chat_history(n: int = 50) -> list[dict]:
    """Get recent chat history."""
    chat = _get_chat()
    return chat.get_history(n=n)


async def _handle_command(command: str, chat) -> dict:
    """Handle slash commands in chat."""
    from app.frankenstein.chat import ChatMessage

    cmd = command.lower().strip()
    frank = chat.brain

    if cmd == "/status":
        resp = chat.chat("What's your current status?")
        return resp.to_dict()

    elif cmd == "/awaken":
        if frank._state.is_alive:
            msg = ChatMessage(
                role="frankenstein",
                content="🧟⚡ I'm already awake! Ask me anything.",
                data={"type": "command", "command": "awaken"},
            )
        else:
            await frank.awaken()
            msg = ChatMessage(
                role="frankenstein",
                content=(
                    "🧟⚡ **FRANKENSTEIN IS ALIVE!**\n\n"
                    "All systems online. Background tasks started:\n"
                    "- 🔍 Market scanning\n"
                    "- 🧬 Hourly retraining\n"
                    "- 📊 Performance tracking\n"
                    "- 🎛️ Strategy adaptation\n"
                    "- 💾 Auto-save\n"
                    "- ❤️ Health monitoring\n\n"
                    "I'm ready to trade. What would you like to know?"
                ),
                data={"type": "command", "command": "awaken"},
            )
        chat.session.add(msg)
        return msg.to_dict()

    elif cmd == "/sleep":
        await frank.sleep()
        msg = ChatMessage(
            role="frankenstein",
            content="🧟💤 Going to sleep... Memory saved. Goodnight.",
            data={"type": "command", "command": "sleep"},
        )
        chat.session.add(msg)
        return msg.to_dict()

    elif cmd == "/retrain":
        result = await frank.force_retrain()
        if result.get("success"):
            msg = ChatMessage(
                role="frankenstein",
                content=(
                    f"🧬 **Model Retrained!**\n\n"
                    f"- New version: `{result['version']}`\n"
                    f"- Generation: {result['generation']}\n"
                    f"- Validation AUC: {result['auc']:.4f}\n\n"
                    f"The new model has been promoted. Let's see if it trades better."
                ),
                data={"type": "command", "command": "retrain", "result": result},
            )
        else:
            msg = ChatMessage(
                role="frankenstein",
                content=(
                    f"🧬 Retrain attempted but no promotion — "
                    f"{result.get('reason', 'unknown reason')}.\n"
                    f"Need more trade data or the challenger didn't beat the champion."
                ),
                data={"type": "command", "command": "retrain", "result": result},
            )
        chat.session.add(msg)
        return msg.to_dict()

    else:
        # Unknown command — treat as regular message
        resp = chat.chat(command)
        return resp.to_dict()


# ── Simulation Reset & Settings ───────────────────────────────────────────────

@router.post("/simulation/reset")
async def reset_simulation(body: dict = {}) -> dict:
    """
    Reset the paper trading simulation.

    Optional body:
    - balance_cents: new starting balance in cents (default: 1_000_000 = $10,000)
    - clear_memory: also clear Frankenstein's trade memory (default: true)
    - restart_brain: sleep & re-awaken Frankenstein (default: true)
    """
    frank = _get_frank()
    sim = state.paper_simulator
    if sim is None:
        raise HTTPException(400, "Paper trading not enabled")

    balance_cents = body.get("balance_cents", None)
    clear_memory = body.get("clear_memory", True)
    restart_brain = body.get("restart_brain", True)

    # 1. Stop Frankenstein if running
    was_alive = frank._state.is_alive
    if was_alive and restart_brain:
        await frank.sleep()

    # 2. Reset paper simulator
    reset_result = sim.reset(new_balance_cents=balance_cents)

    # 3. Clear trade memory if requested
    memory_cleared = False
    if clear_memory:
        frank.memory._trades.clear()
        frank.memory._pending_trades.clear()
        frank.memory._important_trades.clear()
        frank.memory._snapshots.clear()
        frank.memory._by_ticker.clear()
        frank.memory._by_outcome.clear()
        frank.memory._total_resolved = 0
        memory_cleared = True
        log.info("trade_memory_cleared")

    # 4. Reset performance tracker
    frank.performance = __import__(
        "app.frankenstein.performance", fromlist=["PerformanceTracker"]
    ).PerformanceTracker(memory=frank.memory)

    # 5. Reset brain state counters
    frank._state.total_scans = 0
    frank._state.total_signals = 0
    frank._state.total_trades_executed = 0
    frank._state.total_trades_rejected = 0
    frank._state.last_scan_debug = {}

    # 6. Re-awaken if it was alive
    if was_alive and restart_brain:
        await frank.awaken()

    log.info(
        "simulation_reset_complete",
        new_balance=reset_result["new_balance"],
        memory_cleared=memory_cleared,
        restarted=was_alive and restart_brain,
    )

    return {
        "status": "ok",
        "message": "Simulation reset complete",
        **reset_result,
        "memory_cleared": memory_cleared,
        "brain_restarted": was_alive and restart_brain,
    }


@router.get("/settings")
async def get_settings() -> dict:
    """Get current Frankenstein + trading settings."""
    frank = _get_frank()
    sim = state.paper_simulator
    params = frank.strategy.params

    return {
        "paper_trading": {
            "enabled": sim is not None,
            "balance_cents": sim.balance_cents if sim else 0,
            "starting_balance_cents": sim.starting_balance_cents if sim else 0,
            "pnl_cents": sim.pnl_cents if sim else 0,
            "fee_rate_cents": sim.fee_rate_cents if sim else 7,
            "slippage_cents": sim.slippage_cents if sim else 1,
        },
        "strategy": {
            "min_confidence": params.min_confidence,
            "min_edge": params.min_edge,
            "kelly_fraction": params.kelly_fraction,
            "max_position_size": params.max_position_size,
            "max_simultaneous_positions": params.max_simultaneous_positions,
            "scan_interval": params.scan_interval,
            "max_daily_loss": params.max_daily_loss,
            "stop_loss_pct": params.stop_loss_pct,
            "take_profit_pct": params.take_profit_pct,
            "max_spread_cents": params.max_spread_cents,
            "aggression": params.aggression,
        },
        "brain": {
            "scan_interval": frank.config.scan_interval,
            "retrain_interval": frank.config.retrain_interval,
            "min_train_samples": frank.config.min_train_samples,
            "sports_only": frank._sports_only,
            "model_version": frank._state.model_version,
            "generation": frank._state.generation,
        },
    }


@router.put("/settings")
async def update_settings(body: dict) -> dict:
    """
    Update Frankenstein strategy/trading settings live.

    Accepts partial updates. Supported keys:
    - strategy.min_confidence, strategy.min_edge, strategy.kelly_fraction, etc.
    - brain.scan_interval, brain.sports_only
    - paper.fee_rate_cents, paper.slippage_cents
    """
    frank = _get_frank()
    sim = state.paper_simulator
    params = frank.strategy.params
    updated = []

    # Strategy updates
    strat = body.get("strategy", {})
    if "min_confidence" in strat:
        params.min_confidence = max(0.50, min(0.95, float(strat["min_confidence"])))
        updated.append("min_confidence")
    if "min_edge" in strat:
        params.min_edge = max(0.01, min(0.20, float(strat["min_edge"])))
        updated.append("min_edge")
    if "kelly_fraction" in strat:
        params.kelly_fraction = max(0.05, min(0.50, float(strat["kelly_fraction"])))
        updated.append("kelly_fraction")
    if "max_position_size" in strat:
        params.max_position_size = max(1, min(50, int(strat["max_position_size"])))
        updated.append("max_position_size")
    if "max_simultaneous_positions" in strat:
        params.max_simultaneous_positions = max(1, min(100, int(strat["max_simultaneous_positions"])))
        updated.append("max_simultaneous_positions")
    if "scan_interval" in strat:
        params.scan_interval = max(10, min(300, float(strat["scan_interval"])))
        updated.append("scan_interval")
    if "max_daily_loss" in strat:
        params.max_daily_loss = max(10, min(500, float(strat["max_daily_loss"])))
        updated.append("max_daily_loss")
    if "stop_loss_pct" in strat:
        params.stop_loss_pct = max(0.05, min(0.50, float(strat["stop_loss_pct"])))
        updated.append("stop_loss_pct")
    if "take_profit_pct" in strat:
        params.take_profit_pct = max(0.10, min(1.00, float(strat["take_profit_pct"])))
        updated.append("take_profit_pct")
    if "max_spread_cents" in strat:
        params.max_spread_cents = max(5, min(100, int(strat["max_spread_cents"])))
        updated.append("max_spread_cents")
    if "aggression" in strat:
        params.aggression = max(0.1, min(1.0, float(strat["aggression"])))
        updated.append("aggression")

    # Brain updates
    brain = body.get("brain", {})
    if "scan_interval" in brain:
        frank.config.scan_interval = max(10, min(300, float(brain["scan_interval"])))
        updated.append("brain.scan_interval")
    if "sports_only" in brain:
        frank._sports_only = bool(brain["sports_only"])
        updated.append("brain.sports_only")

    # Paper trading updates
    paper = body.get("paper", {})
    if sim:
        if "fee_rate_cents" in paper:
            sim.fee_rate_cents = max(0, min(20, int(paper["fee_rate_cents"])))
            updated.append("paper.fee_rate_cents")
        if "slippage_cents" in paper:
            sim.slippage_cents = max(0, min(10, int(paper["slippage_cents"])))
            updated.append("paper.slippage_cents")

    log.info("settings_updated", fields=updated)

    return {
        "status": "ok",
        "updated": updated,
        "message": f"Updated {len(updated)} settings",
    }


# ── Decision Engine ───────────────────────────────────────────────────────────

@router.get("/decision-engine")
async def decision_engine() -> dict:
    """Return the full decision pipeline explanation and confidence factor docs."""
    return explain_decision_logic()


# ── Model Intelligence ────────────────────────────────────────────────────────

@router.get("/model/calibration")
async def model_calibration() -> dict:
    """Get model calibration health: predicted vs actual outcome tracking."""
    frank = _get_frank()
    model = frank._model
    if not hasattr(model, "calibration"):
        return {"available": False, "reason": "Model has no calibration tracker"}
    return {
        "available": True,
        **model.calibration.summary(),
    }


@router.get("/model/intelligence")
async def model_intelligence() -> dict:
    """
    Comprehensive view of the model's intelligence metrics:
    - Training status and version
    - Calibration health
    - Tree ensemble stats
    - Uncertainty estimation capability
    """
    frank = _get_frank()
    model = frank._model

    result: dict = {
        "model_name": model.name if hasattr(model, "name") else "unknown",
        "model_version": model.version if hasattr(model, "version") else "unknown",
        "is_trained": model.is_trained if hasattr(model, "is_trained") else False,
        "generation": frank._state.generation,
    }

    # Tree ensemble info
    if hasattr(model, "_model") and model._model is not None:
        try:
            n_trees = model._model.num_boosted_rounds()
            result["ensemble"] = {
                "num_trees": n_trees,
                "uncertainty_estimation": n_trees > 1,
                "checkpoint_sampling": min(10, n_trees),
            }
        except Exception:
            result["ensemble"] = {"num_trees": 0, "uncertainty_estimation": False}
    else:
        result["ensemble"] = {"num_trees": 0, "uncertainty_estimation": False}

    # Calibration info
    if hasattr(model, "calibration"):
        result["calibration"] = model.calibration.summary()
    else:
        result["calibration"] = {"available": False}

    # Feature info
    if hasattr(model, "_feature_names"):
        result["features"] = {
            "count": len(model._feature_names),
            "names": model._feature_names[:10],  # first 10
        }

    return result


# ── Scan Diagnostics ──────────────────────────────────────────────────────────

@router.get("/debug-scan")
async def debug_scan() -> dict:
    """Diagnostic: step through scan funnel and report where it stops."""
    import traceback as tb
    from app.pipeline import market_cache

    result: dict = {"code_version": "6b148fd", "steps": []}

    # Step 1: Cache
    try:
        active = market_cache.get_active()
        result["steps"].append({"step": "cache", "active_count": len(active)})
    except Exception as e:
        result["steps"].append({"step": "cache", "error": str(e)})
        return result

    if not active:
        result["exit"] = "no_active_markets"
        return result

    # Step 2: Filter
    try:
        frank = _get_frank()
        candidates = frank._filter_candidates(active)
        result["steps"].append({"step": "filter", "candidates": len(candidates)})
    except Exception as e:
        result["steps"].append({"step": "filter", "error": str(e), "tb": tb.format_exc()[-500:]})
        return result

    if not candidates:
        result["exit"] = "no_candidates"
        # Spread analysis inline
        params = frank.strategy.params
        max_sp = params.max_spread_cents
        if frank._execution._risk_manager:
            max_sp = min(max_sp, frank._execution._risk_manager.limits.max_spread_cents)
        n_none = sum(1 for m in active[:500] if m.spread is None)
        n_ok = sum(1 for m in active[:500] if m.spread is not None and int(float(m.spread) * 100) <= max_sp)
        result["spread_info"] = {"max_spread": max_sp, "none_count": n_none, "within_limit": n_ok, "sampled": min(500, len(active))}
        return result

    # Step 3: Features
    try:
        feat = frank._features.compute(candidates[0])
        result["steps"].append({"step": "features", "ok": True, "midpoint": float(feat.midpoint), "spread": float(feat.spread)})
    except Exception as e:
        result["steps"].append({"step": "features", "error": str(e), "tb": tb.format_exc()[-500:]})
        return result

    # Step 4: Predict
    try:
        pred = frank._model.predict(feat)
        result["steps"].append({
            "step": "predict", "ok": True,
            "prob": round(float(pred.predicted_prob), 4),
            "edge": round(float(pred.edge), 4),
            "side": str(pred.side),
            "trained": bool(frank._model.is_trained),
        })
    except Exception as e:
        result["steps"].append({"step": "predict", "error": str(e), "tb": tb.format_exc()[-500:]})
        return result

    result["exit"] = "full_pipeline_ok"
    result["candidates_count"] = len(candidates)
    return result


def _analyze_spreads(markets, max_spread: int) -> dict:
    """Analyze spread distribution for debugging."""
    no_spread = 0
    within_limit = 0
    above_limit = 0
    for m in markets:
        if m.spread is None:
            no_spread += 1
            continue
        spread_cents = int(m.spread * 100) if isinstance(m.spread, float) else m.spread
        if spread_cents <= max_spread:
            within_limit += 1
        else:
            above_limit += 1
    return {
        "no_spread": no_spread,
        "within_limit": within_limit,
        "above_limit": above_limit,
        "max_spread_cents": max_spread,
    }


# ── Phase 3+20: Performance report endpoint ──────────────────────
@router.get("/frankenstein/performance")
async def frankenstein_performance():
    """Comprehensive performance report for profitability tracking."""
    from app.state import state
    if not state.frankenstein:
        return {"error": "Frankenstein not initialized"}
    try:
        report = state.frankenstein.get_performance_report()
        return {"status": "ok", "report": report}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── Phase 19: Agent status endpoint ──────────────────────────────
@router.get("/agents")
async def frankenstein_agents():
    """Status of all trading agents."""
    from app.state import state
    if not state.frankenstein:
        return {"error": "Frankenstein not initialized"}
    try:
        orch = getattr(state.frankenstein, '_orchestrator', None)
        if not orch:
            return {"error": "No orchestrator"}
        return {"status": "ok", **orch.status()}
    except Exception as e:
        return {"status": "error", "error": str(e)}
