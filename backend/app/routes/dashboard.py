"""
JA Hedge — Dashboard Aggregation API route.

GET  /api/dashboard  — Single endpoint returning all overview data
"""

from __future__ import annotations

import time
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
            f = state.frankenstein
            s = f._state
            mem = f.memory.stats()
            frank_summary = {
                "is_alive": s.is_alive,
                "is_trading": s.is_trading and not s.is_paused,
                "is_paused": s.is_paused,
                "total_scans": s.total_scans,
                "total_signals": s.total_signals,
                "total_trades": s.total_trades_executed,
                "total_rejected": s.total_trades_rejected,
                "generation": s.generation,
                "model_version": s.model_version,
                "uptime_seconds": time.time() - s.birth_time if s.birth_time else 0,
                "last_scan_ms": s.current_scan_time_ms,
                "win_rate": mem.get("win_rate", "0%"),
                "total_pnl": mem.get("total_pnl", "$0"),
                "pending_trades": mem.get("pending", 0),
                "resolved_trades": mem.get("total_resolved", 0),
                "categories": f.categories.stats().get("category_distribution", {}),
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
