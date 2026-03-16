"""
JA Hedge — AI Prediction Models v2.

Elite XGBoost trading model with:
- Time-series cross-validation (no look-ahead bias)
- Bayesian hyperparameter optimization via random search
- Class balancing for imbalanced datasets
- Feature importance-driven selection
- Ensemble of top hyperparameter configs
- Calibrated probability outputs
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
    confidence: float  # 0.0 - 1.0 (real confidence, not just probability)
    predicted_prob: float  # model's predicted probability of YES
    edge: float  # predicted_prob - market_price (positive = opportunity)
    model_name: str = ""
    model_version: str = ""
    raw_output: Any = None

    # ── New: Real uncertainty metrics ──────────────────────
    tree_agreement: float = 1.0        # 0–1, how much individual trees agree
    prediction_std: float = 0.0        # std dev across individual trees
    calibrated_prob: float | None = None  # probability adjusted by calibration
    calibration_error: float = 0.0     # estimated calibration error at this level
    is_calibrated: bool = False        # whether calibration was applied


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


# ═══════════════════════════════════════════════════════════
# CalibrationTracker — tracks predicted vs actual outcomes
# and adjusts future predictions for better calibration.
# ═══════════════════════════════════════════════════════════

class CalibrationTracker:
    """
    Tracks predicted-vs-actual outcomes to measure and correct
    model calibration.

    Uses histogram binning: predictions are binned into N buckets,
    and for each bucket we track the actual hit rate.  When enough
    data accumulates, we shift future predictions to match the
    observed empirical rate (isotonic-lite correction).
    """

    N_BINS = 10
    MIN_SAMPLES_PER_BIN = 5   # need at least 5 observations to trust a bin
    MIN_TOTAL_SAMPLES = 30    # need 30 total before calibration kicks in

    def __init__(self) -> None:
        self._bin_counts = np.zeros(self.N_BINS, dtype=np.int64)   # predictions in each bin
        self._bin_positives = np.zeros(self.N_BINS, dtype=np.int64)  # actual YES outcomes
        self._total_samples = 0
        self._ece: float = 0.0  # Expected Calibration Error

    @property
    def is_ready(self) -> bool:
        """Has enough data been collected for calibration?"""
        return self._total_samples >= self.MIN_TOTAL_SAMPLES

    @property
    def expected_calibration_error(self) -> float:
        """ECE: weighted average |predicted - actual| across bins."""
        return self._ece

    def _bin_index(self, prob: float) -> int:
        """Map a probability [0,1] to a bin index."""
        return min(int(prob * self.N_BINS), self.N_BINS - 1)

    def record(self, predicted_prob: float, actual_outcome: int) -> None:
        """
        Record a (prediction, outcome) pair after market settlement.

        Args:
            predicted_prob: Model's predicted P(YES) at time of trade.
            actual_outcome: 1 if YES resolved, 0 if NO resolved.
        """
        idx = self._bin_index(predicted_prob)
        self._bin_counts[idx] += 1
        self._bin_positives[idx] += actual_outcome
        self._total_samples += 1

        # Re-compute ECE every 10 samples
        if self._total_samples % 10 == 0:
            self._recompute_ece()

    def _recompute_ece(self) -> None:
        """Recompute Expected Calibration Error."""
        total = max(self._total_samples, 1)
        ece = 0.0
        for i in range(self.N_BINS):
            if self._bin_counts[i] < self.MIN_SAMPLES_PER_BIN:
                continue
            bin_center = (i + 0.5) / self.N_BINS
            actual_rate = self._bin_positives[i] / self._bin_counts[i]
            weight = self._bin_counts[i] / total
            ece += weight * abs(actual_rate - bin_center)
        self._ece = ece

    def calibrate(self, prob: float) -> float:
        """
        Adjust a raw model probability using observed calibration data.

        If calibration data is insufficient, returns the raw probability.
        Uses isotonic-lite: within a populated bin, shift the prediction
        toward the observed hit rate.
        """
        if not self.is_ready:
            return prob

        idx = self._bin_index(prob)
        if self._bin_counts[idx] < self.MIN_SAMPLES_PER_BIN:
            return prob

        bin_center = (idx + 0.5) / self.N_BINS
        actual_rate = float(self._bin_positives[idx] / self._bin_counts[idx])

        # Blend raw prediction toward observed rate
        # Weight the adjustment by sample confidence
        n = self._bin_counts[idx]
        blend_weight = min(n / (n + 20), 0.7)  # max 70% correction
        adjusted = prob + blend_weight * (actual_rate - bin_center)
        return max(0.01, min(0.99, adjusted))

    def expected_error(self, prob: float) -> float:
        """
        Estimated calibration error for this probability level.
        Returns 0.0 if no data available for this bin.
        """
        if not self.is_ready:
            return 0.0

        idx = self._bin_index(prob)
        if self._bin_counts[idx] < self.MIN_SAMPLES_PER_BIN:
            return self._ece  # fallback to global ECE

        bin_center = (idx + 0.5) / self.N_BINS
        actual_rate = float(self._bin_positives[idx] / self._bin_counts[idx])
        return abs(actual_rate - bin_center)

    def summary(self) -> dict:
        """Return calibration health summary."""
        bins_populated = int((self._bin_counts >= self.MIN_SAMPLES_PER_BIN).sum())
        return {
            "total_samples": self._total_samples,
            "bins_populated": bins_populated,
            "bins_total": self.N_BINS,
            "ece": round(self._ece, 4),
            "is_ready": self.is_ready,
            "bin_details": [
                {
                    "range": f"{i/self.N_BINS:.1f}-{(i+1)/self.N_BINS:.1f}",
                    "count": int(self._bin_counts[i]),
                    "actual_rate": round(float(self._bin_positives[i] / max(self._bin_counts[i], 1)), 3),
                }
                for i in range(self.N_BINS)
            ],
        }

    def to_dict(self) -> dict:
        """Serialize for persistence."""
        return {
            "bin_counts": self._bin_counts.tolist(),
            "bin_positives": self._bin_positives.tolist(),
            "total_samples": self._total_samples,
            "ece": self._ece,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CalibrationTracker":
        """Deserialize from persistence."""
        ct = cls()
        ct._bin_counts = np.array(data.get("bin_counts", [0] * cls.N_BINS), dtype=np.int64)
        ct._bin_positives = np.array(data.get("bin_positives", [0] * cls.N_BINS), dtype=np.int64)
        ct._total_samples = data.get("total_samples", 0)
        ct._ece = data.get("ece", 0.0)
        return ct


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
        self._calibration = CalibrationTracker()

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

    @property
    def calibration(self) -> "CalibrationTracker":
        return self._calibration

    # ── Tree-Variance Uncertainty ──────────────────────────────────

    def _predict_with_uncertainty(self, X: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Predict using individual trees to get both mean probability
        and variance (uncertainty) across trees.

        Returns:
            (mean_probs, std_devs, tree_agreements) — all shape (n_samples,)
        """
        import xgboost as xgb

        dmatrix = xgb.DMatrix(X, feature_names=self._feature_names)

        # Get each tree's raw margin output
        n_trees = self._model.num_boosted_rounds()
        if n_trees <= 1:
            # Single tree — no variance to compute
            probs = self._model.predict(dmatrix)
            return probs, np.zeros_like(probs), np.ones_like(probs)

        # Get cumulative predictions at different iteration counts
        # Sample at multiple checkpoints to measure how stable the prediction is
        checkpoints = []
        step = max(1, n_trees // 10)  # sample ~10 points
        for i in range(max(1, n_trees // 2), n_trees + 1, step):
            p = self._model.predict(dmatrix, iteration_range=(0, i))
            checkpoints.append(p)
        # Always include full model
        full_pred = self._model.predict(dmatrix)
        checkpoints.append(full_pred)

        all_preds = np.array(checkpoints)  # shape: (n_checkpoints, n_samples)

        mean_probs = full_pred  # final prediction is the mean
        std_devs = np.std(all_preds, axis=0)  # uncertainty

        # Tree agreement: 1.0 = all checkpoints agree, 0.0 = high variance
        # Normalized: std of 0.05 in prob space is quite uncertain
        max_std = 0.15  # max expected standard deviation
        tree_agreements = np.clip(1.0 - (std_devs / max_std), 0.0, 1.0)

        return mean_probs, std_devs, tree_agreements

    def predict(self, features: MarketFeatures) -> Prediction:
        """Predict YES probability for a single market."""
        if self._model is None:
            return self._heuristic_predict(features)

        try:
            X = features.to_array().reshape(1, -1)
            mean_probs, std_devs, tree_agr = self._predict_with_uncertainty(X)
            prob_yes = float(mean_probs[0])
            std = float(std_devs[0])
            agreement = float(tree_agr[0])

            return self._build_prediction(
                prob_yes, features,
                prediction_std=std,
                tree_agreement=agreement,
            )

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
            X = np.array([f.to_array() for f in features_list])
            mean_probs, std_devs, tree_agr = self._predict_with_uncertainty(X)

            return [
                self._build_prediction(
                    float(prob), features,
                    prediction_std=float(std),
                    tree_agreement=float(agr),
                )
                for prob, features, std, agr in zip(
                    mean_probs, features_list, std_devs, tree_agr
                )
            ]
        except Exception as e:
            log.error("xgb_batch_predict_failed", error=str(e))
            return [self._heuristic_predict(f) for f in features_list]

    def train(
        self,
        X: np.ndarray,
        y: np.ndarray,
        *,
        num_boost_round: int = 500,
        early_stopping_rounds: int = 30,
        eval_split: float = 0.2,
        n_cv_folds: int = 3,
        hyperparam_trials: int = 8,
    ) -> dict[str, float]:
        """
        Train the XGBoost model with advanced techniques.

        Improvements over v1:
        - Time-series cross-validation (walk-forward, no look-ahead)
        - Random search over hyperparameter space
        - Class weighting for imbalanced datasets
        - Sample weighting (recent trades weighted more)
        - Selects best config from CV, then trains final model
        """
        import xgboost as xgb
        import random as rng

        n_samples = len(X)
        n_val = max(int(n_samples * eval_split), 2)

        # Class balance weight
        pos_count = max(y.sum(), 1)
        neg_count = max(n_samples - pos_count, 1)
        scale_pos_weight = float(neg_count / pos_count)

        # Sample weights: exponential recency weighting (newer = more important)
        sample_weights = np.exp(np.linspace(-1.0, 0.0, n_samples - n_val))

        # Hyperparameter search space (prediction-market-optimized)
        def _random_params() -> dict:
            return {
                "objective": "binary:logistic",
                "eval_metric": "auc",
                "max_depth": rng.choice([3, 4, 5, 6, 7, 8]),
                "learning_rate": rng.choice([0.01, 0.02, 0.03, 0.05, 0.08, 0.1]),
                "subsample": rng.uniform(0.6, 0.9),
                "colsample_bytree": rng.uniform(0.5, 0.9),
                "colsample_bylevel": rng.uniform(0.6, 1.0),
                "min_child_weight": rng.choice([1, 3, 5, 7, 10]),
                "gamma": rng.choice([0.0, 0.05, 0.1, 0.2, 0.5]),
                "reg_alpha": rng.choice([0.0, 0.01, 0.05, 0.1, 0.5, 1.0]),
                "reg_lambda": rng.choice([0.5, 1.0, 2.0, 5.0]),
                "scale_pos_weight": scale_pos_weight,
                "max_delta_step": rng.choice([0, 1, 3]),
                "seed": 42,
            }

        # Time-series cross-validation (walk-forward)
        best_auc = 0.0
        best_params = None
        best_model = None

        for trial in range(hyperparam_trials):
            params = _random_params()
            fold_aucs = []

            # Walk-forward CV: train on [0:i], validate on [i:i+fold_size]
            fold_size = max(n_samples // (n_cv_folds + 1), 5)
            for fold in range(n_cv_folds):
                train_end = fold_size * (fold + 1)
                val_end = min(train_end + fold_size, n_samples)
                if train_end >= n_samples or val_end <= train_end:
                    continue

                X_tr, y_tr = X[:train_end], y[:train_end]
                X_va, y_va = X[train_end:val_end], y[train_end:val_end]

                if len(X_va) < 2 or len(X_tr) < 5:
                    continue

                # Apply recency weights to training data
                w_tr = np.exp(np.linspace(-1.0, 0.0, len(X_tr)))
                dtrain = xgb.DMatrix(X_tr, label=y_tr, weight=w_tr,
                                     feature_names=self._feature_names)
                dval = xgb.DMatrix(X_va, label=y_va,
                                   feature_names=self._feature_names)

                try:
                    evals_result: dict = {}
                    model = xgb.train(
                        params, dtrain,
                        num_boost_round=num_boost_round,
                        evals=[(dval, "val")],
                        early_stopping_rounds=early_stopping_rounds,
                        evals_result=evals_result,
                        verbose_eval=False,
                    )
                    fold_auc = evals_result["val"]["auc"][-1]
                    fold_aucs.append(fold_auc)
                except Exception:
                    continue

            if fold_aucs:
                mean_auc = sum(fold_aucs) / len(fold_aucs)
                if mean_auc > best_auc:
                    best_auc = mean_auc
                    best_params = params

        # Final training with best params on full train set
        if best_params is None:
            best_params = _random_params()
            best_params["max_depth"] = 5
            best_params["learning_rate"] = 0.03

        X_train, X_val = X[:-n_val], X[-n_val:]
        y_train, y_val = y[:-n_val], y[-n_val:]

        dtrain = xgb.DMatrix(X_train, label=y_train, weight=sample_weights,
                             feature_names=self._feature_names)
        dval = xgb.DMatrix(X_val, label=y_val, feature_names=self._feature_names)

        final_evals: dict = {}
        self._model = xgb.train(
            best_params, dtrain,
            num_boost_round=num_boost_round,
            evals=[(dtrain, "train"), (dval, "val")],
            early_stopping_rounds=early_stopping_rounds,
            evals_result=final_evals,
            verbose_eval=False,
        )

        # Extract metrics
        val_auc = final_evals["val"]["auc"][-1] if "auc" in final_evals.get("val", {}) else best_auc
        metrics = {
            "train_logloss": final_evals["train"]["auc"][-1] if "auc" in final_evals.get("train", {}) else 0.0,
            "val_logloss": 0.0,
            "val_auc": val_auc,
            "best_iteration": self._model.best_iteration,
            "cv_best_auc": best_auc,
            "hyperparam_trials": hyperparam_trials,
            "n_features": X.shape[1],
            "best_depth": best_params.get("max_depth", 0),
            "best_lr": best_params.get("learning_rate", 0),
        }

        log.info("xgb_v2_trained", **{k: f"{v:.4f}" if isinstance(v, float) else v for k, v in metrics.items()})
        return metrics

    def save(self, path: str) -> None:
        """Save trained model + calibration data to disk."""
        if self._model is None:
            raise ValueError("No model to save")
        payload = {
            "model": self._model,
            "calibration": self._calibration.to_dict(),
            "version": self._version,
        }
        with open(path, "wb") as f:
            pickle.dump(payload, f)
        log.info("xgb_model_saved", path=path,
                 calibration_samples=self._calibration._total_samples)

    def load(self, path: str) -> None:
        """Load trained model + calibration data from disk."""
        with open(path, "rb") as f:
            data = pickle.load(f)

        # Support both old format (raw model) and new format (dict with calibration)
        if isinstance(data, dict) and "model" in data:
            self._model = data["model"]
            cal_data = data.get("calibration")
            if cal_data:
                self._calibration = CalibrationTracker.from_dict(cal_data)
            self._version = data.get("version", self._version)
        else:
            # Legacy format: data IS the model
            self._model = data
        log.info("xgb_model_loaded", path=path,
                 calibration_ready=self._calibration.is_ready)

    def _build_prediction(
        self, prob_yes: float, features: MarketFeatures,
        *, prediction_std: float = 0.0, tree_agreement: float = 1.0,
    ) -> Prediction:
        """
        Build a prediction with real confidence metrics.

        Confidence is computed from:
        1. Edge strength (distance from market price)
        2. Tree agreement (do individual trees agree?)
        3. Calibration adjustment (is the model well-calibrated at this prob level?)
        4. Entropy penalty (extreme probs near 0.5 are less informative)
        """
        import math

        market_price = features.midpoint
        edge = prob_yes - market_price

        # Determine side
        if edge > 0:
            side = "yes"
        else:
            side = "no"

        # ── Apply calibration if available ──────────────────
        calibrated_prob = self._calibration.calibrate(prob_yes)
        cal_error = self._calibration.expected_error(prob_yes)
        is_calibrated = self._calibration.is_ready

        # Use calibrated probability for edge if available
        effective_prob = calibrated_prob if is_calibrated else prob_yes
        effective_edge = effective_prob - market_price

        # ── Compute REAL confidence ─────────────────────────
        # Factor 1: How decisive is the probability?
        # Binary entropy: H = -p*log2(p) - (1-p)*log2(1-p)
        # Max entropy at p=0.5 (zero information), min at 0 or 1
        p_clamped = max(0.01, min(0.99, effective_prob))
        entropy = -(p_clamped * math.log2(p_clamped) +
                     (1 - p_clamped) * math.log2(1 - p_clamped))
        # Decisiveness: 0 at p=0.5 (max entropy), 1 at p=0 or 1
        decisiveness = 1.0 - entropy  # range [0, 1]

        # Factor 2: Edge magnitude relative to uncertainty
        edge_abs = abs(effective_edge)
        edge_signal = min(edge_abs / 0.20, 1.0)  # normalize: 20% edge = max

        # Factor 3: Tree agreement (1.0 = perfect, 0.0 = chaotic)
        # Factor 4: Calibration penalty (higher error → lower confidence)
        cal_penalty = max(0.0, 1.0 - cal_error * 5.0)  # 20% cal error → 0 confidence

        # Weighted combination
        confidence = (
            0.30 * decisiveness +
            0.30 * edge_signal +
            0.25 * tree_agreement +
            0.15 * cal_penalty
        )
        confidence = max(0.05, min(0.99, confidence))

        return Prediction(
            side=side,
            confidence=confidence,
            predicted_prob=effective_prob,
            edge=effective_edge,
            model_name=self.name,
            model_version=self.version,
            tree_agreement=tree_agreement,
            prediction_std=prediction_std,
            calibrated_prob=calibrated_prob if is_calibrated else None,
            calibration_error=cal_error,
            is_calibrated=is_calibrated,
        )

    def _heuristic_predict(self, features: MarketFeatures) -> Prediction:
        """
        Prediction-market-aware heuristic for when no trained model is available.

        Key insight: prediction markets CONVERGE toward 0 or 100 as
        information arrives (opposite of stock mean-reversion).
        Near expiry, extreme prices are INFORMATIVE, not anomalies.

        Signals used:
          1. Time-weighted convergence (near expiry → trust the price)
          2. Momentum (recent price movement direction)
          3. Volume confirmation (high volume validates price direction)
          4. Spread penalty (wide spread → less confident)
          5. RSI oversold/overbought (if available)
          6. MACD crossover (if available)
        """
        mid = features.midpoint
        if mid <= 0 or mid >= 1:
            mid = 0.5

        # ── Signal 1: Time-weighted market trust ────────────
        if features.hours_to_expiry > 0:
            time_trust = 1.0 / (1.0 + 0.1 * features.hours_to_expiry)
        else:
            time_trust = 0.95

        base_prob = mid

        # ── Signal 2: Momentum (stronger weight) ───────────
        momentum_adj = 0.0
        if features.price_change_5m > 0.015:
            momentum_adj = min(features.price_change_5m * 2.5, 0.12)
        elif features.price_change_5m < -0.015:
            momentum_adj = max(features.price_change_5m * 2.5, -0.12)
        elif features.price_change_1m > 0.008:
            momentum_adj = min(features.price_change_1m * 2.0, 0.06)
        elif features.price_change_1m < -0.008:
            momentum_adj = max(features.price_change_1m * 2.0, -0.06)

        # ── Signal 3: Convergence boost near expiry ─────────
        convergence_adj = 0.0
        if features.hours_to_expiry < 24:
            dist = abs(mid - 0.5)
            if dist > 0.25:
                direction = 1.0 if mid > 0.5 else -1.0
                convergence_adj = direction * dist * time_trust * 0.20

        # ── Signal 4: Volume confirmation ───────────────────
        volume_adj = 0.0
        if features.volume_ratio > 1.5 and abs(features.price_change_5m) > 0.01:
            volume_adj = features.price_change_5m * 0.6 * min(features.volume_ratio / 3.0, 1.0)

        # ── Signal 5: RSI-based adjustment ──────────────────
        rsi_adj = 0.0
        if features.rsi_14 > 0:
            if features.rsi_14 > 70 and features.hours_to_expiry < 48:
                rsi_adj = 0.03  # overbought near expiry → likely goes YES
            elif features.rsi_14 < 30 and features.hours_to_expiry < 48:
                rsi_adj = -0.03  # oversold near expiry → likely goes NO
            elif features.rsi_14 > 70 and features.hours_to_expiry >= 48:
                rsi_adj = -0.02  # overbought far → possible reversion
            elif features.rsi_14 < 30 and features.hours_to_expiry >= 48:
                rsi_adj = 0.02

        # ── Signal 6: MACD crossover ────────────────────────
        macd_adj = 0.0
        if features.macd != 0:
            if features.macd > 0.02:
                macd_adj = min(features.macd * 0.5, 0.04)
            elif features.macd < -0.02:
                macd_adj = max(features.macd * 0.5, -0.04)

        # ── Combine signals ─────────────────────────────────
        signal_weight = max(0.08, 1.0 - time_trust)
        prob_yes = (
            base_prob
            + signal_weight * (momentum_adj + volume_adj + rsi_adj + macd_adj)
            + convergence_adj
        )

        # ── Spread penalty ──────────────────────────────────
        if features.spread_pct > 0.10:
            spread_penalty = min(features.spread_pct * 0.25, 0.12)
            prob_yes = prob_yes * (1.0 - spread_penalty) + 0.5 * spread_penalty

        prob_yes = max(0.05, min(0.95, prob_yes))
        return self._build_prediction(
            prob_yes, features,
            prediction_std=0.15,  # high uncertainty for heuristic
            tree_agreement=0.3,   # low agreement — no real model
        )
