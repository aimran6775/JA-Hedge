"""
JA Hedge — Frankenstein API Routes.

Endpoints to monitor, control, and interact with the
Frankenstein AI brain.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.state import state
from app.logging_config import get_logger

log = get_logger("routes.frankenstein")
router = APIRouter(prefix="/frankenstein", tags=["frankenstein"])


def _get_frank():
    """Get Frankenstein or raise 503."""
    if state.frankenstein is None:
        raise HTTPException(503, "Frankenstein not initialized")
    return state.frankenstein


# ── Status ────────────────────────────────────────────────────────────────────

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
