"""
JA Hedge — Autonomous Agent API Routes.

POST /api/agent/start     — Start agent with profit target
POST /api/agent/stop      — Stop the agent
GET  /api/agent/status    — Full agent status + stats + recent trades
PUT  /api/agent/config    — Update agent configuration
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.state import state

router = APIRouter(prefix="/agent", tags=["Agent"])


# ── Request / Response Models ─────────────────────────────────────────────────


class StartAgentRequest(BaseModel):
    target_profit: float = Field(..., gt=0, description="Dollar profit target (e.g., 4100.0)")
    aggressiveness: str = Field("moderate", description="conservative | moderate | aggressive")


class StopAgentResponse(BaseModel):
    status: str
    session_id: str = ""
    final_pnl: float = 0
    progress_pct: float = 0


class AgentStatusResponse(BaseModel):
    status: str = "idle"
    session_id: str = ""
    aggressiveness: str = "moderate"
    stats: dict = {}
    recent_trades: list[dict] = []
    config: dict = {}


class AgentConfigUpdate(BaseModel):
    aggressiveness: str | None = None
    max_loss_pct: float | None = None
    max_trades_per_scan: int | None = None
    scan_interval: float | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────


def _require_agent():
    if not state.autonomous_agent:
        raise HTTPException(503, detail="Autonomous agent not initialized")


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/start")
async def start_agent(body: StartAgentRequest) -> dict:
    """
    Start the autonomous AI trading agent.

    The agent will trade autonomously to hit the profit target.
    """
    _require_agent()

    result = await state.autonomous_agent.start(
        target_profit=body.target_profit,
        aggressiveness=body.aggressiveness,
    )
    return result


@router.post("/stop")
async def stop_agent() -> dict:
    """Stop the autonomous agent gracefully."""
    _require_agent()
    result = await state.autonomous_agent.stop()
    return result


@router.get("/status", response_model=AgentStatusResponse)
async def agent_status() -> AgentStatusResponse:
    """Get comprehensive agent status, stats, and recent trades."""
    if not state.autonomous_agent:
        return AgentStatusResponse()

    data = state.autonomous_agent.get_status()
    return AgentStatusResponse(**data)


@router.put("/config")
async def update_agent_config(body: AgentConfigUpdate) -> dict:
    """Update agent configuration while running."""
    _require_agent()

    agent = state.autonomous_agent

    if body.aggressiveness:
        from app.ai.agent import Aggressiveness
        try:
            agg = Aggressiveness(body.aggressiveness.lower())
            agent._aggressiveness = agg
            agent._apply_aggressiveness(agg)
        except ValueError:
            raise HTTPException(400, detail=f"Invalid aggressiveness: {body.aggressiveness}")

    if body.max_loss_pct is not None:
        agent._max_loss_pct = body.max_loss_pct

    if body.max_trades_per_scan is not None:
        agent._max_trades_per_scan = body.max_trades_per_scan

    if body.scan_interval is not None:
        agent._scan_interval = body.scan_interval

    return {"status": "updated", "config": agent.get_status()["config"]}
