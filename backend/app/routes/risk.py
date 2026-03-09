"""
JA Hedge — Risk Management API routes.

GET  /api/risk/snapshot        — Current risk snapshot
POST /api/risk/kill-switch     — Toggle kill switch
GET  /api/risk/events          — Recent risk events
PUT  /api/risk/limits          — Update risk limits
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.state import state

router = APIRouter(prefix="/risk", tags=["Risk"])


class RiskSnapshotResponse(BaseModel):
    total_exposure: float = 0
    daily_pnl: float = 0
    daily_trades: int = 0
    position_count: int = 0
    open_orders: int = 0
    kill_switch_active: bool = False


class RiskLimitsBody(BaseModel):
    max_position_size: int = 10
    max_daily_loss: float = 50.0
    max_portfolio_exposure: float = 500.0
    max_single_order_cost: float = 100.0
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    max_spread_cents: int = 20
    min_volume: int = 0


def _require_risk():
    if not state.risk_manager or not state.ready:
        raise HTTPException(503, detail="Risk manager not initialized")


@router.get("/snapshot", response_model=RiskSnapshotResponse)
async def risk_snapshot() -> RiskSnapshotResponse:
    """Get current risk state from the live RiskManager."""
    if not state.risk_manager:
        return RiskSnapshotResponse()

    snap = state.risk_manager.snapshot
    return RiskSnapshotResponse(
        total_exposure=float(snap.total_exposure),
        daily_pnl=float(snap.daily_pnl),
        daily_trades=snap.daily_trades,
        position_count=snap.position_count,
        open_orders=snap.open_orders,
        kill_switch_active=state.risk_manager.kill_switch_active,
    )


@router.post("/kill-switch")
async def toggle_kill_switch(activate: bool = True) -> dict:
    """Activate or deactivate the kill switch."""
    _require_risk()

    if activate:
        state.risk_manager.activate_kill_switch(reason="dashboard")
    else:
        state.risk_manager.deactivate_kill_switch()

    return {
        "kill_switch_active": state.risk_manager.kill_switch_active,
        "message": f"Kill switch {'activated' if activate else 'deactivated'}",
    }


@router.put("/limits")
async def update_limits(body: RiskLimitsBody) -> dict:
    """Update risk limits at runtime."""
    _require_risk()

    from app.engine.risk import RiskLimits

    new_limits = RiskLimits(
        max_position_size=body.max_position_size,
        max_daily_loss=Decimal(str(body.max_daily_loss)),
        max_portfolio_exposure=Decimal(str(body.max_portfolio_exposure)),
        max_single_order_cost=Decimal(str(body.max_single_order_cost)),
        stop_loss_pct=Decimal(str(body.stop_loss_pct)) if body.stop_loss_pct else None,
        take_profit_pct=Decimal(str(body.take_profit_pct)) if body.take_profit_pct else None,
        max_spread_cents=body.max_spread_cents,
        min_volume=body.min_volume,
    )
    state.risk_manager.update_limits(new_limits)

    return {"status": "accepted", "limits": body.model_dump()}
