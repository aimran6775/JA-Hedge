"""
Frankenstein — Fill Rate Prediction Model. 🧟📊

Phase 5: Predicts the probability that a maker limit order will fill
based on observable features at placement time.

Why this matters:
  - Maker orders only fill ~50-70% of the time (we don't cross the spread)
  - Kelly sizing should discount by fill probability to avoid over-committing
    capital to orders that won't execute
  - Requoting should be more aggressive when fill probability is low
  - Orders with very low fill probability should be cancelled early

Model: Lightweight online logistic regression (sklearn SGDClassifier) that
learns incrementally from each fill/cancel outcome. No heavy training loop —
just one partial_fit call per outcome.

Features (at order placement time):
  - spread_cents:     wider spread → lower fill probability
  - price_vs_mid:     how far inside the spread we're placing (improvement)
  - side:             yes=1, no=0  (slight asymmetry in fill rates)
  - volume_log:       log(market volume) — higher volume → more fills
  - hour_of_day:      0-23 (liquidity varies by time)
  - open_interest_log: log(open interest) — proxy for depth
  - hours_to_expiry:  markets near expiry have faster fills
  - amend_count:      more amends → chasing the market (lower fill prob)

Target: 1 = filled, 0 = cancelled/stale

This model is NOT loaded from disk — it's trained online from scratch each
session and improves as the session progresses. With ~50+ observations it
becomes useful; below that it returns a flat prior.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.logging_config import get_logger

log = get_logger("frankenstein.fill_predictor")

# Minimum observations before the model's predictions are used
MIN_OBSERVATIONS_FOR_PREDICTION = 30
# Default fill probability when we don't have enough data
DEFAULT_FILL_PROB = 0.60  # conservative prior for maker orders
# Feature count
N_FEATURES = 8


@dataclass
class FillObservation:
    """One observed fill/cancel event for training."""

    # Features
    spread_cents: int = 0
    price_vs_mid_cents: int = 0   # how far our price is from mid (positive = closer to mid)
    side: str = "yes"             # "yes" or "no"
    volume: float = 0.0           # market volume at placement
    open_interest: float = 0.0    # market OI at placement
    hour_of_day: int = 0          # 0-23
    hours_to_expiry: float = 24.0
    amend_count: int = 0          # how many times we amended this order

    # Target
    filled: bool = False          # True = filled, False = cancelled/stale

    # Metadata
    ticker: str = ""
    order_id: str = ""
    time_resting_seconds: float = 0.0  # how long before fill/cancel
    timestamp: float = field(default_factory=time.time)

    def to_feature_array(self) -> np.ndarray:
        """Convert to feature vector for the model."""
        return np.array([
            self.spread_cents,
            self.price_vs_mid_cents,
            1.0 if self.side == "yes" else 0.0,
            math.log1p(self.volume),
            math.log1p(self.open_interest),
            self.hour_of_day / 24.0,
            min(self.hours_to_expiry, 168.0) / 168.0,  # normalize to 0-1 (cap at 1 week)
            min(self.amend_count, 10) / 10.0,
        ], dtype=np.float64)


class FillPredictor:
    """
    Online fill probability predictor.

    Learns incrementally from each fill/cancel observation using
    SGDClassifier with log loss (logistic regression).

    Usage:
        predictor = FillPredictor()

        # Record outcomes as they happen
        predictor.record_fill(obs)    # order was filled
        predictor.record_cancel(obs)  # order was cancelled/stale

        # Predict fill probability for a new order
        prob = predictor.predict_fill_probability(obs)
    """

    def __init__(self, *, max_history: int = 5000) -> None:
        self._model: Any = None       # SGDClassifier (created lazily)
        self._observations: deque[FillObservation] = deque(maxlen=max_history)
        self._n_fills: int = 0
        self._n_cancels: int = 0
        self._is_fitted: bool = False

        # Rolling statistics for fallback
        self._recent_fill_rate: float = DEFAULT_FILL_PROB

        # Metrics
        self._predictions_made: int = 0
        self._model_predictions: int = 0  # predictions from actual model (vs prior)

        log.info("fill_predictor_created")

    @property
    def total_observations(self) -> int:
        """Total observed fill/cancel events."""
        return self._n_fills + self._n_cancels

    def _ensure_model(self) -> Any:
        """Lazily create the SGDClassifier."""
        if self._model is None:
            try:
                from sklearn.linear_model import SGDClassifier
                self._model = SGDClassifier(
                    loss="log_loss",
                    penalty="l2",
                    alpha=0.001,
                    learning_rate="optimal",
                    warm_start=True,
                    random_state=42,
                )
            except ImportError:
                log.warning("sklearn not available — fill prediction disabled")
                self._model = "unavailable"
        return self._model

    # ── Record Outcomes ───────────────────────────────────────────────

    def record_fill(self, obs: FillObservation) -> None:
        """Record a filled order observation and update the model."""
        obs.filled = True
        self._observations.append(obs)
        self._n_fills += 1
        self._update_model(obs)
        self._update_rolling_rate()

    def record_cancel(self, obs: FillObservation) -> None:
        """Record a cancelled/stale order observation and update the model."""
        obs.filled = False
        self._observations.append(obs)
        self._n_cancels += 1
        self._update_model(obs)
        self._update_rolling_rate()

    def _update_model(self, obs: FillObservation) -> None:
        """Incrementally update the model with one new observation."""
        model = self._ensure_model()
        if model == "unavailable":
            return

        X = obs.to_feature_array().reshape(1, -1)
        y = np.array([1 if obs.filled else 0])

        try:
            model.partial_fit(X, y, classes=np.array([0, 1]))
            self._is_fitted = True
        except Exception as e:
            log.debug("fill_model_update_failed", error=str(e))

    def _update_rolling_rate(self) -> None:
        """Update the simple rolling fill rate."""
        total = self._n_fills + self._n_cancels
        if total > 0:
            self._recent_fill_rate = self._n_fills / total

    # ── Prediction ────────────────────────────────────────────────────

    def predict_fill_probability(
        self,
        spread_cents: int = 0,
        price_vs_mid_cents: int = 0,
        side: str = "yes",
        volume: float = 0.0,
        open_interest: float = 0.0,
        hour_of_day: int = 0,
        hours_to_expiry: float = 24.0,
        amend_count: int = 0,
    ) -> float:
        """
        Predict the probability that an order with these features will fill.

        Returns a value in [0.0, 1.0].

        Falls back to the rolling empirical fill rate if the model
        doesn't have enough data yet.
        """
        self._predictions_made += 1
        total_obs = self._n_fills + self._n_cancels

        # Not enough data — return empirical prior
        if total_obs < MIN_OBSERVATIONS_FOR_PREDICTION or not self._is_fitted:
            return self._recent_fill_rate

        model = self._ensure_model()
        if model == "unavailable":
            return self._recent_fill_rate

        try:
            obs = FillObservation(
                spread_cents=spread_cents,
                price_vs_mid_cents=price_vs_mid_cents,
                side=side,
                volume=volume,
                open_interest=open_interest,
                hour_of_day=hour_of_day,
                hours_to_expiry=hours_to_expiry,
                amend_count=amend_count,
            )
            X = obs.to_feature_array().reshape(1, -1)

            # SGDClassifier.predict_proba requires calibrated probabilities
            # Use decision_function and sigmoid as a more reliable approach
            decision = model.decision_function(X)[0]
            # Sigmoid: 1 / (1 + exp(-x))
            prob = 1.0 / (1.0 + math.exp(-max(-10, min(10, decision))))

            self._model_predictions += 1

            # Blend with empirical rate for stability (especially early on)
            blend_weight = min(total_obs / 200.0, 0.8)  # model gets up to 80% weight
            blended = blend_weight * prob + (1 - blend_weight) * self._recent_fill_rate

            return max(0.05, min(0.99, blended))
        except Exception as e:
            log.debug("fill_prediction_error", error=str(e))
            return self._recent_fill_rate

    def predict_from_order_context(
        self,
        ticker: str,
        side: str,
        price_cents: int,
        market: Any = None,
        features: Any = None,
    ) -> float:
        """
        Convenience method: predict fill probability from market context.

        Extracts the relevant features from the market/features objects.
        """
        from datetime import datetime, timezone

        spread_cents = 5  # default
        mid_cents = 50
        volume = 0.0
        oi = 0.0
        hte = 24.0

        if features is not None:
            spread_cents = max(1, int(getattr(features, "spread", 0.05) * 100))
            mid_cents = max(1, int(getattr(features, "midpoint", 0.50) * 100))
            volume = getattr(features, "volume", 0.0)
            hte = getattr(features, "hours_to_expiry", 24.0)

        if market is not None:
            oi = float(getattr(market, "open_interest", 0) or 0)
            if hasattr(market, "yes_bid") and hasattr(market, "yes_ask"):
                yb = float(market.yes_bid or 0)
                ya = float(market.yes_ask or 0)
                if yb > 0 and ya > 0:
                    spread_cents = max(1, int((ya - yb) * 100))
                    mid_cents = int((yb + ya) / 2.0 * 100)

        # Price improvement: how far inside the spread is our price
        price_vs_mid = abs(mid_cents - price_cents)

        hour = datetime.now(timezone.utc).hour

        return self.predict_fill_probability(
            spread_cents=spread_cents,
            price_vs_mid_cents=price_vs_mid,
            side=side,
            volume=volume,
            open_interest=oi,
            hour_of_day=hour,
            hours_to_expiry=hte,
            amend_count=0,
        )

    # ── Batch Refit ───────────────────────────────────────────────────

    def refit(self) -> dict[str, Any]:
        """
        Refit the model from all stored observations.

        Called periodically (e.g., every 30min) or after major changes.
        More stable than incremental updates alone.
        """
        if len(self._observations) < MIN_OBSERVATIONS_FOR_PREDICTION:
            return {"status": "insufficient_data", "observations": len(self._observations)}

        model = self._ensure_model()
        if model == "unavailable":
            return {"status": "sklearn_unavailable"}

        try:
            X = np.array([obs.to_feature_array() for obs in self._observations])
            y = np.array([1 if obs.filled else 0 for obs in self._observations])

            # Reset and fit from scratch for a cleaner model
            from sklearn.linear_model import SGDClassifier
            self._model = SGDClassifier(
                loss="log_loss",
                penalty="l2",
                alpha=0.001,
                learning_rate="optimal",
                warm_start=False,
                random_state=42,
            )

            # Fit in small batches to simulate online learning
            batch_size = 32
            for i in range(0, len(X), batch_size):
                batch_X = X[i:i+batch_size]
                batch_y = y[i:i+batch_size]
                self._model.partial_fit(batch_X, batch_y, classes=np.array([0, 1]))

            self._is_fitted = True

            # Compute training accuracy
            predictions = (self._model.decision_function(X) > 0).astype(int)
            accuracy = (predictions == y).mean()

            log.info("fill_predictor_refit",
                     observations=len(self._observations),
                     fills=int(y.sum()),
                     cancels=int(len(y) - y.sum()),
                     accuracy=f"{accuracy:.3f}",
                     fill_rate=f"{self._recent_fill_rate:.3f}")

            return {
                "status": "success",
                "observations": len(self._observations),
                "accuracy": round(accuracy, 3),
                "fill_rate": round(self._recent_fill_rate, 3),
            }
        except Exception as e:
            log.error("fill_predictor_refit_failed", error=str(e))
            return {"status": "error", "error": str(e)}

    # ── Stats ─────────────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        """Fill predictor statistics."""
        total = self._n_fills + self._n_cancels
        return {
            "observations": total,
            "fills": self._n_fills,
            "cancels": self._n_cancels,
            "empirical_fill_rate": round(self._recent_fill_rate, 3),
            "model_fitted": self._is_fitted,
            "model_active": total >= MIN_OBSERVATIONS_FOR_PREDICTION and self._is_fitted,
            "predictions_made": self._predictions_made,
            "model_predictions": self._model_predictions,
            "history_size": len(self._observations),
        }
