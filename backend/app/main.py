"""
JA Hedge — FastAPI Application Entry Point.

Main app with lifespan management for startup/shutdown of:
- Database connections
- Redis connections
- Kalshi WebSocket feeds
- Trading engine
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import init_db, close_db
from app.logging_config import setup_logging, get_logger
from app.state import state, reset_state

settings = get_settings()
setup_logging(log_level=settings.log_level, log_format=settings.log_format)
log = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan — startup and shutdown."""

    log.info(
        "starting_jahedge",
        mode=settings.jahedge_mode.value,
        rest_url=settings.kalshi_rest_url,
        has_api_keys=settings.has_api_keys,
    )

    # ── Startup ───────────────────────────────────────────
    try:
        await init_db()
    except Exception as e:
        log.warning("db_init_skipped", error=str(e), hint="Database not available — running without persistence")

    # Kalshi API client
    from app.kalshi.api import KalshiAPI

    kalshi = KalshiAPI.from_settings(settings)
    await kalshi.__aenter__()  # open httpx connection pool
    state.kalshi_api = kalshi

    # Risk manager
    from decimal import Decimal
    from app.engine.risk import RiskManager, RiskLimits

    risk_limits = RiskLimits(
        max_position_size=settings.risk_max_position_size,
        max_daily_loss=Decimal(str(settings.risk_max_daily_loss)),
        max_portfolio_exposure=Decimal(str(settings.risk_max_portfolio_exposure)),
    )
    risk_mgr = RiskManager(limits=risk_limits)
    state.risk_manager = risk_mgr

    # Paper trading wrapper (fake money mode)
    from app.engine.paper_trader import PaperTradingSimulator

    api_for_engine = kalshi  # default: real API
    if settings.paper_trading:
        simulator = PaperTradingSimulator(
            starting_balance_cents=settings.paper_trading_balance,
        )
        api_for_engine = simulator.wrap_api(kalshi)
        state.paper_simulator = simulator
        log.info(
            "paper_trading_enabled",
            balance=f"${settings.paper_trading_balance / 100:.2f}",
        )

    # Execution engine
    from app.engine.execution import ExecutionEngine

    exec_engine = ExecutionEngine(api=api_for_engine, risk_manager=risk_mgr)
    state.execution_engine = exec_engine

    # AI components
    from app.ai.features import FeatureEngine
    from app.ai.models import XGBoostPredictor
    from app.ai.strategy import TradingStrategy
    from app.ai.agent import AutonomousAgent
    from app.frankenstein import Frankenstein
    from app.frankenstein.brain import FrankensteinConfig

    feat_engine = FeatureEngine()
    model = XGBoostPredictor()
    strategy = TradingStrategy(
        model=model,
        feature_engine=feat_engine,
        execution_engine=exec_engine,
        risk_manager=risk_mgr,
        min_confidence=settings.strategy_min_confidence,
        min_edge=settings.strategy_min_edge,
        kelly_fraction=settings.strategy_kelly_fraction,
        scan_interval=settings.strategy_scan_interval,
    )
    state.feature_engine = feat_engine
    state.prediction_model = model
    state.trading_strategy = strategy

    # Autonomous AI Trading Agent (legacy — kept for backwards compatibility)
    agent = AutonomousAgent(
        model=model,
        feature_engine=feat_engine,
        execution_engine=exec_engine,
        risk_manager=risk_mgr,
    )
    state.autonomous_agent = agent

    # 🧟 FRANKENSTEIN — The unified AI brain
    frank_config = FrankensteinConfig(
        scan_interval=settings.strategy_scan_interval,
        retrain_interval=3600.0,  # Retrain every hour
        min_train_samples=50,
        retrain_threshold=25,
        memory_persist_path="data/frankenstein_memory.json",
        checkpoint_dir="data/models",
    )
    frankenstein = Frankenstein(
        model=model,
        feature_engine=feat_engine,
        execution_engine=exec_engine,
        risk_manager=risk_mgr,
        config=frank_config,
    )
    state.frankenstein = frankenstein
    log.info("🧟 frankenstein_created", generation=0)

    # Market data pipeline (with feature engine callback)
    from app.pipeline import MarketDataPipeline

    def _feed_features(markets):
        """Callback: feed every refreshed market into FeatureEngine."""
        for m in markets:
            mid = float(m.midpoint or m.last_price or 0)
            vol = float(m.volume or 0)
            oi = float(m.open_interest or 0)
            if mid > 0:
                feat_engine.update(m.ticker, mid, vol, oi)

    pipeline = MarketDataPipeline(api=kalshi, on_refresh_callback=_feed_features)
    state.market_pipeline = pipeline

    # Portfolio tracker (uses paper wrapper if paper trading)
    from app.pipeline.portfolio_tracker import PortfolioTracker

    tracker = PortfolioTracker(api=api_for_engine)
    state.portfolio_tracker = tracker

    # ── Start live data feeds ─────────────────────────────
    try:
        await pipeline.start()
        log.info("market_pipeline_started")
    except Exception as e:
        log.error("market_pipeline_start_failed", error=str(e))

    try:
        await tracker.start()
        log.info("portfolio_tracker_started")
    except Exception as e:
        log.error("portfolio_tracker_start_failed", error=str(e))

    # Feed FeatureEngine with initial market data so technical indicators populate
    from app.pipeline import market_cache as _mc
    for _m in _mc.get_active():
        _mid = float(_m.midpoint or _m.last_price or 0)
        _vol = float(_m.volume or 0)
        _oi = float(_m.open_interest or 0)
        if _mid > 0:
            feat_engine.update(_m.ticker, _mid, _vol, _oi)
    log.info("feature_engine_seeded", markets=len(_mc.get_active()))

    # ── Auto-awaken Frankenstein (AI brain) ───────────────
    try:
        await frankenstein.awaken()
        log.info("🧟⚡ frankenstein_auto_awakened")
    except Exception as e:
        log.error("frankenstein_awaken_failed", error=str(e))

    state.ready = True
    log.info("jahedge_ready", port=settings.backend_port)

    yield

    # ── Shutdown ──────────────────────────────────────────
    log.info("shutting_down")

    # Stop Frankenstein first (saves memory)
    if state.frankenstein:
        try:
            await state.frankenstein.sleep()
        except Exception:
            pass

    # Stop market data pipeline
    if state.market_pipeline:
        try:
            await state.market_pipeline.stop()
        except Exception:
            pass

    # Stop portfolio tracker
    if state.portfolio_tracker:
        try:
            await state.portfolio_tracker.stop()
        except Exception:
            pass

    # Stop strategy
    if state.trading_strategy:
        try:
            await state.trading_strategy.stop()
        except Exception:
            pass

    # Stop autonomous agent
    if state.autonomous_agent:
        try:
            await state.autonomous_agent.stop()
        except Exception:
            pass

    # Close Kalshi client
    if state.kalshi_api:
        try:
            await state.kalshi_api.__aexit__(None, None, None)
        except Exception:
            pass

    await close_db()
    reset_state()

    log.info("shutdown_complete")


app = FastAPI(
    title="JA Hedge",
    description="AI-Powered Kalshi Trading Platform",
    version="0.1.0",
    lifespan=lifespan,
)

# ── Error Handlers ────────────────────────────────────────────────────────────
from app.error_handlers import register_exception_handlers  # noqa: E402
register_exception_handlers(app)

# ── Middleware ────────────────────────────────────────────────────────────────
from app.middleware import RequestTrackingMiddleware  # noqa: E402
app.add_middleware(RequestTrackingMiddleware)

# ── CORS ──────────────────────────────────────────────────────────────────────
import os as _os
_cors_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
# Allow Railway frontend domain(s) via env var
_extra = _os.environ.get("CORS_ORIGINS", "")
if _extra:
    _cors_origins.extend([o.strip() for o in _extra.split(",") if o.strip()])

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── API Routes ────────────────────────────────────────────────────────────────
from app.routes import api_router  # noqa: E402
app.include_router(api_router)


# ── Health Check ──────────────────────────────────────────────────────────────
@app.get("/health")
async def health_check() -> dict:
    from app.state import state as app_state

    paper_info = None
    if app_state.paper_simulator:
        sim = app_state.paper_simulator
        paper_info = {
            "enabled": True,
            "balance": sim.balance_dollars,
            "starting_balance": f"{sim.starting_balance_cents / 100:.2f}",
            "pnl": sim.pnl_dollars,
            "total_trades": sim.total_fills,
        }

    return {
        "status": "ok" if app_state.ready else "starting",
        "mode": settings.jahedge_mode.value,
        "has_api_keys": settings.has_api_keys,
        "version": "0.2.0",
        "paper_trading": paper_info or {"enabled": False},
        "components": {
            "database": "connected",
            "kalshi_api": "ready" if app_state.kalshi_api else "not_initialized",
            "execution_engine": "ready" if app_state.execution_engine else "not_initialized",
            "risk_manager": "ready" if app_state.risk_manager else "not_initialized",
            "ai_strategy": "ready" if app_state.trading_strategy else "not_initialized",
            "frankenstein": "alive" if (app_state.frankenstein and app_state.frankenstein._state.is_alive) else "sleeping",
        },
    }


@app.get("/health/auth")
async def auth_test() -> dict:
    """Test if Kalshi API authentication works (GET balance + GET positions)."""
    from app.state import state as app_state
    import os
    from pathlib import Path
    results: dict = {
        "api_initialized": bool(app_state.kalshi_api),
        "key_id_set": bool(settings.kalshi_api_key_id),
        "key_id_prefix": settings.kalshi_api_key_id[:8] + "..." if settings.kalshi_api_key_id else "EMPTY",
        "key_path": str(settings.resolved_key_path),
        "key_file_exists": settings.resolved_key_path.exists(),
        "key_file_size": settings.resolved_key_path.stat().st_size if settings.resolved_key_path.exists() else 0,
        "base64_env_set": bool(os.environ.get("KALSHI_PRIVATE_KEY_BASE64")),
    }
    if app_state.kalshi_api:
        try:
            bal = await app_state.kalshi_api.portfolio.get_balance()
            results["balance"] = {"ok": True, "balance_dollars": bal.balance_dollars}
        except Exception as e:
            results["balance"] = {"ok": False, "error": str(e), "type": type(e).__name__}
        try:
            pos = await app_state.kalshi_api.portfolio.get_all_positions()
            results["positions"] = {"ok": True, "count": len(pos)}
        except Exception as e:
            results["positions"] = {"ok": False, "error": str(e), "type": type(e).__name__}
    return results


@app.get("/")
async def root() -> dict:
    return {"name": "JA Hedge", "version": "0.2.0", "brain": "Frankenstein", "docs": "/docs"}
