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

    # 📊 Strategy Engine (pre-built trading strategies)
    strategy_engine: Any | None = None  # StrategyEngine

    # 🧟 FRANKENSTEIN — The unified AI brain
    frankenstein: Any | None = None  # Frankenstein

    # 🏀 Sports Module
    sports_detector: Any | None = None       # SportsDetector
    odds_client: Any | None = None           # OddsClient
    game_tracker: Any | None = None          # GameTracker
    sports_predictor: Any | None = None      # SportsPredictor
    sports_feature_engine: Any | None = None # SportsFeatureEngine
    live_engine: Any | None = None           # LiveTradingEngine
    sports_risk: Any | None = None           # SportsRiskManager
    sports_collector: Any | None = None      # SportsDataCollector
    sports_monitor: Any | None = None        # SportsMonitor

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
