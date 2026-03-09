"""
JA Hedge — Strategy API routes.

GET  /api/strategy/status    — AI strategy status and stats
POST /api/strategy/start     — Start AI trading
POST /api/strategy/stop      — Stop AI trading
PUT  /api/strategy/config    — Update strategy config
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.state import state

router = APIRouter(prefix="/strategy", tags=["Strategy"])


class StrategyStatusResponse(BaseModel):
    running: bool = False
    strategy_id: str = "default"
    model_name: str = "xgboost_v1"
    total_signals: int = 0
    signals_executed: int = 0
    signals_filtered: int = 0
    signals_risk_rejected: int = 0
    avg_confidence: float = 0
    avg_edge: float = 0


class StrategyConfigBody(BaseModel):
    min_confidence: float = 0.60
    min_edge: float = 0.05
    kelly_fraction: float = 0.25
    max_position_size: int = 10
    max_daily_loss: float = 50.0
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    allowed_categories: list[str] | None = None
    scan_interval: float = 30.0


def _require_strategy():
    if not state.trading_strategy or not state.ready:
        raise HTTPException(503, detail="Strategy engine not initialized")


@router.get("/status", response_model=StrategyStatusResponse)
async def strategy_status() -> StrategyStatusResponse:
    """Get current AI strategy status."""
    if not state.trading_strategy:
        return StrategyStatusResponse()

    strat = state.trading_strategy
    stats = strat.stats
    return StrategyStatusResponse(
        running=strat._running,
        strategy_id=strat.strategy_id,
        model_name=strat._model.name if hasattr(strat._model, "name") else "unknown",
        total_signals=stats.total_signals,
        signals_executed=stats.signals_executed,
        signals_filtered=stats.signals_filtered,
        signals_risk_rejected=stats.signals_risk_rejected,
        avg_confidence=stats.avg_confidence,
        avg_edge=stats.avg_edge,
    )


@router.post("/start")
async def start_strategy() -> dict:
    """Start the AI trading strategy."""
    _require_strategy()

    if state.trading_strategy._running:
        return {"status": "already_running"}

    await state.trading_strategy.start()
    return {"status": "started", "strategy_id": state.trading_strategy.strategy_id}


@router.post("/stop")
async def stop_strategy() -> dict:
    """Stop the AI trading strategy."""
    _require_strategy()

    if not state.trading_strategy._running:
        return {"status": "already_stopped"}

    await state.trading_strategy.stop()
    return {"status": "stopped"}


@router.put("/config")
async def update_config(body: StrategyConfigBody) -> dict:
    """Update strategy configuration at runtime."""
    if state.trading_strategy:
        strat = state.trading_strategy
        strat._min_confidence = body.min_confidence
        strat._min_edge = body.min_edge
        strat._kelly_fraction = body.kelly_fraction
        strat._max_positions = body.max_position_size
        strat._scan_interval = body.scan_interval

    return {"status": "accepted", "config": body.model_dump()}
