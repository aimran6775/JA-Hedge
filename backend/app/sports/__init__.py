"""
JA Hedge — Sports Trading Module.

Specialized sports market trading system:
  S1: detector        — Ticker parsing, sport detection, market type classification
  S2: realtime_feed   — Multi-source consensus (ESPN, Twitter/Bluesky, RSS, Reddit)
  S3: features        — 30+ sports-specific features (consensus comparison, game state, team context)
  S4: game_tracker    — Live game state tracking via ESPN scores
  S5: model           — Dedicated sports ML model (XGBoost) + naive consensus baseline
  S6: live_engine     — In-game trading engine (score arb, momentum, garbage time)
  S7: risk            — Sports-specific risk management (game-level, correlation)
  S8: collector       — Historical data collection + backtesting framework
  S9: (frontend)      — Sports dashboard routes
  S10: monitor        — 24/7 monitoring, auto-retraining, alerting
"""

from app.sports.detector import SportsDetector, sports_detector, SPORT_REGISTRY
from app.sports.realtime_feed import RealtimeFeedClient
from app.sports.features import SportsFeatureEngine, sports_feature_engine
from app.sports.game_tracker import GameTracker, game_tracker
from app.sports.model import SportsPredictor, sports_predictor
from app.sports.live_engine import LiveTradingEngine, live_engine
from app.sports.risk import SportsRiskManager, sports_risk
from app.sports.collector import SportsDataCollector, sports_collector
from app.sports.monitor import SportsMonitor, sports_monitor

__all__ = [
    "SportsDetector", "sports_detector", "SPORT_REGISTRY",
    "RealtimeFeedClient",
    "SportsFeatureEngine", "sports_feature_engine",
    "GameTracker", "game_tracker",
    "SportsPredictor", "sports_predictor",
    "LiveTradingEngine", "live_engine",
    "SportsRiskManager", "sports_risk",
    "SportsDataCollector", "sports_collector",
    "SportsMonitor", "sports_monitor",
]
