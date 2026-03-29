"""
Frankenstein — Pre-trained Model Builder (Phase 3).

Trains an XGBoost model on historical Kalshi data (20k+ real samples)
with walk-forward cross-validation. This is the STATIC BASE MODEL that
Frankenstein loads on startup — it already knows how prediction markets
behave before seeing a single live trade.

The pre-trained model is saved to data/models/pretrained_v1.pkl and
loaded automatically by brain.py on startup.

Usage (standalone):
    python -m app.frankenstein.pretrained

Usage (from code):
    from app.frankenstein.pretrained import build_pretrained_model
    metrics = build_pretrained_model()
"""

from __future__ import annotations

import os
import pickle
import random
import time
from pathlib import Path
from typing import Any

import numpy as np

from app.ai.features import MarketFeatures
from app.ai.models import CalibrationTracker
from app.logging_config import get_logger

log = get_logger("frankenstein.pretrained")

# Respect PERSIST_DIR env var (set to /data on Railway volume mount)
_PERSIST_DIR = Path(os.environ.get("PERSIST_DIR",
    str(Path(__file__).resolve().parent.parent.parent / "data")))
MODEL_DIR = _PERSIST_DIR / "models"
PRETRAINED_PATH = MODEL_DIR / "pretrained_v1.pkl"


def build_pretrained_model(
    db_path: str | Path | None = None,
    output_path: str | Path | None = None,
    series: list[str] | None = None,
    max_markets: int = 0,
    n_cv_folds: int = 5,
    hyperparam_trials: int = 20,
    num_boost_round: int = 800,
    early_stopping_rounds: int = 40,
    holdout_fraction: float = 0.15,
) -> dict[str, Any]:
    """
    Build and save the pre-trained XGBoost model.

    Pipeline:
      1. Load historical features from SQLite
      2. Split into train/holdout (time-ordered, no leakage)
      3. Walk-forward CV for hyperparameter selection
      4. Train final model on full training set
      5. Evaluate on holdout
      6. Build calibration from holdout predictions
      7. Save model + calibration + metadata

    Returns:
        Dict with training metrics, feature importance, calibration stats.
    """
    import xgboost as xgb

    from app.frankenstein.historical_features import build_training_dataset

    save_path = Path(output_path) if output_path else PRETRAINED_PATH
    save_path.parent.mkdir(parents=True, exist_ok=True)

    log.info("pretrained_build_start",
             output=str(save_path),
             cv_folds=n_cv_folds,
             hp_trials=hyperparam_trials)

    # ── 1. Load data ──────────────────────────────────────────────
    start_time = time.time()
    X, y, meta = build_training_dataset(
        db_path=db_path, series=series, max_markets=max_markets,
    )

    if len(X) < 100:
        log.error("insufficient_data", samples=len(X))
        return {"success": False, "error": f"Only {len(X)} samples, need 100+"}

    n_features = X.shape[1]
    n_samples = len(X)
    feature_names = MarketFeatures.feature_names()

    # Ensure feature names match
    if len(feature_names) != n_features:
        log.warning("feature_dimension_mismatch",
                     expected=len(feature_names), got=n_features)
        feature_names = [f"f{i}" for i in range(n_features)]

    log.info("data_loaded",
             samples=n_samples,
             features=n_features,
             positive_rate=f"{y.mean():.3f}")

    # ── 2. Time-ordered train/holdout split ───────────────────────
    # Data is ordered by market expiration time (via build_training_dataset).
    # Holdout is the LAST fraction — simulates forward-looking evaluation.
    n_holdout = int(n_samples * holdout_fraction)
    n_train = n_samples - n_holdout

    X_train, X_holdout = X[:n_train], X[n_train:]
    y_train, y_holdout = y[:n_train], y[n_train:]
    meta_train, meta_holdout = meta[:n_train], meta[n_train:]

    log.info("data_split",
             train=n_train, holdout=n_holdout,
             train_pos=f"{y_train.mean():.3f}",
             holdout_pos=f"{y_holdout.mean():.3f}")

    # ── 3. Class balance ──────────────────────────────────────────
    pos_count = max(y_train.sum(), 1)
    neg_count = max(n_train - pos_count, 1)
    scale_pos_weight = float(neg_count / pos_count)

    # ── 4. Sample weights (recency-weighted) ──────────────────────
    # More recent markets get higher weight — market dynamics change.
    weights = np.exp(np.linspace(-1.5, 0.0, n_train))
    weights = weights * (n_train / weights.sum())  # normalize

    # ── 5. Hyperparameter search ──────────────────────────────────
    def _random_params() -> dict:
        return {
            "objective": "binary:logistic",
            "eval_metric": ["logloss", "auc"],
            "max_depth": random.choice([3, 4, 5, 6]),
            "learning_rate": random.choice([0.01, 0.02, 0.03, 0.05, 0.07]),
            "subsample": random.uniform(0.60, 0.85),
            "colsample_bytree": random.uniform(0.50, 0.85),
            "colsample_bylevel": random.uniform(0.60, 0.95),
            "min_child_weight": random.choice([3, 5, 7, 10, 15, 20]),
            "gamma": random.choice([0.1, 0.2, 0.5, 1.0, 2.0]),
            "reg_alpha": random.choice([0.01, 0.1, 0.5, 1.0, 2.0, 5.0]),
            "reg_lambda": random.choice([1.0, 2.0, 5.0, 10.0, 20.0]),
            "scale_pos_weight": scale_pos_weight,
            "max_delta_step": random.choice([1, 3, 5]),
            "seed": 42,
        }

    best_auc = 0.0
    best_params = None
    cv_results: list[dict] = []

    # Walk-forward CV on training set
    fold_size = max(n_train // (n_cv_folds + 1), 50)

    for trial in range(hyperparam_trials):
        params = _random_params()
        fold_aucs = []
        fold_logloss = []

        for fold in range(n_cv_folds):
            train_end = fold_size * (fold + 1)
            val_end = min(train_end + fold_size, n_train)
            if train_end >= n_train or val_end <= train_end:
                continue

            Xf_tr, yf_tr = X_train[:train_end], y_train[:train_end]
            Xf_va, yf_va = X_train[train_end:val_end], y_train[train_end:val_end]
            wf_tr = weights[:train_end]

            if len(Xf_va) < 5 or len(Xf_tr) < 20:
                continue

            dtrain = xgb.DMatrix(Xf_tr, label=yf_tr, weight=wf_tr,
                                 feature_names=feature_names)
            dval = xgb.DMatrix(Xf_va, label=yf_va,
                               feature_names=feature_names)

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
                fold_ll = evals_result["val"]["logloss"][-1]
                fold_aucs.append(fold_auc)
                fold_logloss.append(fold_ll)
            except Exception as e:
                log.debug("cv_fold_error", trial=trial, fold=fold, error=str(e))
                continue

        if fold_aucs:
            mean_auc = sum(fold_aucs) / len(fold_aucs)
            mean_ll = sum(fold_logloss) / len(fold_logloss) if fold_logloss else 0
            cv_results.append({
                "trial": trial,
                "mean_auc": mean_auc,
                "mean_logloss": mean_ll,
                "depth": params["max_depth"],
                "lr": params["learning_rate"],
            })
            if mean_auc > best_auc:
                best_auc = mean_auc
                best_params = params
                log.info("new_best_hp",
                         trial=trial, auc=f"{mean_auc:.4f}",
                         depth=params["max_depth"],
                         lr=params["learning_rate"])

    if best_params is None:
        best_params = _random_params()
        best_params.update({"max_depth": 4, "learning_rate": 0.03,
                            "min_child_weight": 7, "gamma": 0.5,
                            "reg_lambda": 5.0})

    # ── 6. Train final model ──────────────────────────────────────
    log.info("training_final_model", params=best_params)

    dtrain_full = xgb.DMatrix(X_train, label=y_train, weight=weights,
                               feature_names=feature_names)
    dholdout = xgb.DMatrix(X_holdout, label=y_holdout,
                            feature_names=feature_names)

    final_evals: dict = {}
    final_model = xgb.train(
        best_params, dtrain_full,
        num_boost_round=num_boost_round,
        evals=[(dtrain_full, "train"), (dholdout, "holdout")],
        early_stopping_rounds=early_stopping_rounds,
        evals_result=final_evals,
        verbose_eval=False,
    )

    # ── 7. Evaluate on holdout ────────────────────────────────────
    holdout_preds = final_model.predict(dholdout)
    holdout_auc = final_evals["holdout"]["auc"][-1]
    holdout_logloss = final_evals["holdout"]["logloss"][-1]
    train_auc = final_evals["train"]["auc"][-1]

    # Binary accuracy at 0.5 threshold
    holdout_acc = float(((holdout_preds > 0.5) == y_holdout).mean())

    # Calibration: mean predicted vs actual rate
    mean_pred = holdout_preds.mean()
    mean_actual = y_holdout.mean()
    calibration_bias = mean_pred - mean_actual

    # Brier score
    brier = float(((holdout_preds - y_holdout) ** 2).mean())

    log.info("holdout_evaluation",
             auc=f"{holdout_auc:.4f}",
             logloss=f"{holdout_logloss:.4f}",
             accuracy=f"{holdout_acc:.3f}",
             brier=f"{brier:.4f}",
             calibration_bias=f"{calibration_bias:.4f}")

    # ── 8. Build calibration tracker from holdout ─────────────────
    calibration = CalibrationTracker()
    for pred_p, actual in zip(holdout_preds, y_holdout):
        calibration.record(float(pred_p), int(actual))

    # ── 9. Feature importance ─────────────────────────────────────
    importance = final_model.get_score(importance_type="gain")
    total_imp = sum(importance.values()) or 1.0
    top_features = sorted(importance.items(), key=lambda x: x[1], reverse=True)[:20]
    feature_importance = {k: round(v / total_imp, 4) for k, v in top_features}

    # Check for leakage
    leakage_warning = None
    if top_features and (top_features[0][1] / total_imp) > 0.25:
        leakage_warning = f"Feature '{top_features[0][0]}' has {top_features[0][1]/total_imp:.1%} importance"
        log.warning("⚠️ POSSIBLE LEAKAGE", warning=leakage_warning)

    # ── 10. Save model ────────────────────────────────────────────
    payload = {
        "model": final_model,
        "calibration": calibration.to_dict(),
        "version": "pretrained_v1",
        "metadata": {
            "train_samples": n_train,
            "holdout_samples": n_holdout,
            "total_features": n_features,
            "features_used": len(importance),
            "train_auc": train_auc,
            "holdout_auc": holdout_auc,
            "holdout_accuracy": holdout_acc,
            "holdout_logloss": holdout_logloss,
            "brier_score": brier,
            "calibration_bias": calibration_bias,
            "best_params": {k: v for k, v in best_params.items()
                           if k not in ("objective", "eval_metric", "seed")},
            "cv_best_auc": best_auc,
            "hp_trials": hyperparam_trials,
            "cv_folds": n_cv_folds,
            "feature_importance": feature_importance,
            "leakage_warning": leakage_warning,
            "built_at": time.time(),
            "build_duration_s": time.time() - start_time,
        },
    }

    with open(str(save_path), "wb") as f:
        pickle.dump(payload, f)

    log.info("pretrained_model_saved",
             path=str(save_path),
             size_mb=f"{save_path.stat().st_size / 1024 / 1024:.1f}")

    metrics = {
        "success": True,
        "path": str(save_path),
        "train_samples": n_train,
        "holdout_samples": n_holdout,
        "train_auc": round(train_auc, 4),
        "holdout_auc": round(holdout_auc, 4),
        "cv_best_auc": round(best_auc, 4),
        "holdout_accuracy": round(holdout_acc, 3),
        "holdout_logloss": round(holdout_logloss, 4),
        "brier_score": round(brier, 4),
        "calibration_bias": round(calibration_bias, 4),
        "calibration_ece": round(calibration.expected_calibration_error, 4),
        "features_used": len(importance),
        "best_depth": best_params.get("max_depth"),
        "best_lr": best_params.get("learning_rate"),
        "feature_importance": feature_importance,
        "leakage_warning": leakage_warning,
        "build_duration_s": round(time.time() - start_time, 1),
    }

    log.info("pretrained_build_complete", **{
        k: v for k, v in metrics.items()
        if k not in ("feature_importance",)
    })

    # Phase 13+17: Save edge distribution and recommended parameters
    # These get loaded by brain.py on startup
    try:
        import json
        from app.frankenstein.historical_features import compute_edge_distribution
        edge_dist = compute_edge_distribution(db_path=db_path)
        # Map series-level caps to category-level caps
        series_to_cat = {
            "KXBTC15M": "crypto", "KXETH15M": "crypto", "KXBTC": "crypto",
            "KXETH": "crypto", "KXBTCD": "crypto", "KXETHD": "crypto",
            "KXSOL": "crypto", "KXNAS100": "finance", "KXSP500": "finance",
        }
        category_caps: dict[str, float] = {}
        for series_t, stats in edge_dist.items():
            cat = series_to_cat.get(series_t, "general")
            p95 = stats.get("p95_edge", 0.10)
            # Use the most conservative (lowest) cap for each category
            if cat not in category_caps or p95 < category_caps[cat]:
                category_caps[cat] = round(min(p95, 0.15), 4)  # cap at 15% max
        
        # Compute recommended min edge from overall distribution
        all_edges = []
        for stats in edge_dist.values():
            all_edges.append(stats.get("p95_edge", 0.08))
        p75_edge = float(np.percentile(all_edges, 75)) if all_edges else 0.08

        recs = {
            "recommended_min_edge": round(max(p75_edge, 0.05), 4),
            "recommended_daily_cap": 15,
            "recommended_price_floor": 40,
            "category_edge_caps": category_caps,
            "holdout_auc": round(holdout_auc, 4),
            "holdout_accuracy": round(holdout_acc, 3),
            "built_at": time.time(),
        }
        recs_path = save_path.parent / "backtest_recommendations.json"
        with open(str(recs_path), "w") as f:
            json.dump(recs, f, indent=2)
        log.info("backtest_recs_saved", path=str(recs_path))
    except Exception as e:
        log.warning("backtest_recs_save_failed", error=str(e))

    return metrics


def load_pretrained_model(
    path: str | Path | None = None,
) -> tuple[Any, CalibrationTracker, dict[str, Any]] | None:
    """
    Load the pre-trained model from disk.

    Returns:
        (xgb_model, calibration_tracker, metadata) or None if not found.
    """
    load_path = Path(path) if path else PRETRAINED_PATH
    if not load_path.exists():
        log.info("no_pretrained_model", path=str(load_path))
        return None

    try:
        with open(str(load_path), "rb") as f:
            data = pickle.load(f)

        model = data["model"]
        cal_data = data.get("calibration")
        calibration = CalibrationTracker.from_dict(cal_data) if cal_data else CalibrationTracker()
        metadata = data.get("metadata", {})

        log.info("pretrained_model_loaded",
                 path=str(load_path),
                 version=data.get("version", "unknown"),
                 auc=metadata.get("holdout_auc", "?"),
                 samples=metadata.get("train_samples", "?"))

        return model, calibration, metadata
    except Exception as e:
        log.error("pretrained_load_failed", path=str(load_path), error=str(e))
        return None


# ── Standalone execution ──────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Frankenstein Pre-trained Model Builder")
    parser.add_argument("--db", default=None, help="Historical database path")
    parser.add_argument("--output", default=None, help="Output model path")
    parser.add_argument("--series", nargs="+", default=None, help="Series to include")
    parser.add_argument("--max-markets", type=int, default=0, help="Max markets (0=all)")
    parser.add_argument("--hp-trials", type=int, default=20, help="Hyperparameter trials")
    parser.add_argument("--cv-folds", type=int, default=5, help="CV folds")
    parser.add_argument("--boost-rounds", type=int, default=800, help="Max boost rounds")
    parser.add_argument("--info", action="store_true", help="Show pretrained model info")
    args = parser.parse_args()

    if args.info:
        result = load_pretrained_model(args.output)
        if result:
            _, cal, meta = result
            print("\n📊 Pre-trained Model Info:")
            for k, v in meta.items():
                if k == "feature_importance":
                    print(f"  {k}:")
                    for fname, imp in v.items():
                        print(f"    {fname:<30} {imp:.4f}")
                else:
                    print(f"  {k}: {v}")
            print(f"\n  Calibration ECE: {cal.expected_calibration_error:.4f}")
            print(f"  Calibration samples: {cal._total_samples}")
        else:
            print("No pre-trained model found.")
    else:
        metrics = build_pretrained_model(
            db_path=args.db,
            output_path=args.output,
            series=args.series,
            max_markets=args.max_markets,
            hyperparam_trials=args.hp_trials,
            n_cv_folds=args.cv_folds,
            num_boost_round=args.boost_rounds,
        )
        if metrics.get("success"):
            print(f"\n✅ Pre-trained model built successfully!")
            print(f"   Path: {metrics['path']}")
            print(f"   Train AUC: {metrics['train_auc']}")
            print(f"   Holdout AUC: {metrics['holdout_auc']}")
            print(f"   Holdout Accuracy: {metrics['holdout_accuracy']}")
            print(f"   Brier Score: {metrics['brier_score']}")
            print(f"   Calibration ECE: {metrics['calibration_ece']}")
            print(f"   Build time: {metrics['build_duration_s']}s")
        else:
            print(f"\n❌ Build failed: {metrics.get('error', 'unknown')}")
