"""
JA Hedge — Application State (singleton).

Holds initialized instances of all engine components so that
route handlers and background tasks can access them.

Populated during FastAPI lifespan startup; reset on shutdown.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AppState:
    """Global application state — initialised in lifespan."""

    # Core Kalshi client
    kalshi_api: Any | None = None  # KalshiAPI

    # Engines
    execution_engine: Any | None = None  # ExecutionEngine
    risk_manager: Any | None = None  # RiskManager
    trading_strategy: Any | None = None  # TradingStrategy (legacy)
    paper_simulator: Any | None = None  # PaperTradingSimulator (fake money)

    # Pipelines
    market_pipeline: Any | None = None  # MarketDataPipeline
    portfolio_tracker: Any | None = None  # PortfolioTracker

    # AI
    feature_engine: Any | None = None  # FeatureEngine
    prediction_model: Any | None = None  # PredictionModel
    autonomous_agent: Any | None = None  # AutonomousAgent (legacy)

    # 🧟 FRANKENSTEIN — The unified AI brain
    frankenstein: Any | None = None  # Frankenstein

    # Alerts
    alert_manager: Any | None = None  # AlertManager

    # Flags
    ready: bool = False


# Singleton — imported by route modules
state = AppState()


def reset_state() -> None:
    """Clear all references (used during shutdown)."""
    global state
    state = AppState()
