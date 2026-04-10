"""
Frankenstein — Online Learner.

Continuously retrains the XGBoost model using trade outcomes.
Implements a champion/challenger pattern — new models must
beat the current model on held-out data before deployment.

Key features:
- Periodic retraining from trade memory
- Champion/challenger model comparison
- Feature importance tracking
- Model versioning & checkpointing
- Automatic fallback on degradation
"""

from __future__ import annotations

import time
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from app.ai.features import MarketFeatures
from app.ai.models import Prediction, XGBoostPredictor
from app.frankenstein.memory import TradeMemory
from app.logging_config import get_logger

log = get_logger("frankenstein.learner")


@dataclass
class ModelCheckpoint:
    """Snapshot of a model with its performance metrics."""
    version: str
    timestamp: float = field(default_factory=time.time)
    train_samples: int = 0
    val_auc: float = 0.0
    train_auc: float = 0.0
    best_iteration: int = 0
    feature_importance: dict[str, float] = field(default_factory=dict)
    live_accuracy: float = 0.0
    live_pnl: float = 0.0
    live_trades: int = 0
    is_champion: bool = False


class OnlineLearner:
    """
    Frankenstein's learning engine — makes the model smarter over time.

    Workflow:
    1. Collects resolved trades from memory
    2. Builds training dataset (features → outcomes)
    3. Trains challenger model
    4. Compares challenger vs champion on validation set
    5. Promotes challenger if it wins
    6. Tracks model lineage and feature importance
    """

    def __init__(
        self,
        model: XGBoostPredictor,
        memory: TradeMemory,
        *,
        min_samples: int = 50,                 # Phase 25: raised from 20 — need quality data
        retrain_threshold: int = 25,           # Phase 25: raised from 10 — less frequent retrains
        challenger_must_beat_by: float = 0.002, # Phase 14: easier promotion (was 0.005)
        min_auc_to_deploy: float = 0.540,      # Phase 25: raised from 0.535 — need real signal
        checkpoint_dir: str = "data/models",
        max_checkpoints: int = 10,
    ):
        self.model = model
        self.memory = memory
        self.min_samples = min_samples
        self.retrain_threshold = retrain_threshold
        self.challenger_must_beat_by = challenger_must_beat_by
        self.min_auc_to_deploy = min_auc_to_deploy
        self.checkpoint_dir = checkpoint_dir
        self.max_checkpoints = max_checkpoints

        # State
        self._champion: ModelCheckpoint | None = None
        self._checkpoints: list[ModelCheckpoint] = []
        self._last_train_count: int = 0
        self._total_retrains: int = 0
        self._total_promotions: int = 0
        self._generation: int = 0

        # Feature importance tracking over time
        self._importance_history: list[dict[str, float]] = []

        # Phase 18: Category-specific models
        self._category_models: dict[str, XGBoostPredictor] = {}
        self._MIN_CATEGORY_SAMPLES = 40  # need at least 40 resolved per category

        # Phase 35: Market outcome harvester (injected by brain)
        self._harvester: Any = None

        # Phase 5: Pretrained model blending
        # After N real trades, we blend pretrained historical data with
        # live trade data for retraining.  This prevents the model from
        # forgetting historical patterns while adapting to live conditions.
        self._FINETUNE_MIN_REAL_TRADES = 200   # start fine-tuning after 200 real trades
        self._FINETUNE_HISTORICAL_RATIO = 0.3  # 30% historical, 70% live in blended training
        self._pretrained_X: np.ndarray | None = None
        self._pretrained_y: np.ndarray | None = None

        log.info(
            "online_learner_initialized",
            min_samples=min_samples,
            retrain_threshold=retrain_threshold,
        )

    @property
    def current_version(self) -> str:
        return self._champion.version if self._champion else "untrained"

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def needs_retrain(self) -> bool:
        """Check if enough new data has accumulated for retraining."""
        resolved_count = self.memory.total_resolved
        new_since_last = resolved_count - self._last_train_count
        return new_since_last >= self.retrain_threshold

    # ── Training ──────────────────────────────────────────────────────

    async def retrain(self, force: bool = False) -> ModelCheckpoint | None:
        """
        Attempt to retrain the model with latest data.

        Returns the new checkpoint if training succeeded, None otherwise.
        """
        if not force and not self.needs_retrain:
            log.debug("retrain_skipped", reason="insufficient_new_data")
            return None

        # Extract training data from memory
        data = self.memory.get_training_data(min_trades=self.min_samples)
        if data is None:
            log.info("retrain_skipped", reason="insufficient_total_data")
            return None

        # Phase 16: memory now returns (X, y, sample_weights)
        if len(data) == 3:
            X, y, sample_weights = data
        else:
            X, y = data
            sample_weights = None

        # Phase 25: Class balance check — skip if all same label.
        # Training on 100% YES or 100% NO teaches the model nothing.
        # Need at least 15% minority class for meaningful gradients.
        from app.frankenstein.constants import MIN_CLASS_BALANCE
        if len(y) > 0:
            pos_rate = float(y.mean())
            minority_rate = min(pos_rate, 1.0 - pos_rate)
            if minority_rate < MIN_CLASS_BALANCE:
                log.info(
                    "retrain_skipped_class_imbalance",
                    pos_rate=f"{pos_rate:.3f}",
                    minority_rate=f"{minority_rate:.3f}",
                    min_required=f"{MIN_CLASS_BALANCE:.3f}",
                    samples=len(y),
                )
                return None

        # Phase 5: Blend pretrained historical data with live data
        # After enough real trades, mix in historical data to prevent
        # catastrophic forgetting of base patterns.
        # Phase 35c: Add feature dimension validation
        if (self._pretrained_X is not None 
            and len(X) >= self._FINETUNE_MIN_REAL_TRADES
            and self._pretrained_X.shape[1] == X.shape[1]):  # Dimension check
            n_hist = int(len(X) * self._FINETUNE_HISTORICAL_RATIO / (1 - self._FINETUNE_HISTORICAL_RATIO))
            n_hist = min(n_hist, len(self._pretrained_X))
            if n_hist > 0:
                # Random sample from pretrained data
                indices = np.random.choice(len(self._pretrained_X), n_hist, replace=False)
                hist_X = self._pretrained_X[indices]
                hist_y = self._pretrained_y[indices]
                X = np.vstack([X, hist_X])
                y = np.concatenate([y, hist_y])
                # Weight: live data 2× more than historical (recency matters)
                if sample_weights is not None:
                    hist_weights = np.ones(n_hist) * 0.5  # half weight for historical
                    sample_weights = np.concatenate([sample_weights, hist_weights])
                else:
                    live_weights = np.ones(len(X) - n_hist) * 1.0
                    hist_weights = np.ones(n_hist) * 0.5
                    sample_weights = np.concatenate([live_weights, hist_weights])
                log.info("pretrained_blend", live_samples=len(X)-n_hist,
                         historical_samples=n_hist, ratio=f"{self._FINETUNE_HISTORICAL_RATIO:.0%}")
        elif (self._pretrained_X is not None 
              and self._pretrained_X.shape[1] != X.shape[1]):
            log.warning("pretrained_feature_mismatch", 
                       pretrained_features=self._pretrained_X.shape[1],
                       current_features=X.shape[1])

        # Phase 35: Blend harvested market data (free training from non-traded markets)
        if self._harvester:
            try:
                harvest_data = self._harvester.get_training_data(
                    max_samples=len(X) * 3,  # Up to 3x trade data from harvest
                    max_age_hours=72.0,
                )
                if harvest_data is not None:
                    h_X, h_y, h_weights = harvest_data
                    n_harvest = len(h_X)
                    X = np.vstack([X, h_X])
                    y = np.concatenate([y, h_y])
                    if sample_weights is not None:
                        sample_weights = np.concatenate([sample_weights, h_weights])
                    else:
                        trade_weights = np.ones(len(X) - n_harvest) * 1.0
                        sample_weights = np.concatenate([trade_weights, h_weights])
                    log.info("harvest_blend", trade_samples=len(X)-n_harvest,
                             harvest_samples=n_harvest, total=len(X))
            except Exception as e:
                log.debug("harvest_blend_error", error=str(e))

        log.info(
            "retrain_starting",
            samples=len(X),
            positive_rate=f"{y.mean():.3f}",
            generation=self._generation + 1,
            has_sample_weights=sample_weights is not None,
        )

        # Train challenger
        challenger = XGBoostPredictor()
        try:
            metrics = challenger.train(
                X, y,
                num_boost_round=500,
                early_stopping_rounds=30,
                eval_split=0.2,
                n_cv_folds=3,
                hyperparam_trials=12,   # more trials → better hyperparams
                sample_weights=sample_weights,
            )
        except Exception as e:
            log.error("retrain_failed", error=str(e))
            return None

        # Phase 13+25: Feature importance pruning
        # After initial training, identify features with <1% importance
        # and retrain without them. This reduces noise and overfitting.
        # Phase 25: Only prune after 200+ samples (was 100) — need enough
        # data to reliably measure importance.
        importance = self._extract_importance(challenger)
        if importance and len(X) >= 200:
            # Find features above 1% importance threshold
            keep_indices = []
            feature_names = MarketFeatures.feature_names()
            for i, fname in enumerate(feature_names):
                # Use f{i} format that XGBoost uses for unnamed features
                xgb_name = f"f{i}"
                imp = importance.get(xgb_name, importance.get(fname, 0.0))
                if imp >= 0.01:  # 1% threshold
                    keep_indices.append(i)

            # Only prune if we'd keep at least 60% of features
            if len(keep_indices) >= len(feature_names) * 0.6 and len(keep_indices) < len(feature_names):
                X_pruned = X[:, keep_indices]
                pruned_count = len(feature_names) - len(keep_indices)
                log.info("feature_pruning", kept=len(keep_indices),
                         pruned=pruned_count, total=len(feature_names))

                # Retrain on pruned features
                challenger_pruned = XGBoostPredictor()
                try:
                    metrics_pruned = challenger_pruned.train(
                        X_pruned, y,
                        num_boost_round=500,
                        early_stopping_rounds=30,
                        eval_split=0.2,
                        n_cv_folds=3,
                        hyperparam_trials=8,
                        sample_weights=sample_weights,
                    )
                    # Use pruned model only if AUC improved
                    if metrics_pruned.get("val_auc", 0) > metrics.get("val_auc", 0):
                        challenger = challenger_pruned
                        metrics = metrics_pruned
                        log.info("pruned_model_adopted",
                                 auc_before=f"{metrics.get('val_auc', 0):.4f}",
                                 auc_after=f"{metrics_pruned.get('val_auc', 0):.4f}")
                except Exception:
                    pass  # stick with unpruned model

        # Create checkpoint
        version = self._make_version(len(X))
        checkpoint = ModelCheckpoint(
            version=version,
            train_samples=len(X),
            val_auc=metrics.get("val_auc", 0.0),
            train_auc=metrics.get("train_auc", 0.0),
            best_iteration=int(metrics.get("best_iteration", 0)),
            feature_importance=self._extract_importance(challenger),
        )

        self._total_retrains += 1

        # Champion/challenger comparison
        if self._should_promote(checkpoint):
            self._promote(challenger, checkpoint)

            # Phase 35: Train LightGBM for ensemble diversity
            # After XGBoost promotion, also train LightGBM alongside it.
            # LightGBM uses different regularization → ensemble diversity.
            try:
                if hasattr(self.model, 'train_lightgbm'):
                    lgb_metrics = self.model.train_lightgbm(
                        X, y, sample_weights=sample_weights,
                    )
                    log.info("lightgbm_retrained", **{
                        k: f"{v:.4f}" if isinstance(v, float) else v
                        for k, v in lgb_metrics.items()
                    })
            except Exception as e:
                log.debug("lightgbm_retrain_error", error=str(e))

            return checkpoint
        else:
            log.info(
                "challenger_rejected",
                challenger_auc=f"{checkpoint.val_auc:.4f}",
                champion_auc=f"{self._champion.val_auc:.4f}" if self._champion else "none",
            )
            return None

    def _should_promote(self, challenger: ModelCheckpoint) -> bool:
        """Decide if the challenger model should replace the champion."""
        # Phase 15: NEVER deploy a model below minimum AUC
        if challenger.val_auc < self.min_auc_to_deploy:
            log.warning(
                "challenger_below_min_auc",
                challenger_auc=f"{challenger.val_auc:.4f}",
                min_required=f"{self.min_auc_to_deploy:.4f}",
            )
            return False

        # Always promote if no champion exists
        if self._champion is None:
            return True

        # Challenger must beat champion's AUC by threshold
        if challenger.val_auc > self._champion.val_auc + self.challenger_must_beat_by:
            return True

        # Promote if trained on significantly more data (2x)
        if challenger.train_samples >= self._champion.train_samples * 2:
            # Accept if AUC is at least as good (no regression allowed)
            if challenger.val_auc >= self._champion.val_auc:
                return True

        return False

    def _promote(self, model: XGBoostPredictor, checkpoint: ModelCheckpoint) -> None:
        """Promote a challenger model to champion."""
        # Update the main model in-place — keep existing calibration tracker
        # (the challenger's calibration is empty; the champion's has real data)
        self.model._model = model._model
        self.model._version = checkpoint.version
        # NOTE: self.model._calibration is intentionally NOT replaced

        checkpoint.is_champion = True
        self._champion = checkpoint
        self._checkpoints.append(checkpoint)
        self._generation += 1
        self._total_promotions += 1
        self._last_train_count = self.memory.total_resolved

        # Track feature importance evolution
        if checkpoint.feature_importance:
            self._importance_history.append(checkpoint.feature_importance)

        # Save checkpoint to disk
        self._save_checkpoint(model, checkpoint)

        # Prune old checkpoints
        self._prune_checkpoints()

        log.info(
            "🧟 FRANKENSTEIN EVOLVED",
            generation=self._generation,
            version=checkpoint.version,
            auc=f"{checkpoint.val_auc:.4f}",
            samples=checkpoint.train_samples,
            best_iter=checkpoint.best_iteration,
        )

    # ── Phase 18: Category-Specific Model Training ─────────────────

    async def train_category_models(self) -> dict[str, XGBoostPredictor]:
        """Train specialist XGBoost models per market category.

        Returns dict of {category: trained_model} for categories with
        enough data.  Categories with <40 samples are skipped.
        """
        from app.frankenstein.categories import detect_category
        from collections import defaultdict

        # Group resolved trades by category
        category_records: dict[str, list] = defaultdict(list)
        for t in self.memory._trades:
            if t.market_result not in ("yes", "no"):
                continue
            if not t.features:
                continue
            cat = t.category or detect_category(
                t.market_title or "", "", ticker=t.ticker
            )
            if cat:
                category_records[cat].append(t)

        trained: dict[str, XGBoostPredictor] = {}
        expected_dim = len(MarketFeatures.feature_names())

        for cat, records in category_records.items():
            if len(records) < self._MIN_CATEGORY_SAMPLES:
                continue

            # Build X, y from category-specific records
            padded = []
            for r in records:
                feat = list(r.features)
                if len(feat) < expected_dim:
                    feat.extend([0.0] * (expected_dim - len(feat)))
                elif len(feat) > expected_dim:
                    feat = feat[:expected_dim]
                padded.append(feat)

            X = np.array(padded, dtype=np.float32)
            y = np.array(
                [1.0 if r.market_result == "yes" else 0.0 for r in records],
                dtype=np.float32,
            )

            # Train a lightweight specialist model (fewer rounds, no tuning)
            specialist = XGBoostPredictor()
            try:
                metrics = specialist.train(
                    X, y,
                    num_boost_round=200,
                    early_stopping_rounds=20,
                    eval_split=0.25,
                    n_cv_folds=2,
                    hyperparam_trials=4,
                )
                val_auc = metrics.get("val_auc", 0.0)
                if val_auc >= 0.54:  # must beat coin flip meaningfully
                    trained[cat] = specialist
                    log.info("category_model_trained", category=cat,
                             samples=len(records), auc=f"{val_auc:.4f}")
                else:
                    log.debug("category_model_weak", category=cat,
                              auc=f"{val_auc:.4f}")
            except Exception as e:
                log.debug("category_model_failed", category=cat, error=str(e))

        self._category_models = trained
        return trained

    # ── Feature Importance ────────────────────────────────────────────

    def _extract_importance(self, model: XGBoostPredictor) -> dict[str, float]:
        """Extract feature importance from a trained model."""
        if model._model is None:
            return {}

        try:
            importance = model._model.get_score(importance_type="gain")
            # Normalize
            total = sum(importance.values()) or 1.0
            return {k: v / total for k, v in importance.items()}
        except Exception:
            return {}

    def get_feature_importance(self) -> dict[str, float]:
        """Get current champion's feature importance."""
        if self._champion and self._champion.feature_importance:
            return self._champion.feature_importance
        return {}

    def get_importance_trends(self) -> dict[str, list[float]]:
        """Track how feature importance changes across generations."""
        if not self._importance_history:
            return {}

        all_features = set()
        for imp in self._importance_history:
            all_features.update(imp.keys())

        trends: dict[str, list[float]] = {}
        for feat in all_features:
            trends[feat] = [imp.get(feat, 0.0) for imp in self._importance_history]

        return trends

    # ── Checkpointing ─────────────────────────────────────────────────

    def _save_checkpoint(self, model: XGBoostPredictor, checkpoint: ModelCheckpoint) -> None:
        """Save model checkpoint to disk."""
        try:
            path = Path(self.checkpoint_dir)
            path.mkdir(parents=True, exist_ok=True)
            model_path = path / f"frankenstein_gen{self._generation}_{checkpoint.version}.pkl"
            model.save(str(model_path))
            log.info("checkpoint_saved", path=str(model_path))
        except Exception as e:
            log.error("checkpoint_save_failed", error=str(e))

    def _prune_checkpoints(self) -> None:
        """Keep only the most recent checkpoints on disk."""
        try:
            path = Path(self.checkpoint_dir)
            if not path.exists():
                return
            files = sorted(path.glob("frankenstein_gen*.pkl"), key=lambda f: f.stat().st_mtime)
            while len(files) > self.max_checkpoints:
                oldest = files.pop(0)
                oldest.unlink()
                log.debug("checkpoint_pruned", path=str(oldest))
        except Exception:
            pass

    def _make_version(self, n_samples: int) -> str:
        """Generate a version string for a model."""
        ts = int(time.time())
        raw = f"fk-g{self._generation + 1}-n{n_samples}-t{ts}"
        short_hash = hashlib.md5(raw.encode()).hexdigest()[:6]
        return f"fk-g{self._generation + 1}-{short_hash}"

    # ── Statistics ────────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        """Full learner statistics."""
        return {
            "generation": self._generation,
            "current_version": self.current_version,
            "total_retrains": self._total_retrains,
            "total_promotions": self._total_promotions,
            "last_train_count": self._last_train_count,
            "needs_retrain": self.needs_retrain,
            "champion": self._champion.version if self._champion else None,
            "champion_auc": self._champion.val_auc if self._champion else 0.0,
            "champion_samples": self._champion.train_samples if self._champion else 0,
            "checkpoints": len(self._checkpoints),
            "pretrained_data_loaded": self._pretrained_X is not None,
            "pretrained_samples": len(self._pretrained_X) if self._pretrained_X is not None else 0,
            "finetune_threshold": self._FINETUNE_MIN_REAL_TRADES,
            "top_features": dict(
                sorted(
                    self.get_feature_importance().items(),
                    key=lambda x: x[1],
                    reverse=True,
                )[:10]
            ),
        }

    # ── Phase 5: Pretrained data loading ────────────────────────────

    def load_pretrained_data(self) -> bool:
        """Load historical training data for blending with live data.
        
        Call this after the pretrained model is loaded.  The data comes from
        the same historical feature pipeline that produced the pretrained model.
        """
        try:
            from app.frankenstein.historical_features import build_training_dataset
            X, y, meta = build_training_dataset()
            if X is not None and len(X) > 0:
                self._pretrained_X = X
                self._pretrained_y = y
                log.info(
                    "pretrained_data_loaded_for_blending",
                    samples=len(X),
                    positive_rate=f"{y.mean():.3f}",
                )
                return True
        except Exception as e:
            log.warning("pretrained_data_load_failed", error=str(e))
        return False
