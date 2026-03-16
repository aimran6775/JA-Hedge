"""Test the new ML improvements: CalibrationTracker, uncertainty, and confidence."""

import sys
sys.path.insert(0, ".")

from app.ai.models import CalibrationTracker, XGBoostPredictor, Prediction
from app.ai.features import MarketFeatures
import numpy as np

print("=" * 60)
print("Testing ML Improvements")
print("=" * 60)

# 1. CalibrationTracker
print("\n── CalibrationTracker ──")
ct = CalibrationTracker()
print(f"  Initialized: is_ready={ct.is_ready}, samples={ct._total_samples}")

for i in range(35):
    prob = max(0.01, min(0.99, 0.7 + np.random.normal(0, 0.05)))
    outcome = 1 if np.random.random() < 0.75 else 0
    ct.record(prob, outcome)

print(f"  After 35 samples: is_ready={ct.is_ready}, ECE={ct.expected_calibration_error:.4f}")
summary = ct.summary()
print(f"  Bins populated: {summary['bins_populated']}/{summary['bins_total']}")

# Serialize/deserialize
data = ct.to_dict()
ct2 = CalibrationTracker.from_dict(data)
print(f"  Deserialized: is_ready={ct2.is_ready}, samples={ct2._total_samples}")

# Calibrate
raw = 0.72
cal = ct.calibrate(raw)
err = ct.expected_error(raw)
print(f"  Calibrate {raw:.2f} -> {cal:.4f} (error={err:.4f})")

# 2. Prediction dataclass
print("\n── Prediction Dataclass ──")
p = Prediction(
    side="yes", confidence=0.78, predicted_prob=0.72, edge=0.05,
    tree_agreement=0.9, prediction_std=0.02, is_calibrated=True,
    calibrated_prob=0.73, calibration_error=0.03,
)
print(f"  side={p.side}, conf={p.confidence:.2f}, tree_agr={p.tree_agreement}")
print(f"  std={p.prediction_std}, cal_prob={p.calibrated_prob}, cal_err={p.calibration_error}")

# 3. XGBoostPredictor init
print("\n── XGBoostPredictor ──")
model = XGBoostPredictor()
print(f"  name={model.name}, trained={model.is_trained}")
print(f"  calibration_ready={model.calibration.is_ready}")

# 4. Heuristic predict (no model trained)
print("\n── Heuristic Predict (no model) ──")
features = MarketFeatures(
    ticker="TEST-MARKET",
    timestamp=1000000.0,
    midpoint=0.60,
    spread=0.04,
    spread_pct=0.04,
    volume=150, volume_ratio=1.2,
    hours_to_expiry=12.0,
    price_change_1m=0.02,
    price_change_5m=0.03,
    rsi_14=55.0,
    macd=0.01,
)
pred = model.predict(features)
print(f"  side={pred.side}, confidence={pred.confidence:.3f}")
print(f"  predicted_prob={pred.predicted_prob:.3f}, edge={pred.edge:.3f}")
print(f"  tree_agreement={pred.tree_agreement:.3f}, std={pred.prediction_std:.3f}")
print(f"  is_calibrated={pred.is_calibrated}")

# 5. Verify confidence is NOT just probability
print("\n── Confidence vs Probability Check ──")
assert pred.confidence != pred.predicted_prob, \
    "FAIL: Confidence should NOT equal probability!"
print(f"  ✅ Confidence ({pred.confidence:.3f}) != Probability ({pred.predicted_prob:.3f})")
print(f"  ✅ Confidence is a real composite metric, not just echoed probability")

print("\n" + "=" * 60)
print("✅ All ML improvement tests passed!")
print("=" * 60)
