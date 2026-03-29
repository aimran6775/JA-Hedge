#!/usr/bin/env python3
"""Quick pipeline test: candles → features → XGBoost model."""
import sys
sys.path.insert(0, ".")

from app.frankenstein.historical_features import build_training_dataset
import numpy as np

print("=" * 60)
print("PIPELINE TEST: candles → features → model")
print("=" * 60)

X, y, meta = build_training_dataset(
    series=["KXBTC15M"],
    max_markets=200,
    min_candles=10,
)
print(f"\nDataset: {X.shape[0]} samples × {X.shape[1]} features")
print(f"YES rate: {y.mean():.3f}")
uniq = len(set(m["ticker"] for m in meta))
print(f"Markets: {uniq}  Slices/mkt: {len(meta)/max(uniq,1):.1f}")

if len(X) < 50:
    print("Not enough data for model test — need more candles harvested.")
    sys.exit(0)

import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, roc_auc_score

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)

model = xgb.XGBClassifier(
    n_estimators=100, max_depth=4, learning_rate=0.1,
    eval_metric="logloss", random_state=42, verbosity=0,
)
model.fit(X_train, y_train)

y_pred = model.predict(X_test)
y_prob = model.predict_proba(X_test)[:, 1]
acc = accuracy_score(y_test, y_pred)
auc = roc_auc_score(y_test, y_prob)

print(f"\nModel Performance:")
print(f"  Accuracy: {acc:.3f}")
print(f"  AUC-ROC:  {auc:.3f}")
print(f"  Train: {len(X_train)}  Test: {len(X_test)}")

# Feature importance
from app.ai.features import MarketFeatures
names = MarketFeatures.feature_names()
importances = model.feature_importances_
top = sorted(zip(names, importances), key=lambda x: -x[1])[:10]
print(f"\nTop 10 features:")
for name, imp in top:
    print(f"  {name:<30} {imp:.4f}")

# Zero-col check
zero_cols = (X == 0).all(axis=0).sum()
print(f"\nAll-zero feature columns: {zero_cols}/{X.shape[1]}")

print("\n✅ Pipeline test PASSED!")
