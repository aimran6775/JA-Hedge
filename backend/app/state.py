"""
JA Hedge — Application State (singleton).

Holds initialized instances of all engine components so that
route handlers and background tasks can access them.

Populated during FastAPI lifespan startup; reset on shutdown.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from app.kalshi.api import KalshiAPI
    from app.engine.execution import ExecutionEngine
    from app.engine.risk import RiskManager
    from app.engine.paper_trader import PaperTradingSimulator
    from app.pipeline import MarketDataPipeline
    from app.pipeline.portfolio_tracker import PortfolioTracker
    from app.ai.features import FeatureEngine
    from app.ai.models import PredictionModel
    from app.ai.agent import AutonomousAgent
    from app.ai.strategy import TradingStrategy
    from app.strategies import StrategyEngine
    from app.frankenstein.brain import Frankenstein
    from app.sports.detector import SportsDetector
    from app.sports.odds_client import OddsClient
    from app.sports.game_tracker import GameTracker
    from app.sports.model import SportsPredictor
    from app.sports.features import SportsFeatureEngine
    from app.sports.live_engine import LiveTradingEngine
    from app.sports.risk import SportsRiskManager
    from app.sports.collector import SportsDataCollector
    from app.sports.monitor import SportsMonitor
    from app.alerts import AlertManager
    from app.intelligence.hub import DataSourceHub
    from app.intelligence.fusion import FeatureFusionEngine
    from app.intelligence.confidence import SourceConfidenceTracker, AdaptiveWeightEngine
    from app.intelligence.alerts import AlertPipeline as IntelAlertPipeline
    from app.intelligence.backfill import HistoricalBackfillEngine
    from app.intelligence.correlation import SourceCorrelationMatrix
    from app.intelligence.quality import DataQualityMonitor


@dataclass
class AppState:
    """Global application state — initialised in lifespan."""

    # Core Kalshi client
    kalshi_api: KalshiAPI | None = None

    # Engines
    execution_engine: ExecutionEngine | None = None
    risk_manager: RiskManager | None = None
    trading_strategy: TradingStrategy | None = None  # legacy
    paper_simulator: PaperTradingSimulator | None = None

    # Pipelines
    market_pipeline: MarketDataPipeline | None = None
    portfolio_tracker: PortfolioTracker | None = None

    # AI
    feature_engine: FeatureEngine | None = None
    prediction_model: PredictionModel | None = None
    autonomous_agent: AutonomousAgent | None = None  # legacy

    # 📊 Strategy Engine (pre-built trading strategies)
    strategy_engine: StrategyEngine | None = None

    # 🧟 FRANKENSTEIN — The unified AI brain
    frankenstein: Frankenstein | None = None

    # 🏀 Sports Module
    sports_detector: SportsDetector | None = None
    odds_client: OddsClient | None = None
    game_tracker: GameTracker | None = None
    sports_predictor: SportsPredictor | None = None
    sports_feature_engine: SportsFeatureEngine | None = None
    live_engine: LiveTradingEngine | None = None
    sports_risk: SportsRiskManager | None = None
    sports_collector: SportsDataCollector | None = None
    sports_monitor: SportsMonitor | None = None

    # Alerts
    alert_manager: AlertManager | None = None

    # 🧠 Intelligence System (multi-source data)
    intelligence_hub: DataSourceHub | None = None
    feature_fusion: FeatureFusionEngine | None = None
    confidence_tracker: SourceConfidenceTracker | None = None
    adaptive_weights: AdaptiveWeightEngine | None = None
    alert_pipeline: IntelAlertPipeline | None = None
    backfill_engine: HistoricalBackfillEngine | None = None
    correlation_matrix: SourceCorrelationMatrix | None = None
    quality_monitor: DataQualityMonitor | None = None

    # Flags
    ready: bool = False
    db_available: bool = False  # tracks whether DB initialized successfully


# Singleton — imported by route modules
state = AppState()


def reset_state() -> None:
    """Clear all references (used during shutdown)."""
    global state
    state = AppState()
