"""Quick verification of all Phase 25 changes."""
import sys
sys.path.insert(0, "/Users/abdullahimran/Documents/JA Hedge/backend")

# 1. Constants
from app.frankenstein.constants import (
    MIN_HOLD_MINUTES_MAKER, MIN_HOLD_MINUTES_TAKER, LEARNING_MODE_CATASTROPHIC_STOP,
    MIN_TRAINING_SAMPLES, RETRAIN_INTERVAL, MIN_CLASS_BALANCE,
    EXTREME_PRICE_THRESHOLD_YES, EXTREME_PRICE_THRESHOLD_NO,
    TIMEOUT_HOURS, TIMEOUT_PRICE_YES, TIMEOUT_PRICE_NO,
    LEARNING_MODE_EDGE_CAP_MULT, MAX_DAILY_TRADES,
    MAX_PER_EVENT, MAX_PER_CATEGORY, CATEGORY_EDGE_CAPS,
)
print(f"✅ Constants: hold={MIN_HOLD_MINUTES_MAKER}min, train_min={MIN_TRAINING_SAMPLES}, "
      f"retrain_interval={RETRAIN_INTERVAL}, extreme={EXTREME_PRICE_THRESHOLD_YES}/{EXTREME_PRICE_THRESHOLD_NO}, "
      f"timeout={TIMEOUT_HOURS}h at {TIMEOUT_PRICE_YES}/{TIMEOUT_PRICE_NO}")
print(f"   Edge caps: sports={CATEGORY_EDGE_CAPS['sports']}, crypto={CATEGORY_EDGE_CAPS['crypto']}, "
      f"learning mult={LEARNING_MODE_EDGE_CAP_MULT}")
print(f"   Daily cap={MAX_DAILY_TRADES}, per_event={MAX_PER_EVENT}, per_cat={MAX_PER_CATEGORY}")

# 2. Confidence weights sum to 1.0
from app.frankenstein.confidence import FACTOR_WEIGHTS
total = sum(FACTOR_WEIGHTS.values())
assert abs(total - 1.0) < 0.01, f"Weights don't sum to 1.0: {total}"
print(f"✅ Confidence weights sum to {total:.2f} ({len(FACTOR_WEIGHTS)} factors)")

# 3. Import chain
from app.main import app
print("✅ Full import chain OK")

# 4. Verify strategy defaults
from app.frankenstein.strategy import StrategyParams
p = StrategyParams()
print(f"✅ Strategy: min_conf={p.min_confidence}, min_edge={p.min_edge}, "
      f"scan_interval={p.scan_interval}s, max_positions={p.max_simultaneous_positions}")

# 5. Verify learner defaults
from app.frankenstein.learner import OnlineLearner
from app.ai.models import XGBoostPredictor
from app.frankenstein.memory import TradeMemory
model = XGBoostPredictor()
mem = TradeMemory()
learner = OnlineLearner(model, mem)
print(f"✅ Learner: min_samples={learner.min_samples}, retrain_threshold={learner.retrain_threshold}, "
      f"min_auc={learner.min_auc_to_deploy}")

print("\n🧟 ALL PHASE 25 CHECKS PASSED")
