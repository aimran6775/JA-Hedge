"""Prometheus-compatible /metrics endpoint for monitoring."""

from __future__ import annotations

from fastapi import APIRouter, Response

from app.state import state

router = APIRouter(tags=["metrics"])


def _metric(name: str, value: float | int, *, help_: str = "", typ: str = "gauge") -> str:
    """Format a single Prometheus metric line."""
    lines = []
    if help_:
        lines.append(f"# HELP {name} {help_}")
    lines.append(f"# TYPE {name} {typ}")
    lines.append(f"{name} {value}")
    return "\n".join(lines)


@router.get("/metrics", response_class=Response)
async def metrics() -> Response:
    """
    Prometheus-style metrics for scraping.

    Exposes:
      - jahedge_paper_balance_cents
      - jahedge_paper_pnl_cents
      - jahedge_paper_total_trades
      - jahedge_frank_total_scans
      - jahedge_frank_total_trades_executed
      - jahedge_frank_open_positions
      - jahedge_frank_side_yes_ratio
      - jahedge_frank_circuit_breaker (1 = active, 0 = inactive)
      - jahedge_frank_is_alive
      - jahedge_frank_is_paused
      - jahedge_frank_uptime_seconds
      - jahedge_kalshi_api_ready
    """
    parts: list[str] = []

    # Paper trading
    sim = state.paper_simulator
    if sim is not None:
        parts.append(_metric(
            "jahedge_paper_balance_cents",
            sim.balance_cents,
            help_="Current paper trading balance in cents",
        ))
        parts.append(_metric(
            "jahedge_paper_pnl_cents",
            sim.balance_cents - sim.starting_balance_cents,
            help_="Realized + unrealized P&L vs starting balance, cents",
        ))
        parts.append(_metric(
            "jahedge_paper_total_trades",
            sim.total_fills,
            help_="Total paper fills",
            typ="counter",
        ))
        parts.append(_metric(
            "jahedge_paper_open_positions",
            sum(1 for p in sim._positions.values() if (p.yes_count + p.no_count) > 0),
            help_="Open paper positions",
        ))

    # Frankenstein
    frank = state.frankenstein
    if frank is not None:
        parts.append(_metric(
            "jahedge_frank_is_alive",
            1 if getattr(frank, "is_alive", False) else 0,
        ))
        parts.append(_metric(
            "jahedge_frank_is_paused",
            1 if getattr(frank._state, "is_paused", False) else 0,
        ))
        parts.append(_metric(
            "jahedge_frank_total_scans",
            getattr(frank._state, "total_scans", 0),
            typ="counter",
        ))
        parts.append(_metric(
            "jahedge_frank_total_trades_executed",
            getattr(frank._state, "total_trades_executed", 0),
            typ="counter",
        ))
        parts.append(_metric(
            "jahedge_frank_total_signals",
            getattr(frank._state, "total_signals", 0),
            typ="counter",
        ))
        parts.append(_metric(
            "jahedge_frank_circuit_breaker",
            1 if getattr(frank._state, "circuit_breaker_active", False) else 0,
        ))
        # Side balance ratio over recent window
        try:
            import time as _t
            uptime = _t.time() - getattr(frank._state, "start_time", _t.time())
            parts.append(_metric("jahedge_frank_uptime_seconds", uptime))
        except Exception:
            pass
        try:
            recent = list(frank.memory._trades)[-50:]
            buys = [t for t in recent if t.action == "buy" and t.predicted_side in ("yes", "no")]
            if buys:
                yes = sum(1 for t in buys if t.predicted_side == "yes")
                ratio = yes / len(buys)
                parts.append(_metric(
                    "jahedge_frank_side_yes_ratio",
                    round(ratio, 4),
                    help_="Fraction of recent trades that bought YES (target 0.5)",
                ))
                parts.append(_metric(
                    "jahedge_frank_recent_trade_window",
                    len(buys),
                ))
        except Exception:
            pass
        # Win rate
        try:
            resolved = [t for t in frank.memory._trades if t.market_result in ("yes", "no")]
            if resolved:
                wins = sum(1 for t in resolved if t.predicted_side == t.market_result)
                parts.append(_metric(
                    "jahedge_frank_win_rate",
                    round(wins / len(resolved), 4),
                ))
                parts.append(_metric(
                    "jahedge_frank_resolved_trades",
                    len(resolved),
                    typ="counter",
                ))
        except Exception:
            pass

    # Kalshi API
    parts.append(_metric(
        "jahedge_kalshi_api_ready",
        1 if state.kalshi_api is not None else 0,
    ))

    body = "\n".join(parts) + "\n"
    return Response(content=body, media_type="text/plain; version=0.0.4")
