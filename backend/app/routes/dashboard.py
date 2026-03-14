"""
JA Hedge — Dashboard Aggregation API route.

GET  /api/dashboard  — Single endpoint returning all overview data
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.state import state
from app.pipeline.portfolio_tracker import portfolio_state
from app.pipeline import market_cache

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("")
async def dashboard_overview() -> dict[str, Any]:
    """
    Aggregated dashboard overview — one call for the Overview page.

    Returns balance, positions, risk, strategy, agent, frankenstein
    status in a single response to reduce frontend round-trips.
    """
    # ── Balance ───────────────────────────────────────────
    balance = {
        "balance_dollars": portfolio_state.balance_dollars,
        "balance_cents": portfolio_state.balance_cents,
        "total_exposure": float(portfolio_state.total_exposure),
        "position_count": portfolio_state.position_count,
        "open_orders": portfolio_state.open_order_count,
    }

    # ── Positions ─────────────────────────────────────────
    positions = []
    for ticker, pos in portfolio_state.positions.items():
        if pos.position and pos.position != 0:
            positions.append({
                "ticker": ticker,
                "position": pos.position,
                "market_exposure_dollars": pos.market_exposure_dollars,
                "realized_pnl_dollars": pos.realized_pnl_dollars,
            })

    # ── PnL ───────────────────────────────────────────────
    pnl = {
        "daily_pnl": float(portfolio_state.daily_pnl),
        "daily_trades": portfolio_state.daily_trades,
        "daily_fees": float(portfolio_state.daily_fees),
        "total_exposure": float(portfolio_state.total_exposure),
    }

    # ── Risk ──────────────────────────────────────────────
    risk = {"kill_switch_active": False, "total_exposure": 0, "daily_pnl": 0}
    if state.risk_manager:
        await state.risk_manager.update_snapshot()
        snap = state.risk_manager.snapshot
        risk = {
            "total_exposure": float(snap.total_exposure),
            "daily_pnl": float(snap.daily_pnl),
            "daily_trades": snap.daily_trades,
            "position_count": snap.position_count,
            "open_orders": snap.open_orders,
            "kill_switch_active": state.risk_manager.kill_switch_active,
        }

    # ── Agent ─────────────────────────────────────────────
    agent_summary: dict[str, Any] = {"status": "not_initialized"}
    if state.autonomous_agent:
        agent_summary = {
            "status": state.autonomous_agent.status.value,
            "is_running": state.autonomous_agent.is_running,
        }
        if state.autonomous_agent.is_running:
            s = state.autonomous_agent.stats
            agent_summary.update({
                "target_profit": s.target_profit,
                "current_pnl": round(s.current_pnl, 2),
                "progress_pct": round(s.progress_pct, 2),
                "orders_placed": s.orders_placed,
                "orders_filled": s.orders_filled,
                "orders_failed": s.orders_failed,
            })

    # ── Frankenstein ──────────────────────────────────────
    frank_summary: dict[str, Any] = {"status": "not_initialized"}
    if state.frankenstein:
        try:
            full_status = state.frankenstein.status()
            frank_summary = {
                "is_alive": full_status.get("is_alive", False),
                "is_trading": full_status.get("is_trading", False),
                "total_scans": full_status.get("total_scans", 0),
                "total_signals": full_status.get("total_signals", 0),
                "total_trades": full_status.get("total_trades_executed", 0),
            }
        except Exception:
            frank_summary = {"status": "error"}

    # ── Markets ───────────────────────────────────────────
    active_markets = market_cache.get_active()

    return {
        "balance": balance,
        "pnl": pnl,
        "positions": positions,
        "risk": risk,
        "agent": agent_summary,
        "frankenstein": frank_summary,
        "active_markets_count": len(active_markets),
        "total_cached_markets": len(market_cache.get_all()),
    }
