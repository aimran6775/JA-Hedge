"""
JA Hedge — Frankenstein AI System. 🧟

Frankenstein is the unified AI brain that controls the entire
JA Hedge trading platform. It continuously learns from every
trade, adapts its strategy in real-time, and gets smarter
with every market cycle.

Architecture (Phase 1 modular split + Phase 2 reactive):
    brain.py        — Slim orchestrator (~400 lines): lifecycle, wiring, status
    constants.py    — Shared constants: fees, maker mode, edge caps, limits
    event_bus.py    — Async pub/sub system for inter-module communication
    scanner.py      — Market scanning, signal evaluation, trade selection
    order_manager.py— Order placement, pricing, lifecycle, fill tracking, requoting
    positions.py    — Active position management, exit logic
    resolver.py     — Outcome resolution (4 methods), calibration, category stats
    ws_bridge.py    — WebSocket bridge: real-time Kalshi data → EventBus (Phase 2)

Supporting modules:
    memory.py       — Trade memory & experience replay buffer
    learner.py      — Online learning pipeline (hourly retraining)
    performance.py  — Performance tracking (Sharpe, drawdown, accuracy)
    strategy.py     — Adaptive strategy engine (self-tuning parameters)
    scheduler.py    — Background scheduler for periodic tasks
    categories.py   — Market category detection & edge caps
    confidence.py   — Multi-factor confidence scoring (grade A+ to C)
    chat.py         — Conversational interface to Frankenstein
"""

from app.frankenstein.brain import Frankenstein
from app.frankenstein.memory import TradeMemory
from app.frankenstein.learner import OnlineLearner
from app.frankenstein.performance import PerformanceTracker
from app.frankenstein.strategy import AdaptiveStrategy
from app.frankenstein.scheduler import FrankensteinScheduler

__all__ = [
    "Frankenstein",
    "TradeMemory",
    "OnlineLearner",
    "PerformanceTracker",
    "AdaptiveStrategy",
    "FrankensteinScheduler",
]
