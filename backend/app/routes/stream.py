"""
JA Hedge — Server-Sent Events (SSE) stream.

GET  /api/stream  — Real-time event stream for the dashboard.

Pushes a JSON snapshot every ~3 seconds containing balance, positions,
brain status, recent trades, risk, and PnL so the frontend never needs
to poll multiple endpoints.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.state import state
from app.pipeline.portfolio_tracker import portfolio_state
from app.pipeline import market_cache

router = APIRouter(prefix="/stream", tags=["Stream"])


async def _build_snapshot() -> dict[str, Any]:
    """Build a lightweight dashboard snapshot for SSE push."""
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
    risk: dict[str, Any] = {"kill_switch_active": False}
    if state.risk_manager:
        try:
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
        except Exception:
            pass

    # ── Frankenstein ──────────────────────────────────────
    frank: dict[str, Any] = {"status": "not_initialized"}
    if state.frankenstein:
        try:
            f = state.frankenstein
            s = f._state
            mem = f.memory.stats()
            perf = f.performance.snapshot()
            strat = f.strategy.current_params
            frank = {
                "is_alive": s.is_alive,
                "is_trading": s.is_trading and not s.is_paused,
                "is_paused": s.is_paused,
                "total_scans": s.total_scans,
                "total_signals": s.total_signals,
                "total_trades_executed": s.total_trades_executed,
                "total_trades_rejected": s.total_trades_rejected,
                "generation": s.generation,
                "model_version": s.model_version,
                "uptime_seconds": time.time() - s.birth_time if s.birth_time else 0,
                "daily_trades": getattr(s, "daily_trades", 0),
                "daily_trade_cap": getattr(f, "_daily_trade_cap", 500),
                "last_scan_ms": s.current_scan_time_ms,
                "performance": {
                    "win_rate": perf.get("win_rate", 0),
                    "total_pnl": perf.get("total_pnl", 0),
                    "sharpe_ratio": perf.get("sharpe_ratio", 0),
                    "profit_factor": perf.get("profit_factor", 0),
                    "max_drawdown": perf.get("max_drawdown", 0),
                    "real_trades": perf.get("real_trades", 0),
                },
                "memory": {
                    "total_recorded": mem.get("total_recorded", 0),
                    "pending": mem.get("pending", 0),
                    "total_resolved": mem.get("total_resolved", 0),
                    "win_rate": mem.get("win_rate", 0),
                },
                "strategy": {
                    "min_confidence": strat.min_confidence,
                    "min_edge": strat.min_edge,
                    "kelly_fraction": strat.kelly_fraction,
                    "aggression": strat.aggression,
                },
            }
        except Exception:
            frank = {"status": "error"}

    # ── Recent trades (last 15) ───────────────────────────
    recent_trades: list[dict[str, Any]] = []
    if state.frankenstein:
        try:
            raw = state.frankenstein.memory.recent(15)
            for t in raw:
                recent_trades.append({
                    "ticker": t.get("ticker", ""),
                    "side": t.get("side", ""),
                    "action": t.get("action", "buy"),
                    "count": t.get("count", 1),
                    "price_cents": t.get("price_cents", 0),
                    "confidence": t.get("confidence", 0),
                    "edge": t.get("edge", 0),
                    "outcome": t.get("outcome", "pending"),
                    "pnl_cents": t.get("pnl_cents", 0),
                    "timestamp": t.get("timestamp", ""),
                    "category": t.get("category", ""),
                    "model_version": t.get("model_version", ""),
                })
        except Exception:
            pass

    return {
        "type": "snapshot",
        "ts": time.time(),
        "balance": balance,
        "pnl": pnl,
        "positions": positions,
        "risk": risk,
        "frankenstein": frank,
        "recent_trades": recent_trades,
        "active_markets": len(market_cache.get_active()),
        "total_markets": len(market_cache.get_all()),
    }


async def _event_generator() -> AsyncGenerator[str, None]:
    """Yield SSE events every 3 seconds."""
    yield "event: connected\ndata: {}\n\n"
    while True:
        try:
            snapshot = await _build_snapshot()
            data = json.dumps(snapshot, default=str)
            yield f"event: snapshot\ndata: {data}\n\n"
        except Exception as exc:
            error = json.dumps({"error": str(exc)})
            yield f"event: error\ndata: {error}\n\n"
        await asyncio.sleep(3)


@router.get("")
async def stream():
    """SSE endpoint for real-time dashboard updates."""
    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
