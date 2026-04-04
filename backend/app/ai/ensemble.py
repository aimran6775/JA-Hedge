"""
JA Hedge — Ensemble Prediction Model (Phase 4).

Combines multiple models for more robust predictions:
  1. XGBoost (primary — captures nonlinear patterns)
  2. Logistic Regression (baseline — captures linear signals)
  3. Platt-scaled calibration layer (ensures probabilities are well-calibrated)

Also implements walk-forward validation for proper backtesting.
"""

from __future__ import annotations

import math
import pickle
from pathlib import Path
from typing import Any

import numpy as np

from app.ai.features import MarketFeatures
from app.ai.models import Prediction, PredictionModel, XGBoostPredictor
from app.logging_config import get_logger

log = get_logger("ai.ensemble")


class LogisticPredictor:
    """
    Simple logistic regression baseline.
    Fast, interpretable, and good at linear patterns.
    Uses sklearn under the hood.
    """

    def __init__(self) -> None:
        self._model: Any = None
        self._fitted = False

    @property
    def is_trained(self) -> bool:
        return self._fitted

    def train(self, X: np.ndarray, y: np.ndarray) -> dict[str, float]:
        """Train the logistic regression model."""
        try:
            from sklearn.linear_model import LogisticRegression
            from sklearn.preprocessing import StandardScaler
            from sklearn.metrics import roc_auc_score, log_loss

            self._scaler = StandardScaler()
            X_scaled = self._scaler.fit_transform(X)

            self._model = LogisticRegression(
                C=1.0,
                max_iter=1000,
                solver="lbfgs",
                class_weight="balanced",
            )
            self._model.fit(X_scaled, y)
            self._fitted = True

            # Compute metrics on training data
            probs = self._model.predict_proba(X_scaled)[:, 1]
            auc = roc_auc_score(y, probs) if len(set(y)) > 1 else 0.5
            ll = log_loss(y, probs)

            return {"lr_auc": auc, "lr_logloss": ll}
        except ImportError:
            log.warning("sklearn not available, logistic predictor disabled")
            return {}
        except Exception as e:
            log.error("lr_train_failed", error=str(e))
            return {}

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Predict probabilities for P(YES)."""
        if not self._fitted:
            return np.full(len(X), 0.5)
        try:
            X_scaled = self._scaler.transform(X)
            return self._model.predict_proba(X_scaled)[:, 1]
        except Exception:
            return np.full(len(X), 0.5)

    def save(self, path: str) -> None:
        if self._model is not None:
            with open(path, "wb") as f:
                pickle.dump({"model": self._model, "scaler": self._scaler}, f)

    def load(self, path: str) -> None:
        try:
            with open(path, "rb") as f:
                data = pickle.load(f)
            self._model = data["model"]
            self._scaler = data["scaler"]
            self._fitted = True
        except Exception:
            pass


class PlattCalibrator:
    """
    Platt scaling — maps raw model outputs to calibrated probabilities.

    Uses isotonic regression or Platt's sigmoid to ensure that
    when the model says 70%, the true outcome rate is ~70%.
    """

    def __init__(self) -> None:
        self._calibrator: Any = None
        self._fitted = False

    def fit(self, raw_probs: np.ndarray, y_true: np.ndarray) -> dict[str, float]:
        """Fit calibration curve from raw model probabilities."""
        try:
            from sklearn.isotonic import IsotonicRegression

            self._calibrator = IsotonicRegression(
                y_min=0.01, y_max=0.99, out_of_bounds="clip"
            )
            self._calibrator.fit(raw_probs, y_true)
            self._fitted = True

            # Measure calibration improvement
            calibrated = self.calibrate(raw_probs)
            raw_ece = self._expected_calibration_error(raw_probs, y_true)
            cal_ece = self._expected_calibration_error(calibrated, y_true)

            return {"raw_ece": raw_ece, "calibrated_ece": cal_ece}
        except ImportError:
            log.warning("sklearn not available, calibration disabled")
            return {}
        except Exception as e:
            log.error("calibration_fit_failed", error=str(e))
            return {}

    def calibrate(self, probs: np.ndarray) -> np.ndarray:
        """Apply calibration to raw probabilities."""
        if not self._fitted:
            return probs
        try:
            return self._calibrator.transform(probs)
        except Exception:
            return probs

    @staticmethod
    def _expected_calibration_error(
        probs: np.ndarray, y_true: np.ndarray, n_bins: int = 10
    ) -> float:
        """Compute Expected Calibration Error (ECE)."""
        bins = np.linspace(0, 1, n_bins + 1)
        ece = 0.0
        for i in range(n_bins):
            mask = (probs >= bins[i]) & (probs < bins[i + 1])
            if mask.sum() == 0:
                continue
            bin_conf = probs[mask].mean()
            bin_acc = y_true[mask].mean()
            ece += mask.sum() * abs(bin_conf - bin_acc)
        return ece / len(probs) if len(probs) > 0 else 0.0

    def save(self, path: str) -> None:
        if self._calibrator is not None:
            with open(path, "wb") as f:
                pickle.dump(self._calibrator, f)

    def load(self, path: str) -> None:
        try:
            with open(path, "rb") as f:
                self._calibrator = pickle.load(f)
            self._fitted = True
        except Exception:
            pass


class EnsemblePredictor(PredictionModel):
    """
    Ensemble predictor combining XGBoost + Logistic Regression.

    Architecture:
      1. Both models predict P(YES)
      2. Weighted average (xgb_weight * xgb_prob + lr_weight * lr_prob)
      3. Platt calibration applied to ensemble output
      4. Final calibrated probability used for trading decisions

    The ensemble reduces variance and catches linear patterns
    that XGBoost might miss, while XGBoost captures nonlinearities.
    """

    def __init__(
        self,
        xgb_weight: float = 0.70,
        lr_weight: float = 0.30,
        model_path: str | None = None,
    ):
        self._xgb = XGBoostPredictor(model_path=model_path)
        self._lr = LogisticPredictor()
        self._calibrator = PlattCalibrator()

        self._xgb_weight = xgb_weight
        self._lr_weight = lr_weight
        self._version = "ensemble-1.0.0"
        self._feature_names = MarketFeatures.feature_names()

    @property
    def name(self) -> str:
        return "ensemble_xgb_lr"

    @property
    def version(self) -> str:
        return self._version

    @property
    def is_trained(self) -> bool:
        return self._xgb.is_trained

    @property
    def _model(self) -> Any:
        """Compatibility: delegate to XGBoost's internal model."""
        return self._xgb._model

    @_model.setter
    def _model(self, value: Any) -> None:
        self._xgb._model = value

    def predict(self, features: MarketFeatures) -> Prediction:
        """Generate calibrated ensemble prediction."""
        if not self._xgb.is_trained:
            return self._xgb._heuristic_predict(features)

        try:
            X = features.to_array().reshape(1, -1)
            raw_probs, cal_probs = self._ensemble_predict(X)
            return self._build_ensemble_prediction(
                raw_prob=float(raw_probs[0]),
                calibrated_prob=float(cal_probs[0]),
                features=features,
            )
        except Exception as e:
            log.error("ensemble_predict_failed", error=str(e))
            return self._xgb._heuristic_predict(features)

    def predict_batch(self, features_list: list[MarketFeatures]) -> list[Prediction]:
        """Batch calibrated ensemble prediction."""
        if not features_list:
            return []

        if not self._xgb.is_trained:
            return [self._xgb._heuristic_predict(f) for f in features_list]

        try:
            X = np.array([f.to_array() for f in features_list])
            raw_probs, cal_probs = self._ensemble_predict(X)
            return [
                self._build_ensemble_prediction(
                    raw_prob=float(rp), calibrated_prob=float(cp), features=f,
                )
                for rp, cp, f in zip(raw_probs, cal_probs, features_list)
            ]
        except Exception as e:
            log.error("ensemble_batch_predict_failed", error=str(e))
            return [self._xgb._heuristic_predict(f) for f in features_list]

    def _ensemble_predict(self, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Compute weighted ensemble probability and calibrate.
        
        Returns:
            (raw_probs, calibrated_probs) — raw is pre-calibration ensemble,
            calibrated is post-Platt.
        """
        import xgboost as xgb

        # Phase 24b: Handle feature schema evolution.
        # If XGBoost model was trained with fewer features, trim X and names.
        feat_names = self._feature_names
        try:
            model_n_features = self._xgb._model.num_features()
        except (AttributeError, TypeError):
            model_n_features = X.shape[1]

        if X.shape[1] > model_n_features:
            X_xgb = X[:, :model_n_features]
            feat_names = self._feature_names[:model_n_features]
        else:
            X_xgb = X

        # Ensure feature name count matches
        if len(feat_names) != X_xgb.shape[1]:
            feat_names = feat_names[:X_xgb.shape[1]]

        # Use model's stored feature names if available to avoid name conflicts
        try:
            model_feat_names = self._xgb._model.feature_names
            if model_feat_names and len(model_feat_names) == X_xgb.shape[1]:
                feat_names = model_feat_names
        except (AttributeError, TypeError):
            pass

        # XGBoost prediction
        dmatrix = xgb.DMatrix(X_xgb, feature_names=feat_names)
        xgb_probs = self._xgb._model.predict(dmatrix)

        # Logistic regression prediction (or just use XGBoost if LR not trained)
        if self._lr.is_trained:
            lr_probs = self._lr.predict_proba(X)
            raw_probs = self._xgb_weight * xgb_probs + self._lr_weight * lr_probs
        else:
            raw_probs = xgb_probs

        # Calibrate
        if self._calibrator._fitted:
            calibrated_probs = self._calibrator.calibrate(raw_probs)
        else:
            calibrated_probs = raw_probs.copy()

        return (
            np.clip(raw_probs, 0.01, 0.99),
            np.clip(calibrated_probs, 0.01, 0.99),
        )

    def train(
        self,
        X: np.ndarray,
        y: np.ndarray,
        *,
        num_boost_round: int = 300,
        early_stopping_rounds: int = 25,
        eval_split: float = 0.2,
    ) -> dict[str, float]:
        """
        Train all ensemble components with walk-forward validation.

        1. Split temporally: 60% train, 20% calibration, 20% validation
        2. Train XGBoost on train set
        3. Train LogisticRegression on train set
        4. Fit Platt calibrator on calibration set
        5. Evaluate ensemble on validation set
        """
        n = len(X)
        n_train = int(n * 0.6)
        n_cal = int(n * 0.2)

        X_train, y_train = X[:n_train], y[:n_train]
        X_cal, y_cal = X[n_train:n_train + n_cal], y[n_train:n_train + n_cal]
        X_val, y_val = X[n_train + n_cal:], y[n_train + n_cal:]

        metrics: dict[str, float] = {}

        # 1. Train XGBoost on train portion
        xgb_metrics = self._xgb.train(
            X_train, y_train,
            num_boost_round=num_boost_round,
            early_stopping_rounds=early_stopping_rounds,
            eval_split=0.15,  # small internal split
        )
        metrics.update(xgb_metrics)

        # 2. Train Logistic Regression on train portion
        lr_metrics = self._lr.train(X_train, y_train)
        metrics.update(lr_metrics)

        # 3. Calibrate on calibration set
        if len(X_cal) > 10:
            try:
                import xgboost as xgb_lib
                # Phase 24b: feature schema reconciliation for calibration
                cal_feat_names = self._feature_names
                try:
                    cal_n_feat = self._xgb._model.num_features()
                except (AttributeError, TypeError):
                    cal_n_feat = X_cal.shape[1]
                X_cal_xgb = X_cal[:, :cal_n_feat] if X_cal.shape[1] > cal_n_feat else X_cal
                cal_feat_names = cal_feat_names[:X_cal_xgb.shape[1]]
                try:
                    model_feat_names = self._xgb._model.feature_names
                    if model_feat_names and len(model_feat_names) == X_cal_xgb.shape[1]:
                        cal_feat_names = model_feat_names
                except (AttributeError, TypeError):
                    pass
                dmatrix_cal = xgb_lib.DMatrix(X_cal_xgb, feature_names=cal_feat_names)
                raw_probs_cal = self._xgb._model.predict(dmatrix_cal)

                if self._lr.is_trained:
                    lr_probs_cal = self._lr.predict_proba(X_cal)
                    ensemble_cal = self._xgb_weight * raw_probs_cal + self._lr_weight * lr_probs_cal
                else:
                    ensemble_cal = raw_probs_cal

                cal_metrics = self._calibrator.fit(ensemble_cal, y_cal)
                metrics.update(cal_metrics)
            except Exception as e:
                log.warning("calibration_failed", error=str(e))

        # 4. Evaluate on held-out validation
        if len(X_val) > 5:
            try:
                from sklearn.metrics import roc_auc_score, log_loss
                _, val_probs = self._ensemble_predict(X_val)
                if len(set(y_val)) > 1:
                    metrics["val_auc"] = roc_auc_score(y_val, val_probs)
                    metrics["val_logloss"] = log_loss(y_val, val_probs)
                    metrics["best_iteration"] = xgb_metrics.get("best_iteration", 0)
            except Exception as e:
                log.warning("val_eval_failed", error=str(e))

        log.info("ensemble_trained", **{k: f"{v:.4f}" if isinstance(v, float) else v for k, v in metrics.items()})
        return metrics

    def _build_prediction(self, prob_yes: float, features: MarketFeatures) -> Prediction:
        """Build prediction from calibrated probability (legacy compat)."""
        # When called via legacy path, treat as both raw and calibrated
        return self._build_ensemble_prediction(prob_yes, prob_yes, features)

    def _build_ensemble_prediction(
        self,
        raw_prob: float,
        calibrated_prob: float,
        features: MarketFeatures,
    ) -> Prediction:
        """Build prediction from raw + calibrated ensemble probability.
        
        Unlike XGBoost._build_prediction, this does NOT re-calibrate
        because the ensemble pipeline already applied Platt calibration.
        """
        import math

        market_price = features.midpoint
        effective_prob = calibrated_prob
        effective_edge = effective_prob - market_price

        # Determine side
        side = "yes" if effective_edge > 0 else "no"

        # Compute real confidence — same market-aware formula as XGBoost
        # Decisiveness = divergence from MARKET PRICE, not from 0.5
        divergence = abs(effective_prob - market_price)
        decisiveness = min(divergence / 0.15, 1.0)

        # Edge capped at 15% — anything higher is model error
        edge_abs = min(abs(effective_edge), 0.15)
        edge_signal = edge_abs / 0.15

        is_calibrated = self._calibrator._fitted
        cal_error = self._xgb._calibration.expected_error(raw_prob) if hasattr(self._xgb, '_calibration') else 0.0
        cal_penalty = max(0.0, 1.0 - cal_error * 5.0)

        # Price-range penalty — extreme prices are harder to predict
        price_penalty = 1.0
        if market_price < 0.15 or market_price > 0.85:
            price_penalty = 0.5
        elif market_price < 0.25 or market_price > 0.75:
            price_penalty = 0.75

        confidence = (
            0.25 * decisiveness +
            0.25 * edge_signal +
            0.20 * 1.0 +      # ensemble inherently has better agreement
            0.10 * cal_penalty +
            0.20 * price_penalty
        )
        confidence = max(0.05, min(0.99, confidence))

        return Prediction(
            side=side,
            confidence=confidence,
            raw_prob=raw_prob,             # TRUE pre-calibration ensemble output
            predicted_prob=effective_prob,  # post-calibration probability
            edge=effective_edge,
            model_name=self.name,
            model_version=self.version,
            tree_agreement=1.0,  # ensemble: high implicit agreement
            prediction_std=abs(raw_prob - calibrated_prob),  # calibration shift as proxy
            calibrated_prob=calibrated_prob if is_calibrated else None,
            calibration_error=cal_error,
            is_calibrated=is_calibrated,
        )

    def save(self, path: str) -> None:
        """Save all ensemble components."""
        self._xgb.save(path)
        # Save LR and calibrator alongside
        base = Path(path).parent
        self._lr.save(str(base / "lr_model.pkl"))
        self._calibrator.save(str(base / "calibrator.pkl"))

    def load(self, path: str) -> None:
        """Load all ensemble components (graceful if LR/calibrator missing)."""
        self._xgb.load(path)
        base = Path(path).parent
        try:
            lr_path = base / "lr_model.pkl"
            if lr_path.exists():
                self._lr.load(str(lr_path))
        except Exception:
            pass  # XGBoost alone is fine
        try:
            cal_path = base / "calibrator.pkl"
            if cal_path.exists():
                self._calibrator.load(str(cal_path))
        except Exception:
            pass  # uncalibrated is fine


def walk_forward_validate(
    X: np.ndarray,
    y: np.ndarray,
    *,
    n_splits: int = 5,
    min_train_size: int = 100,
) -> dict[str, float]:
    """
    Walk-forward cross-validation for time-series data.

    Unlike k-fold, this respects temporal ordering:
      Split 1: train[0:200]  → test[200:300]
      Split 2: train[0:300]  → test[300:400]
      Split 3: train[0:400]  → test[400:500]
      etc.

    Returns averaged metrics across all splits.
    """
    n = len(X)
    if n < min_train_size + 50:
        return {"error": "insufficient_data"}

    test_size = max(50, (n - min_train_size) // n_splits)
    aucs, logloss_vals = [], []

    try:
        from sklearn.metrics import roc_auc_score, log_loss
    except ImportError:
        return {"error": "sklearn_not_available"}

    for i in range(n_splits):
        train_end = min_train_size + i * test_size
        test_end = min(train_end + test_size, n)

        if train_end >= n or test_end > n:
            break

        X_train, y_train = X[:train_end], y[:train_end]
        X_test, y_test = X[train_end:test_end], y[train_end:test_end]

        if len(set(y_test)) < 2:
            continue

        # Quick XGBoost train
        model = XGBoostPredictor()
        model.train(X_train, y_train, num_boost_round=100, early_stopping_rounds=10)

        if model.is_trained:
            import xgboost as xgb
            dtest = xgb.DMatrix(X_test, feature_names=MarketFeatures.feature_names())
            probs = model._model.predict(dtest)
            aucs.append(roc_auc_score(y_test, probs))
            logloss_vals.append(log_loss(y_test, probs))

    return {
        "wf_mean_auc": float(np.mean(aucs)) if aucs else 0.0,
        "wf_std_auc": float(np.std(aucs)) if aucs else 0.0,
        "wf_mean_logloss": float(np.mean(logloss_vals)) if logloss_vals else 0.0,
        "wf_n_splits": len(aucs),
    }
