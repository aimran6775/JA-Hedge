"""
JA Hedge — Strategies API Routes.

Endpoints for the pre-built trading strategies engine:
  GET    /api/strategies/status     — All strategies + stats
  GET    /api/strategies/signals    — Recent strategy signals
  POST   /api/strategies/toggle     — Enable/disable a strategy
  POST   /api/strategies/config     — Update strategy config
  POST   /api/strategies/scan       — Trigger a manual scan
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.state import state
from app.logging_config import get_logger

log = get_logger("routes.strategies")

router = APIRouter(prefix="/strategies", tags=["Strategies"])


class ToggleBody(BaseModel):
    strategy: str
    enabled: bool


class ConfigBody(BaseModel):
    strategy: str
    min_confidence: float | None = None
    min_edge: float | None = None
    max_position_pct: float | None = None
    kelly_fraction: float | None = None
    max_positions: int | None = None


def _require_engine():
    if not state.strategy_engine:
        raise HTTPException(503, detail="Strategy engine not initialized")


@router.get("/status")
async def strategies_status() -> dict[str, Any]:
    """Full strategies engine status."""
    _require_engine()
    return state.strategy_engine.status()


@router.get("/signals")
async def strategies_signals(n: int = 50) -> dict[str, Any]:
    """Get recent signals from all strategies."""
    _require_engine()
    signals = state.strategy_engine.get_recent_signals(n)
    return {
        "total_signals": len(signals),
        "signals": signals,
    }


@router.post("/toggle")
async def toggle_strategy(body: ToggleBody) -> dict[str, Any]:
    """Enable or disable a strategy."""
    _require_engine()
    state.strategy_engine.toggle_strategy(body.strategy, body.enabled)
    return {
        "status": "ok",
        "strategy": body.strategy,
        "enabled": body.enabled,
    }


@router.post("/config")
async def update_strategy_config(body: ConfigBody) -> dict[str, Any]:
    """Update a strategy's configuration."""
    _require_engine()

    from app.strategies import StrategyConfig

    config = state.strategy_engine.configs.get(body.strategy)
    if not config:
        raise HTTPException(404, detail=f"Strategy '{body.strategy}' not found")

    if body.min_confidence is not None:
        config.min_confidence = body.min_confidence
    if body.min_edge is not None:
        config.min_edge = body.min_edge
    if body.max_position_pct is not None:
        config.max_position_pct = body.max_position_pct
    if body.kelly_fraction is not None:
        config.kelly_fraction = body.kelly_fraction
    if body.max_positions is not None:
        config.max_positions = body.max_positions

    state.strategy_engine.set_config(body.strategy, config)
    return {"status": "ok", "strategy": body.strategy, "config": config.to_dict()}


@router.post("/scan")
async def manual_scan() -> dict[str, Any]:
    """
    Trigger a manual strategy scan against active markets.

    Does NOT auto-execute — returns signals for review.
    """
    _require_engine()

    from app.pipeline import market_cache
    from app.pipeline.portfolio_tracker import portfolio_state

    markets = market_cache.get_active()
    if not markets:
        return {"signals": [], "markets_scanned": 0}

    feat_engine = state.feature_engine
    model = state.prediction_model
    if not feat_engine or not model:
        raise HTTPException(503, detail="AI components not initialized")

    # Build features + predictions for all active markets
    features_map = {}
    predictions_map = {}
    scanned = 0

    for m in markets[:500]:
        try:
            f = feat_engine.compute(m)
            p = model.predict(f)
            features_map[m.ticker] = f
            predictions_map[m.ticker] = p
            scanned += 1
        except Exception:
            continue

    # Run all strategies
    balance = portfolio_state.balance_cents or 1000000
    signals = state.strategy_engine.scan_all_markets(
        markets[:500], features_map, predictions_map, balance,
    )

    return {
        "markets_scanned": scanned,
        "total_signals": len(signals),
        "signals": [s.to_dict() for s in signals[:50]],
    }
