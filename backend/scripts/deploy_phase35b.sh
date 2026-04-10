#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."

echo "=== Phase 35b: Disable LLM, add features + harvester, tune LightGBM ==="

# Verify imports
source .venv/bin/activate
python -c "from app.main import app; print('Import check: OK')"

# Commit and push
cd ..
git add -A
git commit -m "Phase 35b: Disable LLM, add category+interaction features (90 total), market outcome harvester for 10-50x training data, tune LightGBM for ensemble diversity

Changes:
- Disable LLM by default (llm_enabled=False) - saves ~\$40-50/day
- Redistribute ensemble weights: XGB+LR 50%, LightGBM 35%, baseline 10%
- Add category_id feature (ordinal encoding: politics=1..legal=12)
- Add 6 interaction features: vol_confirmed_move, rsi_time_signal,
  convergence_urgency, momentum_regime, spread_edge, ext_disagreement
- New MarketHarvester module: snapshots ALL scan candidates, harvests
  resolved markets as free training data (10-50x data increase)
- Wire harvester into scanner (snapshot), resolver (harvest settlements),
  learner (blend harvest data at 0.5 weight), brain (create+status)
- Tune LightGBM: DART boosting, 31 leaves, extra_trees, different seed
  for genuine ensemble diversity vs XGBoost"
git push origin main

echo "=== Pushed to main. Railway will auto-deploy. ==="
