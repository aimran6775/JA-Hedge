"""
JA Hedge — Sports Prediction Model (Phase S5).

Dedicated sports predictor with two strategies:
  1. Naive Vegas Baseline (Rule-based):
     - If Kalshi price diverges >5% from Vegas consensus → trade toward Vegas
     - No ML needed, works immediately
  
  2. Sports XGBoost (ML-based):
     - Trained on sports-specific features (SportsFeatures)
     - Walk-forward validation to prevent overfitting
     - Only activated after sufficient training data
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.ai.models import Prediction
from app.logging_config import get_logger

log = get_logger("sports.model")


@dataclass
class SportsPrediction:
    """Enhanced prediction with Vegas comparison data."""
    side: str = "yes"
    confidence: float = 0.0
    predicted_prob: float = 0.5
    edge: float = 0.0
    model_name: str = "sports_model"
    model_version: str = "v1"
    
    # Sports extras
    vegas_prob: float = 0.0
    kalshi_price: float = 0.0
    discrepancy: float = 0.0     # kalshi - vegas
    strategy_used: str = ""      # "vegas_baseline" or "sports_xgb"
    sport_id: str = ""
    
    def to_base_prediction(self) -> Prediction:
        """Convert to base Prediction for Frankenstein compatibility."""
        return Prediction(
            side=self.side,
            confidence=self.confidence,
            predicted_prob=self.predicted_prob,
            edge=self.edge,
            model_name=self.model_name,
            model_version=self.model_version,
        )


class NaiveVegasBaseline:
    """
    Rule-based strategy: trade toward Vegas when Kalshi diverges.
    
    This is the "First Dollar Strategy" — no ML required, immediately
    profitable if Vegas lines are more accurate than Kalshi.
    
    Logic:
      If Kalshi YES price = 0.55 and Vegas implied prob = 0.48:
        → Kalshi is too high, SELL YES (or BUY NO) at 0.55
        → Expected profit: 0.55 - 0.48 = 7¢ per contract
    
      If Kalshi YES price = 0.40 and Vegas implied prob = 0.50:
        → Kalshi is too low, BUY YES at 0.40
        → Expected profit: 0.50 - 0.40 = 10¢ per contract
    """
    
    def __init__(
        self,
        min_discrepancy: float = 0.05,   # minimum 5% difference to trade
        max_discrepancy: float = 0.40,   # >40% difference is suspicious
        base_confidence: float = 0.65,   # base confidence for Vegas trades
    ):
        self.min_discrepancy = min_discrepancy
        self.max_discrepancy = max_discrepancy
        self.base_confidence = base_confidence
        self._stats = {"signals": 0, "passes": 0}
    
    def predict(
        self,
        kalshi_price: float,
        vegas_prob: float,
        *,
        num_bookmakers: int = 0,
        bookmaker_spread: float = 0.0,
        sport_id: str = "",
    ) -> SportsPrediction | None:
        """
        Generate a prediction based on Vegas-Kalshi discrepancy.
        
        Returns None if no actionable signal.
        """
        if vegas_prob <= 0.01 or vegas_prob >= 0.99:
            self._stats["passes"] += 1
            return None
        if kalshi_price <= 0.01 or kalshi_price >= 0.99:
            self._stats["passes"] += 1
            return None
        
        discrepancy = kalshi_price - vegas_prob
        abs_disc = abs(discrepancy)
        
        # Not enough divergence
        if abs_disc < self.min_discrepancy:
            self._stats["passes"] += 1
            return None
        
        # Too much divergence — suspicious (might be stale data)
        if abs_disc > self.max_discrepancy:
            self._stats["passes"] += 1
            return None
        
        # Confidence scales with discrepancy size and bookmaker agreement
        confidence = self.base_confidence
        
        # More bookmakers = more reliable signal
        if num_bookmakers >= 8:
            confidence += 0.05
        elif num_bookmakers >= 5:
            confidence += 0.02
        elif num_bookmakers < 3:
            confidence -= 0.10
        
        # Low bookmaker disagreement = more reliable
        if bookmaker_spread < 0.03:
            confidence += 0.05
        elif bookmaker_spread > 0.08:
            confidence -= 0.05
        
        # Larger discrepancies = higher confidence
        if abs_disc > 0.10:
            confidence += 0.05
        if abs_disc > 0.15:
            confidence += 0.05
        
        confidence = max(0.10, min(0.95, confidence))
        
        # Direction: if Kalshi is too high → sell (predict NO), if too low → buy (predict YES)
        if discrepancy > 0:
            # Kalshi > Vegas → Kalshi is overpriced → BUY NO
            side = "no"
            predicted_prob = 1.0 - vegas_prob  # our prob that NO settles
        else:
            # Kalshi < Vegas → Kalshi is underpriced → BUY YES
            side = "yes"
            predicted_prob = vegas_prob  # our prob that YES settles
        
        # Edge = our expected value per contract
        if side == "yes":
            cost = kalshi_price
        else:
            cost = 1.0 - kalshi_price
        edge = predicted_prob - cost
        
        self._stats["signals"] += 1
        
        return SportsPrediction(
            side=side,
            confidence=confidence,
            predicted_prob=predicted_prob,
            edge=edge,
            model_name="naive_vegas_baseline",
            model_version="v1",
            vegas_prob=vegas_prob,
            kalshi_price=kalshi_price,
            discrepancy=discrepancy,
            strategy_used="vegas_baseline",
            sport_id=sport_id,
        )
    
    def stats(self) -> dict[str, Any]:
        return dict(self._stats)


class SportsPredictor:
    """
    Combined sports predictor.
    
    Uses Vegas baseline as primary strategy, with optional ML model
    for enhanced prediction when sufficient training data exists.
    """
    
    def __init__(self) -> None:
        self.vegas_baseline = NaiveVegasBaseline()
        self._xgb_model = None  # Future: trained XGBoost
        self._xgb_ready = False
        self._training_data: list[dict] = []
        self._max_training_data = 10000
        self._stats = {
            "predictions": 0,
            "vegas_used": 0,
            "ml_used": 0,
            "kalshi_only_used": 0,
        }
    
    def predict(
        self,
        sports_features: Any,  # SportsFeatures
        base_features: Any = None,  # MarketFeatures
    ) -> SportsPrediction | None:
        """
        Generate a sports prediction.
        
        Priority:
          1. If XGBoost model is trained and ready → use it
          2. Otherwise → use Vegas baseline
          3. If no Vegas data → Kalshi-only mean-reversion fallback
        """
        self._stats["predictions"] += 1
        
        # Try ML model first (when ready)
        if self._xgb_ready and self._xgb_model is not None:
            try:
                ml_pred = self._predict_xgb(sports_features)
                if ml_pred:
                    self._stats["ml_used"] += 1
                    return ml_pred
            except Exception as e:
                log.debug("xgb_predict_error", error=str(e))
        
        # Fall back to Vegas baseline
        if sports_features.vegas_implied_prob > 0:
            pred = self.vegas_baseline.predict(
                kalshi_price=sports_features.kalshi_price,
                vegas_prob=sports_features.vegas_implied_prob,
                num_bookmakers=sports_features.num_bookmakers,
                bookmaker_spread=sports_features.bookmaker_spread,
                sport_id=sports_features.sport_id,
            )
            if pred:
                self._stats["vegas_used"] += 1
                return pred
        
        # Kalshi-only fallback: trade extreme mispricing using market
        # microstructure signals when Vegas odds are unavailable.
        return self._predict_kalshi_only(sports_features, base_features)
    
    def _predict_xgb(self, sports_features: Any) -> SportsPrediction | None:
        """Use trained XGBoost model for prediction."""
        if not self._xgb_model:
            return None
        
        try:
            X = sports_features.to_array().reshape(1, -1)
            prob = self._xgb_model.predict_proba(X)[0][1]
            
            side = "yes" if prob > 0.5 else "no"
            confidence = abs(prob - 0.5) * 2  # scale to 0-1
            
            if side == "yes":
                edge = prob - sports_features.kalshi_price
            else:
                edge = (1.0 - prob) - (1.0 - sports_features.kalshi_price)
            
            if abs(edge) < 0.03:
                return None  # not enough edge
            
            return SportsPrediction(
                side=side,
                confidence=confidence,
                predicted_prob=prob,
                edge=edge,
                model_name="sports_xgb",
                model_version="v1",
                vegas_prob=sports_features.vegas_implied_prob,
                kalshi_price=sports_features.kalshi_price,
                discrepancy=sports_features.kalshi_vs_vegas_diff,
                strategy_used="sports_xgb",
                sport_id=sports_features.sport_id,
            )
        except Exception as e:
            log.debug("xgb_error", error=str(e))
            return None
    
    def _predict_kalshi_only(
        self,
        sports_features: Any,
        base_features: Any = None,
    ) -> SportsPrediction | None:
        """
        Kalshi-only fallback when Vegas odds are unavailable.
        
        Uses conservative mean-reversion logic on extreme prices:
          - Prices very close to 0 or 1 tend to revert
          - High volume + extreme price = more reliable signal
          - Only trades when the edge is large enough to overcome noise
        
        This is intentionally conservative (high threshold) because we
        lack the Vegas anchor that provides our strongest signal.
        """
        price = sports_features.kalshi_price
        if not base_features or price <= 0.02 or price >= 0.98:
            return None
        
        # Only trade mispricings with enough liquidity
        volume = getattr(base_features, "volume", 0)
        hours = getattr(base_features, "hours_to_expiry", 0)
        spread = getattr(base_features, "spread", 1.0)
        
        # Require minimum liquidity for Kalshi-only trades
        # Spread limit matches strategy params (15¢)
        if volume < 20 or spread > 0.15 or hours < 1.0:
            return None
        
        # Mean-reversion: prices outside 0.25-0.75 with decent volume
        # have positive expected reversion when the book is tight enough.
        if price < 0.25:
            # Cheap YES — potential value buy
            # Fair value estimate: regress toward 0.50 by 15%
            fair_est = price + (0.50 - price) * 0.15
            side = "yes"
            predicted_prob = fair_est
            cost = price
        elif price > 0.75:
            # Expensive YES — buy NO (cheap)
            fair_est = price - (price - 0.50) * 0.15
            side = "no"
            predicted_prob = 1.0 - fair_est
            cost = 1.0 - price
        else:
            # Price is in normal range — no Kalshi-only edge
            return None
        
        edge = predicted_prob - cost
        
        # Require larger edge than Vegas strategy (7% vs 5%)
        # because we're less confident without an anchor
        if edge < 0.07:
            return None
        
        # Conservative confidence — lower than Vegas-backed trades
        confidence = 0.35 + min(edge / 0.30, 0.20)  # 0.35 to 0.55
        
        # Boost slightly for high volume (more reliable price discovery)
        if volume > 500:
            confidence += 0.05
        
        confidence = max(0.30, min(0.60, confidence))
        
        self._stats["kalshi_only_used"] = self._stats.get("kalshi_only_used", 0) + 1
        
        return SportsPrediction(
            side=side,
            confidence=confidence,
            predicted_prob=predicted_prob,
            edge=edge,
            model_name="kalshi_only_mean_revert",
            model_version="v1",
            vegas_prob=0.0,
            kalshi_price=price,
            discrepancy=0.0,
            strategy_used="kalshi_only",
            sport_id=sports_features.sport_id,
        )
    
    def record_training_sample(
        self,
        features: Any,  # SportsFeatures
        outcome: str,  # "yes" or "no"
        pnl_cents: int = 0,
    ) -> None:
        """Record a completed trade for future model training."""
        try:
            sample = {
                "features": features.to_array().tolist(),
                "outcome": 1 if outcome == "yes" else 0,
                "pnl_cents": pnl_cents,
                "timestamp": time.time(),
            }
            self._training_data.append(sample)
            
            if len(self._training_data) > self._max_training_data:
                self._training_data = self._training_data[-self._max_training_data:]
            
        except Exception as e:
            log.debug("training_record_error", error=str(e))
    
    async def train(self, min_samples: int = 100) -> bool:
        """
        Train/retrain the XGBoost model on accumulated data.
        
        Uses walk-forward validation: train on first 80%, validate on last 20%.
        """
        if len(self._training_data) < min_samples:
            log.info("insufficient_training_data", 
                     samples=len(self._training_data), 
                     needed=min_samples)
            return False
        
        try:
            from xgboost import XGBClassifier
            from sklearn.model_selection import TimeSeriesSplit
            from sklearn.metrics import roc_auc_score
            
            # Prepare data
            X = np.array([s["features"] for s in self._training_data])
            y = np.array([s["outcome"] for s in self._training_data])
            
            # Walk-forward split (time-respecting)
            split_idx = int(len(X) * 0.8)
            X_train, X_val = X[:split_idx], X[split_idx:]
            y_train, y_val = y[:split_idx], y[split_idx:]
            
            if len(set(y_train)) < 2 or len(set(y_val)) < 2:
                log.warning("training_skipped_single_class")
                return False
            
            # Train XGBoost
            model = XGBClassifier(
                n_estimators=100,
                max_depth=4,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                reg_alpha=0.5,
                reg_lambda=1.0,
                eval_metric="logloss",
                verbosity=0,
            )
            model.fit(X_train, y_train)
            
            # Validate
            val_probs = model.predict_proba(X_val)[:, 1]
            auc = roc_auc_score(y_val, val_probs)
            
            if auc < 0.52:
                log.warning("model_not_better_than_random", auc=f"{auc:.3f}")
                return False
            
            self._xgb_model = model
            self._xgb_ready = True
            
            log.info("sports_model_trained", 
                     samples=len(X_train),
                     val_auc=f"{auc:.3f}",
                     features=X.shape[1])
            return True
            
        except ImportError:
            log.warning("xgboost_not_installed")
            return False
        except Exception as e:
            log.error("training_failed", error=str(e))
            return False
    
    def stats(self) -> dict[str, Any]:
        return {
            "predictions": self._stats["predictions"],
            "vegas_used": self._stats["vegas_used"],
            "ml_used": self._stats["ml_used"],
            "xgb_ready": self._xgb_ready,
            "training_samples": len(self._training_data),
            "vegas_baseline": self.vegas_baseline.stats(),
        }


# Singleton
sports_predictor = SportsPredictor()
