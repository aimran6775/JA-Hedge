"""
JA Hedge — Frankenstein AI System.

Frankenstein is the unified AI brain that controls the entire
JA Hedge trading platform. It continuously learns from every
trade, adapts its strategy in real-time, and gets smarter
with every market cycle.

Modules:
    brain.py        — The central Frankenstein brain (orchestrator)
    memory.py       — Trade memory & experience replay buffer
    learner.py      — Online learning pipeline (hourly retraining)
    performance.py  — Performance tracking (Sharpe, drawdown, accuracy)
    strategy.py     — Adaptive strategy engine (self-tuning parameters)
    scheduler.py    — Background scheduler for periodic tasks
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
