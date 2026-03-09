"""
JA Hedge — AI Prediction Models.

Pluggable model system:
- XGBoost (primary, fast inference ~1ms)
- Logistic Regression (baseline)
- Neural network (optional, for complex patterns)

Each model implements PredictionModel protocol:
  predict(features) → (side, confidence, edge)
"""

from __future__ import annotations

import pickle
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np

from app.ai.features import MarketFeatures
from app.logging_config import get_logger

log = get_logger("ai.models")


@dataclass
class Prediction:
    """Model prediction output."""

    side: str  # "yes" or "no"
    confidence: float  # 0.0 - 1.0
    predicted_prob: float  # model's predicted probability of YES
    edge: float  # predicted_prob - market_price (positive = opportunity)
    model_name: str = ""
    model_version: str = ""
    raw_output: Any = None


class PredictionModel(ABC):
    """Abstract base class for all prediction models."""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def version(self) -> str:
        ...

    @abstractmethod
    def predict(self, features: MarketFeatures) -> Prediction:
        """Generate a prediction from features."""
        ...

    @abstractmethod
    def predict_batch(self, features_list: list[MarketFeatures]) -> list[Prediction]:
        """Batch prediction for multiple markets."""
        ...

    def save(self, path: str) -> None:
        """Save model to disk."""
        raise NotImplementedError

    def load(self, path: str) -> None:
        """Load model from disk."""
        raise NotImplementedError


class XGBoostPredictor(PredictionModel):
    """
    XGBoost-based market predictor.

    Predicts the probability of YES outcome and computes
    edge vs current market price.
    """

    def __init__(self, model_path: str | None = None):
        self._model: Any = None
        self._model_path = model_path
        self._version = "1.0.0"
        self._feature_names = MarketFeatures.feature_names()

        if model_path and Path(model_path).exists():
            self.load(model_path)

    @property
    def name(self) -> str:
        return "xgboost_v1"

    @property
    def version(self) -> str:
        return self._version

    @property
    def is_trained(self) -> bool:
        return self._model is not None

    def predict(self, features: MarketFeatures) -> Prediction:
        """Predict YES probability for a single market."""
        if self._model is None:
            # Fallback: use simple heuristic when model isn't trained
            return self._heuristic_predict(features)

        try:
            import xgboost as xgb

            X = features.to_array().reshape(1, -1)
            dmatrix = xgb.DMatrix(X, feature_names=self._feature_names)
            prob_yes = float(self._model.predict(dmatrix)[0])

            return self._build_prediction(prob_yes, features)

        except Exception as e:
            log.error("xgb_predict_failed", error=str(e))
            return self._heuristic_predict(features)

    def predict_batch(self, features_list: list[MarketFeatures]) -> list[Prediction]:
        """Batch prediction for multiple markets."""
        if not features_list:
            return []

        if self._model is None:
            return [self._heuristic_predict(f) for f in features_list]

        try:
            import xgboost as xgb

            X = np.array([f.to_array() for f in features_list])
            dmatrix = xgb.DMatrix(X, feature_names=self._feature_names)
            probs = self._model.predict(dmatrix)

            return [
                self._build_prediction(float(prob), features)
                for prob, features in zip(probs, features_list)
            ]
        except Exception as e:
            log.error("xgb_batch_predict_failed", error=str(e))
            return [self._heuristic_predict(f) for f in features_list]

    def train(
        self,
        X: np.ndarray,
        y: np.ndarray,
        *,
        num_boost_round: int = 200,
        early_stopping_rounds: int = 20,
        eval_split: float = 0.2,
    ) -> dict[str, float]:
        """
        Train the XGBoost model.

        Args:
            X: Feature matrix (n_samples, n_features)
            y: Labels (0=NO wins, 1=YES wins)
            num_boost_round: Number of boosting rounds
            early_stopping_rounds: Early stopping patience
            eval_split: Fraction for validation

        Returns:
            Training metrics dict
        """
        import xgboost as xgb

        # Split data
        n_val = int(len(X) * eval_split)
        X_train, X_val = X[n_val:], X[:n_val]
        y_train, y_val = y[n_val:], y[:n_val]

        dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=self._feature_names)
        dval = xgb.DMatrix(X_val, label=y_val, feature_names=self._feature_names)

        params = {
            "objective": "binary:logistic",
            "eval_metric": ["logloss", "auc"],
            "max_depth": 6,
            "learning_rate": 0.05,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "min_child_weight": 5,
            "gamma": 0.1,
            "reg_alpha": 0.1,
            "reg_lambda": 1.0,
            "seed": 42,
        }

        evals_result: dict = {}
        self._model = xgb.train(
            params,
            dtrain,
            num_boost_round=num_boost_round,
            evals=[(dtrain, "train"), (dval, "val")],
            early_stopping_rounds=early_stopping_rounds,
            evals_result=evals_result,
            verbose_eval=False,
        )

        # Extract metrics
        metrics = {
            "train_logloss": evals_result["train"]["logloss"][-1],
            "val_logloss": evals_result["val"]["logloss"][-1],
            "val_auc": evals_result["val"]["auc"][-1],
            "best_iteration": self._model.best_iteration,
        }

        log.info("xgb_trained", **metrics)
        return metrics

    def save(self, path: str) -> None:
        """Save trained model to disk."""
        if self._model is None:
            raise ValueError("No model to save")
        with open(path, "wb") as f:
            pickle.dump(self._model, f)
        log.info("xgb_model_saved", path=path)

    def load(self, path: str) -> None:
        """Load trained model from disk."""
        with open(path, "rb") as f:
            self._model = pickle.load(f)
        log.info("xgb_model_loaded", path=path)

    def _build_prediction(self, prob_yes: float, features: MarketFeatures) -> Prediction:
        """Build a prediction from a probability estimate."""
        market_price = features.midpoint  # current market price as probability
        edge = prob_yes - market_price

        # Determine side: buy YES if our predicted prob > market price
        if edge > 0:
            side = "yes"
            confidence = min(prob_yes, 1.0)
        else:
            side = "no"
            confidence = min(1.0 - prob_yes, 1.0)

        return Prediction(
            side=side,
            confidence=confidence,
            predicted_prob=prob_yes,
            edge=edge,
            model_name=self.name,
            model_version=self.version,
        )

    def _heuristic_predict(self, features: MarketFeatures) -> Prediction:
        """
        Simple heuristic predictor when no trained model is available.

        Uses mean-reversion + momentum signals.
        """
        mid = features.midpoint
        signals: list[float] = []

        # Mean reversion: extreme prices tend to revert
        if mid < 0.15:
            signals.append(0.6)  # slight YES bias
        elif mid > 0.85:
            signals.append(0.4)  # slight NO bias
        else:
            signals.append(mid)

        # Momentum: recent price direction continues
        if features.price_change_5m > 0.02:
            signals.append(min(mid + 0.05, 0.95))
        elif features.price_change_5m < -0.02:
            signals.append(max(mid - 0.05, 0.05))
        else:
            signals.append(mid)

        # RSI: overbought/oversold
        if features.rsi_14 > 70:
            signals.append(max(mid - 0.03, 0.05))
        elif features.rsi_14 < 30:
            signals.append(min(mid + 0.03, 0.95))
        else:
            signals.append(mid)

        # Average signals
        prob_yes = sum(signals) / len(signals)
        return self._build_prediction(prob_yes, features)
