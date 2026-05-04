#!/usr/bin/env bash
# Phase 14: predictor bias fix + DB relationship fix
# Verify import + commit + push + deploy
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== Verifying import chain ==="
python -c "from app.main import app; print('OK app imports')"
python -c "from app.ai.models import XGBoostPredictor; from app.ai.ensemble import EnsemblePredictor; print('OK predictors')"
python -c "from app.db.models import MarketRecord, PriceSnapshot; print('OK db models')"

echo "=== Committing ==="
cd ..
git add -A
git commit -m "Phase 14: rebuild heuristic predictor (kill YES bias) + fix DB relationship

- Drop convergence_adj/RSI/MACD/volume noise stacking from _heuristic_predict
  (these were the YES-bias source — convergence_adj specifically pushes
  high-mid markets further toward YES, and Kalshi market distribution
  skews mid > 0.5)
- Heuristic now: alt-data present -> use it; absent -> prob_yes = mid
  (edge=0 -> trade gated by min_edge filter, no spurious signal)
- _build_prediction: require |edge| >= MIN_DECISIVE_EDGE to commit to a
  non-neutral side; below threshold -> 'no' with near-zero confidence
- Add side-balance feedback to predictor: when recent trades skew >70%
  one side, predictor nudges prob away from dominant side (soft prior)
- Fix MarketRecord.price_snapshots relationship: add viewonly=True
  since ticker is not a real foreign key (eliminates SA mapper warning
  that was blocking some DB persists)" || echo "(nothing to commit)"
git push origin main
echo "=== Pushed. Railway will redeploy automatically ==="
