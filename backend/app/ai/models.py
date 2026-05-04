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
    raw_prob: float = 0.0              # pre-calibration model probability (for calibration feedback)
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

    Uses 20-bin histogram with isotonic monotonicity enforcement.
    More bins = finer calibration, which matters when the typical
    edge is only 5-10%.  After enough samples, the calibration map
    is forced to be monotonically non-decreasing (isotonic) so that
    higher predicted probabilities always map to higher calibrated ones.

    Phase 8: Exponential recency decay — older observations fade so
    calibration adapts as the model is retrained or market dynamics shift.
    Every DECAY_INTERVAL new samples, all bins are decayed by DECAY_FACTOR.
    """

    N_BINS = 20               # 5pp granularity (was 10 → 10pp, too coarse)
    MIN_SAMPLES_PER_BIN = 3   # need at least 3 observations to trust a bin
    MIN_TOTAL_SAMPLES = 30    # need 30 total before calibration kicks in
    DECAY_FACTOR = 0.95       # multiply all bins by this on decay
    DECAY_INTERVAL = 50       # decay every 50 new samples

    def __init__(self) -> None:
        # Use float arrays so decay works smoothly
        self._bin_counts = np.zeros(self.N_BINS, dtype=np.float64)
        self._bin_positives = np.zeros(self.N_BINS, dtype=np.float64)
        self._bin_pred_sum = np.zeros(self.N_BINS, dtype=np.float64)
        self._total_samples = 0
        self._samples_since_decay = 0
        self._ece: float = 0.0
        # Isotonic calibration map: bin_index → calibrated probability
        self._isotonic_map: np.ndarray | None = None

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
        self._bin_pred_sum[idx] += predicted_prob
        self._total_samples += 1
        self._samples_since_decay += 1

        # Phase 8: Recency decay — fade old observations
        if self._samples_since_decay >= self.DECAY_INTERVAL:
            self._bin_counts *= self.DECAY_FACTOR
            self._bin_positives *= self.DECAY_FACTOR
            self._bin_pred_sum *= self.DECAY_FACTOR
            self._samples_since_decay = 0

        # Re-compute ECE and isotonic map every 10 samples
        if self._total_samples % 10 == 0:
            self._recompute_ece()
            self._recompute_isotonic()

    def _recompute_ece(self) -> None:
        """Recompute Expected Calibration Error."""
        total = max(self._total_samples, 1)
        ece = 0.0
        for i in range(self.N_BINS):
            if self._bin_counts[i] < self.MIN_SAMPLES_PER_BIN:
                continue
            avg_pred = self._bin_pred_sum[i] / self._bin_counts[i]
            actual_rate = self._bin_positives[i] / self._bin_counts[i]
            weight = self._bin_counts[i] / total
            ece += weight * abs(actual_rate - avg_pred)
        self._ece = ece

    def _recompute_isotonic(self) -> None:
        """Build isotonic (monotonically non-decreasing) calibration map.

        Pool-Adjacent-Violators (PAV) algorithm — O(N_BINS) and
        guarantees monotonicity without needing sklearn.
        """
        raw_rates = np.full(self.N_BINS, np.nan)
        for i in range(self.N_BINS):
            if self._bin_counts[i] >= self.MIN_SAMPLES_PER_BIN:
                raw_rates[i] = self._bin_positives[i] / self._bin_counts[i]

        # Forward-fill NaN bins from neighbors
        filled = raw_rates.copy()
        last_valid = 0.0
        for i in range(self.N_BINS):
            if not np.isnan(filled[i]):
                last_valid = filled[i]
            else:
                filled[i] = last_valid

        # PAV: enforce monotonicity
        iso = filled.copy()
        i = 0
        while i < self.N_BINS:
            j = i
            # Find block that needs averaging
            while j < self.N_BINS - 1 and iso[j] > iso[j + 1]:
                j += 1
            if j > i:
                # Average the block to make it monotone
                block_avg = np.mean(iso[i:j + 1])
                iso[i:j + 1] = block_avg
            i = j + 1

        self._isotonic_map = iso

    def calibrate(self, prob: float) -> float:
        """
        Adjust a raw model probability using isotonic calibration.

        Uses the precomputed isotonic map for monotone correction,
        with linear interpolation between bin centers.
        """
        if not self.is_ready:
            return prob

        # Use isotonic map if available
        if self._isotonic_map is not None:
            idx = self._bin_index(prob)
            # Linear interpolation between adjacent bins
            bin_center = (idx + 0.5) / self.N_BINS
            if idx < self.N_BINS - 1:
                next_center = (idx + 1.5) / self.N_BINS
                t = (prob - bin_center) / (next_center - bin_center)
                t = max(0.0, min(1.0, t))
                adjusted = self._isotonic_map[idx] * (1 - t) + self._isotonic_map[idx + 1] * t
            else:
                adjusted = float(self._isotonic_map[idx])
            return max(0.01, min(0.99, adjusted))

        # Fallback to per-bin blending
        idx = self._bin_index(prob)
        if self._bin_counts[idx] < self.MIN_SAMPLES_PER_BIN:
            return prob

        actual_rate = float(self._bin_positives[idx] / self._bin_counts[idx])
        n = self._bin_counts[idx]
        blend_weight = min(n / (n + 20), 0.7)
        adjusted = prob + blend_weight * (actual_rate - prob)
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

        avg_pred = float(self._bin_pred_sum[idx] / self._bin_counts[idx])
        actual_rate = float(self._bin_positives[idx] / self._bin_counts[idx])
        return abs(actual_rate - avg_pred)

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

    def reset(self) -> None:
        """Phase 31: Reset all calibration data.

        Called when bootstrap data is purged to prevent stale calibration
        from poisoned training samples (e.g., 500 crypto bootstrap trades
        with 0% real accuracy).
        """
        self._bin_counts = np.zeros(self.N_BINS, dtype=np.float64)
        self._bin_positives = np.zeros(self.N_BINS, dtype=np.float64)
        self._bin_pred_sum = np.zeros(self.N_BINS, dtype=np.float64)
        self._total_samples = 0
        self._samples_since_decay = 0
        self._ece = 0.0
        self._isotonic_map = None

    def to_dict(self) -> dict:
        """Serialize for persistence."""
        return {
            "bin_counts": self._bin_counts.tolist(),
            "bin_positives": self._bin_positives.tolist(),
            "bin_pred_sum": self._bin_pred_sum.tolist(),
            "total_samples": self._total_samples,
            "ece": self._ece,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CalibrationTracker":
        """Deserialize from persistence."""
        ct = cls()
        ct._bin_counts = np.array(data.get("bin_counts", [0] * cls.N_BINS), dtype=np.int64)
        ct._bin_positives = np.array(data.get("bin_positives", [0] * cls.N_BINS), dtype=np.int64)
        ct._bin_pred_sum = np.array(data.get("bin_pred_sum", [0.0] * cls.N_BINS), dtype=np.float64)
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
        self._train_samples: int = 0  # Phase 14: for ensemble blend weight

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

        # Phase 23+24b: Handle feature schema evolution robustly.
        # If model was trained with fewer features, trim both X and names.
        # Also handle pruned models where num_features < len(feature_names).
        try:
            model_n_features = self._model.num_features()
        except (AttributeError, TypeError):
            model_n_features = X.shape[1]

        feat_names = self._feature_names
        if X.shape[1] > model_n_features:
            X = X[:, :model_n_features]
            feat_names = self._feature_names[:model_n_features]
        elif X.shape[1] < model_n_features:
            # Pad with zeros if current features are somehow fewer
            pad = np.zeros((X.shape[0], model_n_features - X.shape[1]))
            X = np.hstack([X, pad])

        # Ensure feature name count matches X columns
        if len(feat_names) != X.shape[1]:
            feat_names = feat_names[:X.shape[1]] if len(feat_names) > X.shape[1] \
                else feat_names + [f"f{i}" for i in range(len(feat_names), X.shape[1])]

        # Use model's stored feature names if available, to avoid name conflicts
        try:
            model_feat_names = self._model.feature_names
            if model_feat_names and len(model_feat_names) == X.shape[1]:
                feat_names = model_feat_names
        except (AttributeError, TypeError):
            pass

        dmatrix = xgb.DMatrix(X, feature_names=feat_names)

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
        last_checkpoint_iter = 0
        for i in range(max(1, n_trees // 2), n_trees + 1, step):
            p = self._model.predict(dmatrix, iteration_range=(0, i))
            checkpoints.append(p)
            last_checkpoint_iter = i
        # Include full model prediction only if not already the last checkpoint
        full_pred = self._model.predict(dmatrix)
        if last_checkpoint_iter != n_trees:
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
        """Predict YES probability for a single market.

        Phase 14: Ensemble — blend ML output with heuristic baseline.
        When young (few training samples), the heuristic anchors us
        to market price.  As data grows, the ML model dominates.
        """
        if self._model is None:
            return self._heuristic_predict(features)

        try:
            X = features.to_array().reshape(1, -1)
            mean_probs, std_devs, tree_agr = self._predict_with_uncertainty(X)
            prob_yes = float(mean_probs[0])
            std = float(std_devs[0])
            agreement = float(tree_agr[0])

            # Phase 25: Ensemble blending — ML weight curve fix.
            # OLD: started at 0.70 with 0 training samples → model had
            # 70% weight immediately → garbage predictions dominated.
            # NEW: starts at 0.30 (market price dominates) and ramps to
            # 0.92 at 500+ samples.  The market price IS the best
            # estimator until we have enough data to beat it.
            n_trained = getattr(self, '_train_samples', 0)
            ml_weight = min(0.92, 0.30 + n_trained / 500.0)
            heuristic_prob = features.midpoint  # market price is the heuristic baseline

            blended_prob = ml_weight * prob_yes + (1.0 - ml_weight) * heuristic_prob
            blended_prob = max(0.01, min(0.99, blended_prob))

            return self._build_prediction(
                blended_prob, features,
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
        sample_weights: np.ndarray | None = None,
    ) -> dict[str, float]:
        """
        Train the XGBoost model with advanced techniques.

        Args:
            sample_weights: Optional per-sample weights from memory (recency +
                correctness).  If provided, these are used instead of the default
                index-based exponential decay.  Shape must be (n_samples,).
        """
        import xgboost as xgb
        import random as rng

        n_samples = len(X)
        n_val = max(int(n_samples * eval_split), 2)

        # Phase 24b: Reconcile feature names with actual X dimensions.
        # Training data may have different feature count than current schema
        # (e.g., bootstrap data from pre-Phase-23 has 66, current has 83).
        train_feat_names = self._feature_names
        if X.shape[1] != len(train_feat_names):
            if X.shape[1] < len(train_feat_names):
                train_feat_names = train_feat_names[:X.shape[1]]
            else:
                train_feat_names = train_feat_names + [
                    f"f{i}" for i in range(len(train_feat_names), X.shape[1])
                ]
            log.info("feature_names_reconciled",
                     expected=len(self._feature_names), actual=X.shape[1],
                     using=len(train_feat_names))

        # Class balance weight
        pos_count = max(y.sum(), 1)
        neg_count = max(n_samples - pos_count, 1)
        scale_pos_weight = float(neg_count / pos_count)

        # Sample weights: use external weights if provided, else fall back
        # to naive exponential recency (index-based).
        if sample_weights is not None and len(sample_weights) == n_samples:
            _all_weights = sample_weights
        else:
            _all_weights = np.exp(np.linspace(-1.0, 0.0, n_samples))

        # Split weights for train/val like we split X/y
        _train_weights = _all_weights[:n_samples - n_val]

        # Hyperparameter search space (prediction-market-optimized)
        # Phase 25: Stronger regularization for small datasets (<200 samples).
        # With few samples, overfitting is the #1 risk.  We use:
        #   - Very shallow trees (2-4 depth)
        #   - Aggressive regularization (high gamma, lambda, alpha)
        #   - Low learning rate with more boosting rounds
        #   - High min_child_weight to prevent rare splits
        _is_small_data = n_samples < 200
        def _random_params() -> dict:
            if _is_small_data:
                return {
                    "objective": "binary:logistic",
                    "eval_metric": ["logloss", "auc"],
                    "max_depth": rng.choice([2, 3, 4]),
                    "learning_rate": rng.choice([0.005, 0.01, 0.02, 0.03]),
                    "subsample": rng.uniform(0.5, 0.75),
                    "colsample_bytree": rng.uniform(0.4, 0.7),
                    "colsample_bylevel": rng.uniform(0.5, 0.8),
                    "min_child_weight": rng.choice([10, 15, 20, 30]),
                    "gamma": rng.choice([0.5, 1.0, 2.0, 3.0]),
                    "reg_alpha": rng.choice([0.5, 1.0, 2.0, 5.0]),
                    "reg_lambda": rng.choice([5.0, 10.0, 20.0, 50.0]),
                    "scale_pos_weight": scale_pos_weight,
                    "max_delta_step": rng.choice([1, 3, 5]),
                    "seed": 42,
                }
            return {
                "objective": "binary:logistic",
                "eval_metric": ["logloss", "auc"],
                "max_depth": rng.choice([3, 4, 5, 6]),
                "learning_rate": rng.choice([0.01, 0.02, 0.03, 0.05]),
                "subsample": rng.uniform(0.6, 0.85),
                "colsample_bytree": rng.uniform(0.5, 0.85),
                "colsample_bylevel": rng.uniform(0.6, 0.95),
                "min_child_weight": rng.choice([3, 5, 7, 10, 15]),
                "gamma": rng.choice([0.1, 0.2, 0.5, 1.0]),
                "reg_alpha": rng.choice([0.01, 0.1, 0.5, 1.0, 2.0]),
                "reg_lambda": rng.choice([1.0, 2.0, 5.0, 10.0]),
                "scale_pos_weight": scale_pos_weight,
                "max_delta_step": rng.choice([1, 3, 5]),
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

                # Use the real sample weights for this fold's training slice
                w_tr = _all_weights[:train_end]
                dtrain = xgb.DMatrix(X_tr, label=y_tr, weight=w_tr,
                                     feature_names=train_feat_names)
                dval = xgb.DMatrix(X_va, label=y_va,
                                   feature_names=train_feat_names)

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
                    # eval_metric is ["logloss", "auc"] — use AUC for comparison
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
            best_params["max_depth"] = 4
            best_params["learning_rate"] = 0.03
            best_params["min_child_weight"] = 7
            best_params["gamma"] = 0.5
            best_params["reg_lambda"] = 5.0

        X_train, X_val = X[:-n_val], X[-n_val:]
        y_train, y_val = y[:-n_val], y[-n_val:]

        dtrain = xgb.DMatrix(X_train, label=y_train, weight=_train_weights,
                             feature_names=train_feat_names)
        dval = xgb.DMatrix(X_val, label=y_val, feature_names=train_feat_names)

        final_evals: dict = {}
        self._model = xgb.train(
            best_params, dtrain,
            num_boost_round=num_boost_round,
            evals=[(dtrain, "train"), (dval, "val")],
            early_stopping_rounds=early_stopping_rounds,
            evals_result=final_evals,
            verbose_eval=False,
        )

        # Phase 14: Track sample count for ensemble blending weight
        self._train_samples = n_samples

        # Extract metrics
        val_auc = final_evals["val"]["auc"][-1] if "auc" in final_evals.get("val", {}) else best_auc
        train_auc = final_evals["train"]["auc"][-1] if "auc" in final_evals.get("train", {}) else 0.0
        metrics = {
            "train_auc": train_auc,
            "val_auc": val_auc,
            "best_iteration": self._model.best_iteration,
            "cv_best_auc": best_auc,
            "hyperparam_trials": hyperparam_trials,
            "n_features": X.shape[1],
            "best_depth": best_params.get("max_depth", 0),
            "best_lr": best_params.get("learning_rate", 0),
        }

        # Track feature importance for monitoring
        try:
            importance = self._model.get_score(importance_type="gain")
            total_imp = sum(importance.values()) or 1.0
            top_feats = sorted(importance.items(), key=lambda x: x[1], reverse=True)[:10]
            metrics["top_features"] = {k: round(v / total_imp, 4) for k, v in top_feats}
            metrics["features_used"] = len(importance)
            metrics["features_total"] = X.shape[1]
            # Detect leakage: if any single feature has >30% importance, flag it
            if top_feats and (top_feats[0][1] / total_imp) > 0.30:
                log.warning(
                    "⚠️ POSSIBLE FEATURE LEAKAGE",
                    feature=top_feats[0][0],
                    importance=f"{top_feats[0][1] / total_imp:.1%}",
                )
                metrics["leakage_warning"] = top_feats[0][0]
        except Exception:
            pass

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

        # Phase 14: require a MINIMUM decisive edge to commit to a non-neutral
        # side. Below this threshold, the prediction is effectively noise and
        # will be filtered out by the scanner's min_edge gate anyway. We default
        # to 'no' (the rare side in our data) so any leakage doesn't reinforce
        # the historical YES bias.
        MIN_DECISIVE_EDGE = 0.005  # 0.5¢ — below this is signal noise
        if abs(edge) < MIN_DECISIVE_EDGE:
            side = "no"
        elif edge > 0:
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
        # Factor 1: Decisiveness — how far our prediction diverges
        # from the MARKET PRICE, not from 0.5.  A market at 8¢ is
        # "decisive" by entropy but that's just the market structure,
        # not our model's insight.  We only get credit for divergence
        # from what the market already knows.
        divergence = abs(effective_prob - market_price)
        # Normalize: 10% divergence from market = reasonably decisive
        decisiveness = min(divergence / 0.15, 1.0)

        # Factor 2: Edge magnitude relative to uncertainty
        # Cap at 15% — any edge above that is almost certainly wrong
        edge_abs = min(abs(effective_edge), 0.15)
        edge_signal = edge_abs / 0.15  # normalize: 15% edge = max

        # Factor 3: Tree agreement (1.0 = perfect, 0.0 = chaotic)
        # Factor 4: Calibration penalty (higher error → lower confidence)
        cal_penalty = max(0.0, 1.0 - cal_error * 5.0)  # 20% cal error → 0 confidence

        # Factor 5: Price-range penalty — extreme prices (< 15¢ or > 85¢)
        # are inherently harder to predict and have asymmetric payoffs.
        price_penalty = 1.0
        if market_price < 0.15 or market_price > 0.85:
            price_penalty = 0.5  # halve confidence for extreme prices
        elif market_price < 0.25 or market_price > 0.75:
            price_penalty = 0.75

        # Weighted combination
        confidence = (
            0.25 * decisiveness +
            0.25 * edge_signal +
            0.20 * tree_agreement +
            0.10 * cal_penalty +
            0.20 * price_penalty
        )
        confidence = max(0.05, min(0.99, confidence))

        return Prediction(
            side=side,
            confidence=confidence,
            raw_prob=prob_yes,            # pre-calibration probability (for calibration feedback)
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
        Heuristic prediction for when no trained model is available.

        Phase 14 (Dec 2025): COMPLETE REWRITE to kill structural YES bias.

        Root cause of prior YES bias: stacked 9 small adjustments
        (convergence_adj, RSI, MACD, momentum, volume) that all sum to a
        slightly positive number on average — and convergence_adj specifically
        pushed high-mid markets *further* toward YES. Combined with Kalshi's
        market population skewing mid > 0.5 (most binary questions are framed
        such that YES is the more likely outcome at most price points), the
        heuristic produced ~95% YES trades.

        NEW PRINCIPLE: "Shut up if you don't know."
        - With ALT-DATA (Polymarket/Vegas/crypto/sentiment): use it as the
          primary signal — that's real external information.
        - Without alt-data: prob_yes = mid → edge = 0 → trade is filtered
          out by the min_edge gate. No spurious signals from technical noise.
        - Optional: a tiny convergence nudge in the LAST hour ONLY, applied
          symmetrically (so high and low mids are treated identically).
        - Optional: side-balance prior — if recent bot trades skew heavily
          one side, slightly bias the prob away from the dominant side to
          help the gate find counter-side opportunities.
        """
        mid = features.midpoint
        if mid <= 0 or mid >= 1:
            mid = 0.5

        base_prob = mid
        total_adjustment = 0.0
        alt_data_signals = 0  # count of real external signals firing

        # ── Signal A: Cross-platform edge (Polymarket / Vegas) ──────────
        # This is the STRONGEST real signal — another deep market disagrees.
        if getattr(features, 'alt_polymarket_prob', 0.0) > 0:
            poly_diff = features.alt_polymarket_prob - mid
            adj = max(-0.08, min(0.08, poly_diff * 0.40))
            total_adjustment += adj
            alt_data_signals += 1
        elif getattr(features, 'alt_vegas_prob', 0.0) > 0:
            vegas_diff = features.alt_vegas_prob - mid
            adj = max(-0.07, min(0.07, vegas_diff * 0.35))
            total_adjustment += adj
            alt_data_signals += 1

        # ── Signal B: Crypto distance from strike ───────────────────────
        crypto_dist = getattr(features, 'alt_crypto_strike_dist', 0.0)
        if crypto_dist and abs(crypto_dist) > 0.02:
            adj = max(-0.06, min(0.06, crypto_dist * 0.15))
            total_adjustment += adj
            alt_data_signals += 1

        # ── Signal C: News + social sentiment ───────────────────────────
        news_sent = getattr(features, 'alt_news_sentiment', 0.0) or 0.0
        soc_sent = getattr(features, 'alt_social_sentiment', 0.0) or 0.0
        sent_adj = news_sent * 0.02 + soc_sent * 0.015
        sent_adj = max(-0.03, min(0.03, sent_adj))
        if abs(sent_adj) > 0.001:
            total_adjustment += sent_adj
            alt_data_signals += 1

        # ── Signal D: Symmetric near-expiry convergence (LAST HOUR ONLY) ─
        # Tiny nudge toward whichever side is dominant, but only when there's
        # essentially no time left and the market has already committed.
        # CRITICAL: applied identically for mid > 0.5 and mid < 0.5 — no
        # population skew can leak through.
        if features.hours_to_expiry < 1.0 and features.hours_to_expiry > 0:
            dist = abs(mid - 0.5)
            if dist > 0.30:  # market is at >80% or <20%
                direction = 1.0 if mid > 0.5 else -1.0
                # Strictly symmetric magnitude
                total_adjustment += direction * 0.02

        # ── Signal E: Side-balance prior ────────────────────────────────
        # If the bot has been trading one side too heavily recently,
        # subtract a small bias from that side to help the scanner find
        # counter-opportunities. This is a SOFT prior, not a hard gate.
        sb_nudge = self._side_balance_prior()
        if sb_nudge != 0.0:
            total_adjustment += sb_nudge

        # Hard cap total adjustment
        total_adjustment = max(-0.12, min(0.12, total_adjustment))
        prob_yes = base_prob + total_adjustment

        # Wide-spread penalty (pull toward 0.5 if spread is huge)
        if features.spread_pct > 0.10:
            spread_penalty = min(features.spread_pct * 0.15, 0.06)
            prob_yes = prob_yes * (1.0 - spread_penalty) + 0.5 * spread_penalty

        prob_yes = max(0.05, min(0.95, prob_yes))

        # Confidence reflects whether we had real data to work with.
        # No alt-data → very low confidence → trade likely fails edge gate.
        if alt_data_signals >= 2:
            _std, _agreement = 0.06, 0.65
        elif alt_data_signals == 1:
            _std, _agreement = 0.10, 0.50
        else:
            _std, _agreement = 0.20, 0.20  # essentially no signal

        pred = self._build_prediction(
            prob_yes, features,
            prediction_std=_std,
            tree_agreement=_agreement,
        )
        pred.raw_prob = prob_yes
        return pred

    # ── Side-balance feedback hook (Phase 14) ───────────────────────────
    # The predictor reads the global Frankenstein memory (if available) to
    # learn its own bias and counter it. Set by main.py on startup.
    _memory_ref: Any = None

    @classmethod
    def attach_memory(cls, memory: Any) -> None:
        """Inject Frankenstein.memory so heuristic can self-correct side bias."""
        cls._memory_ref = memory

    def _side_balance_prior(self) -> float:
        """Return a small adjustment to prob_yes that counters recent side bias.

        - If recent bot trades are >70% YES → subtract up to 0.04 (push toward NO)
        - If recent bot trades are >70% NO  → add up to 0.04 (push toward YES)
        - Else 0.
        Soft prior — a partner to the scanner's hard gate.
        """
        try:
            mem = self.__class__._memory_ref
            if mem is None:
                return 0.0
            trades = getattr(mem, '_trades', None)
            if not trades:
                return 0.0
            recent = list(trades)[-50:]
            buys = [t for t in recent if getattr(t, 'action', '') == 'buy'
                    and getattr(t, 'predicted_side', None) in ('yes', 'no')]
            if len(buys) < 20:
                return 0.0
            yes_count = sum(1 for t in buys if t.predicted_side == 'yes')
            yes_ratio = yes_count / len(buys)
            # Symmetric: imbalance above 0.5 in either direction → counter-nudge
            imbalance = yes_ratio - 0.5  # +0.5 = all YES, -0.5 = all NO
            if abs(imbalance) < 0.20:  # 30%/70% threshold
                return 0.0
            # Counter-bias: scale linearly past the threshold, cap at 4%
            excess = (abs(imbalance) - 0.20) / 0.30  # 0..1 over [0.20..0.50]
            magnitude = min(0.04, excess * 0.04)
            return -magnitude if imbalance > 0 else magnitude
        except Exception:
            return 0.0
