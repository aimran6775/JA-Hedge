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
        min_samples: int = 20,                # Phase 14: train with less data (was 30)
        retrain_threshold: int = 10,           # Phase 14: retrain every 10 trades (was 15)
        challenger_must_beat_by: float = 0.002, # Phase 14: easier promotion (was 0.005)
        min_auc_to_deploy: float = 0.535,      # Refuse models barely above coin flip — need real edge
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
            # Accept if AUC is at least as good
            if challenger.val_auc >= self._champion.val_auc - 0.005:
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
            "top_features": dict(
                sorted(
                    self.get_feature_importance().items(),
                    key=lambda x: x[1],
                    reverse=True,
                )[:10]
            ),
        }
