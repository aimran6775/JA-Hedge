"""
JA Hedge — Sports Feature Engineering (Phase S3).

~30 sports-specific features that capture the REAL edge:
  - Vegas vs Kalshi discrepancy (the "First Dollar" signal)
  - Line movement / steam detection
  - Live game state features
  - Sport-specific adjustments

These features are computed on top of the base MarketFeatures
and passed to the sports-specific ML model.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.ai.features import MarketFeatures
from app.kalshi.models import Market
from app.logging_config import get_logger

log = get_logger("sports.features")


@dataclass
class SportsFeatures:
    """
    Sports-specific feature vector.
    
    Computed from:
      - Base MarketFeatures (price, volume, time, etc.)
      - Vegas odds (from OddsClient cache)
      - Live game state (from GameTracker)
      - Sports detector metadata
    """
    
    # Base reference
    ticker: str = ""
    sport_id: str = ""
    market_type: str = ""      # "moneyline", "spread", "total"
    
    # ── Vegas Edge Features (THE CORE ALPHA) ───────────────────────
    # These are the most valuable features in the entire system
    vegas_home_prob: float = 0.0     # consensus moneyline prob for home
    vegas_away_prob: float = 0.0     # consensus moneyline prob for away
    vegas_implied_prob: float = 0.0  # Vegas implied prob for THIS market's side
    kalshi_price: float = 0.0        # Kalshi current mid price
    
    # THE KEY SIGNAL: Kalshi price vs Vegas consensus
    kalshi_vs_vegas_diff: float = 0.0   # positive = Kalshi higher than Vegas
    kalshi_vs_vegas_abs: float = 0.0    # absolute discrepancy
    
    # Bookmaker disagreement — more disagreement = more uncertainty
    bookmaker_spread: float = 0.0       # max - min across bookmakers
    num_bookmakers: int = 0
    
    # ── Line Movement Features ─────────────────────────────────────
    vegas_line_moved: float = 0.0       # how much the line has moved
    steam_move: bool = False            # sharp money detected (rapid line change)
    reverse_line_move: bool = False     # money on one side, line goes other way
    
    # ── Live Game State Features ───────────────────────────────────
    is_live: bool = False               # game in progress
    game_period: int = 0                # 1st quarter, 2nd half, etc.
    game_progress: float = 0.0         # 0.0 = start, 1.0 = end
    score_home: int = 0
    score_away: int = 0
    score_differential: float = 0.0    # home - away
    score_total: int = 0
    
    # Momentum
    is_close_game: bool = False        # within 1 score
    is_blowout: bool = False           # >20% of typical total ahead
    momentum_home: float = 0.0        # recent scoring trend
    
    # ── Timing Features ────────────────────────────────────────────
    hours_to_game: float = 0.0         # pregame: hours until start
    minutes_in_game: float = 0.0       # live: minutes since start
    is_garbage_time: bool = False      # blowout in late game
    is_crunch_time: bool = False       # close game in final period
    
    # ── Sport-Specific Features ────────────────────────────────────
    home_advantage: float = 0.0        # historical home edge for this sport
    typical_total: float = 0.0         # typical combined score
    total_pace: float = 0.0           # current pace vs typical (live)
    
    # ── Market Microstructure ──────────────────────────────────────
    sports_volume_rank: float = 0.0    # relative volume vs other sports markets
    time_since_odds_update: float = 0.0  # staleness of Vegas data
    
    # ── Composite Signals ──────────────────────────────────────────
    edge_signal: float = 0.0           # combined edge estimate
    confidence_signal: float = 0.0     # how confident we are in the edge
    
    def to_array(self) -> np.ndarray:
        """Convert to numpy array for ML model."""
        return np.array([
            self.vegas_implied_prob,
            self.kalshi_price,
            self.kalshi_vs_vegas_diff,
            self.kalshi_vs_vegas_abs,
            self.bookmaker_spread,
            self.num_bookmakers,
            self.vegas_line_moved,
            float(self.steam_move),
            float(self.reverse_line_move),
            float(self.is_live),
            self.game_period,
            self.game_progress,
            self.score_differential,
            self.score_total,
            float(self.is_close_game),
            float(self.is_blowout),
            self.momentum_home,
            self.hours_to_game,
            self.minutes_in_game,
            float(self.is_garbage_time),
            float(self.is_crunch_time),
            self.home_advantage,
            self.typical_total,
            self.total_pace,
            self.sports_volume_rank,
            self.time_since_odds_update,
            self.edge_signal,
            self.confidence_signal,
        ], dtype=np.float32)
    
    @classmethod
    def feature_names(cls) -> list[str]:
        return [
            "vegas_implied_prob", "kalshi_price",
            "kalshi_vs_vegas_diff", "kalshi_vs_vegas_abs",
            "bookmaker_spread", "num_bookmakers",
            "vegas_line_moved", "steam_move", "reverse_line_move",
            "is_live", "game_period", "game_progress",
            "score_differential", "score_total",
            "is_close_game", "is_blowout", "momentum_home",
            "hours_to_game", "minutes_in_game",
            "is_garbage_time", "is_crunch_time",
            "home_advantage", "typical_total", "total_pace",
            "sports_volume_rank", "time_since_odds_update",
            "edge_signal", "confidence_signal",
        ]
    
    @classmethod
    def n_features(cls) -> int:
        return 28


class SportsFeatureEngine:
    """
    Computes sports-specific features for a market.
    
    Requires:
      - SportsDetector (for sport classification)
      - OddsClient cache (for Vegas odds)
      - GameTracker (for live game state)
    """
    
    def __init__(self) -> None:
        self._odds_client = None   # set by main.py
        self._game_tracker = None  # set by main.py
        self._detector = None      # set by main.py
    
    def set_dependencies(
        self,
        detector=None,
        odds_client=None,
        game_tracker=None,
    ) -> None:
        """Inject dependencies after initialization."""
        if detector:
            self._detector = detector
        if odds_client:
            self._odds_client = odds_client
        if game_tracker:
            self._game_tracker = game_tracker
    
    def compute(
        self,
        market: Market,
        base_features: MarketFeatures,
    ) -> SportsFeatures:
        """Compute sports-specific features for a market."""
        sf = SportsFeatures(ticker=market.ticker)
        
        # Get detection info
        if self._detector:
            info = self._detector.detect(market)
            sf.sport_id = info.sport_id
            sf.market_type = info.market_type
            sf.is_live = info.is_live
            
            if info.sport_config:
                sf.home_advantage = info.sport_config.home_advantage
                sf.typical_total = info.sport_config.typical_total
        
        # Kalshi price
        sf.kalshi_price = base_features.midpoint
        
        # ── Vegas features ────────────────────────────────────────
        if self._odds_client and self._detector:
            info = self._detector.detect(market)
            game_odds = self._odds_client.find_game_odds(
                info.home_team, info.away_team
            )
            
            if game_odds:
                sf.vegas_home_prob = game_odds.consensus_home_prob
                sf.vegas_away_prob = game_odds.consensus_away_prob
                sf.num_bookmakers = len(game_odds.bookmakers)
                
                # Compute bookmaker disagreement
                if game_odds.bookmakers:
                    home_probs = [b.h2h_home for b in game_odds.bookmakers if b.h2h_home > 0]
                    if home_probs:
                        sf.bookmaker_spread = max(home_probs) - min(home_probs)
                
                # THE KEY SIGNAL: Vegas implied prob for this market
                if sf.market_type == "moneyline":
                    # If this is a "will home team win" market
                    if info.home_team and info.home_team.lower() in (market.title or "").lower():
                        sf.vegas_implied_prob = game_odds.consensus_home_prob
                    else:
                        sf.vegas_implied_prob = game_odds.consensus_away_prob
                elif sf.market_type == "spread":
                    # For spreads, use the spread probability
                    for bm in game_odds.bookmakers:
                        if bm.spread_home > 0:
                            sf.vegas_implied_prob = bm.spread_home
                            break
                elif sf.market_type == "total":
                    for bm in game_odds.bookmakers:
                        if bm.total_over > 0:
                            sf.vegas_implied_prob = bm.total_over
                            break
                
                # If we still don't have a good prob, use home moneyline as baseline
                if sf.vegas_implied_prob == 0 and game_odds.consensus_home_prob > 0:
                    sf.vegas_implied_prob = game_odds.consensus_home_prob
                
                # THE EDGE: Kalshi vs Vegas
                if sf.vegas_implied_prob > 0:
                    sf.kalshi_vs_vegas_diff = sf.kalshi_price - sf.vegas_implied_prob
                    sf.kalshi_vs_vegas_abs = abs(sf.kalshi_vs_vegas_diff)
                
                # Staleness
                sf.time_since_odds_update = time.time() - game_odds.fetched_at
        
        # ── Live game features ────────────────────────────────────
        if self._game_tracker and sf.is_live:
            game_state = self._game_tracker.get_state(market.event_ticker or market.ticker)
            if game_state:
                sf.game_period = game_state.get("period", 0)
                sf.game_progress = game_state.get("progress", 0.0)
                sf.score_home = game_state.get("home_score", 0)
                sf.score_away = game_state.get("away_score", 0)
                sf.score_differential = sf.score_home - sf.score_away
                sf.score_total = sf.score_home + sf.score_away
                sf.momentum_home = game_state.get("momentum_home", 0.0)
                sf.minutes_in_game = game_state.get("minutes_elapsed", 0.0)
                
                # Close game / blowout detection
                if sf.typical_total > 0:
                    one_score = sf.typical_total * 0.05  # ~1 score for the sport
                    sf.is_close_game = abs(sf.score_differential) <= one_score
                    sf.is_blowout = abs(sf.score_differential) > sf.typical_total * 0.20
                
                # Garbage time / crunch time
                if sf.game_progress > 0.80:
                    if sf.is_blowout:
                        sf.is_garbage_time = True
                    elif sf.is_close_game:
                        sf.is_crunch_time = True
                
                # Pace (projected total vs typical)
                if sf.game_progress > 0.1 and sf.typical_total > 0:
                    projected = sf.score_total / max(sf.game_progress, 0.01)
                    sf.total_pace = projected / sf.typical_total
        else:
            # Pregame: hours to game start
            sf.hours_to_game = base_features.hours_to_expiry
        
        # ── Composite signals ─────────────────────────────────────
        sf.edge_signal = self._compute_edge_signal(sf)
        sf.confidence_signal = self._compute_confidence_signal(sf)
        
        return sf
    
    def _compute_edge_signal(self, sf: SportsFeatures) -> float:
        """
        Composite edge signal: combines all indicators into one score.
        
        Range: -1 (strong NO edge) to +1 (strong YES edge)
        Sign = direction, magnitude = strength
        """
        signals = []
        
        # Primary signal: Kalshi vs Vegas discrepancy
        if sf.vegas_implied_prob > 0 and sf.kalshi_vs_vegas_abs > 0.02:
            # Vegas says different from Kalshi → edge exists
            # Negative diff means Kalshi is LOWER than Vegas → buy
            # Positive diff means Kalshi is HIGHER than Vegas → sell
            signals.append(-sf.kalshi_vs_vegas_diff * 3.0)  # amplify
        
        # Live momentum signal
        if sf.is_live and abs(sf.momentum_home) > 0:
            signals.append(sf.momentum_home * 0.5)
        
        # Garbage time → fade the market (revert to pregame fair value)
        if sf.is_garbage_time:
            signals.append(-sf.score_differential * 0.01)
        
        if not signals:
            return 0.0
        
        return max(-1.0, min(1.0, sum(signals) / len(signals)))
    
    def _compute_confidence_signal(self, sf: SportsFeatures) -> float:
        """
        How confident we are in the edge signal.
        Range: 0 (no confidence) to 1 (max confidence)
        """
        confidence = 0.5  # base
        
        # More bookmakers = more reliable consensus
        if sf.num_bookmakers >= 8:
            confidence += 0.15
        elif sf.num_bookmakers >= 5:
            confidence += 0.10
        elif sf.num_bookmakers < 3:
            confidence -= 0.15
        
        # Low bookmaker disagreement = more reliable line
        if sf.bookmaker_spread < 0.03:
            confidence += 0.10
        elif sf.bookmaker_spread > 0.08:
            confidence -= 0.10
        
        # Large Kalshi-Vegas discrepancy = potentially real edge
        if sf.kalshi_vs_vegas_abs > 0.05:
            confidence += 0.10
        if sf.kalshi_vs_vegas_abs > 0.10:
            confidence += 0.10
        
        # Stale data = less confidence
        if sf.time_since_odds_update > 600:  # >10 min
            confidence -= 0.10
        if sf.time_since_odds_update > 1800:  # >30 min
            confidence -= 0.15
        
        # Live games with blowout = high confidence in outcome
        if sf.is_live and sf.is_blowout and sf.game_progress > 0.70:
            confidence += 0.20
        
        return max(0.0, min(1.0, confidence))


# Singleton
sports_feature_engine = SportsFeatureEngine()
