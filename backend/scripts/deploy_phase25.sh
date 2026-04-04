#!/bin/bash
set -e
cd /Users/abdullahimran/Documents/JA\ Hedge

echo "🧟 Phase 25: Comprehensive Model Overhaul — deploying..."

# Git add, commit, push
git add -A
git commit -m "Phase 25: 20-phase model overhaul — fix churn loop, label noise, ensemble blend, training quality

CRITICAL FIXES:
1. Position churn loop: 30min hold time, learning mode holds to settlement
2. Label noise: resolver tightened (0.98/0.02 extreme, 24h/0.90 timeout)
3. Ensemble blend: ML weight 0.30→0.92 ramp (was 0.70 start with 0 data!)
4. Training quality: 50 min samples (was 20), retrain every 25 (was 10)
5. Class balance: skip training if <15% minority class

PREDICTION IMPROVEMENTS:
6. Heuristic uses alt-data: Polymarket, Vegas, crypto, news, social
7. XGBoost hyperparams: small-data path with heavy regularization
8. Sports predictor: Kalshi-only fallback re-enabled with sport base rates
9. Confidence: fee_impact weight halved, new prediction_quality factor
10. Performance tracker: should_pause actually works now

FILTER RELAXATION:
11. Cooldowns: 60s/30s (was 120s/60s)
12. Edge caps raised: sports 0.08→0.12, crypto 0.12→0.15, +50% in learning
13. Diversification: 3/event (was 2), 10/category (was 6)
14. Daily cap: 300 (was 150)
15. Min grade: B+ (was A), min edge: 0.04 (was 0.05)
16. Scan interval: 20s (was 30s)
17. Max positions: 80 (was 50)
18. Kelly: fixed 1-2 contracts in learning mode (was meaningless Kelly)
19. Edge reversal: requires 0.90 conf + trained model (was 0.80 untrained)
20. Maker exit: learning mode = catastrophic stop only (-50%)"

git push origin main

echo "✅ Phase 25 pushed to origin/main"
echo "⏳ Railway will auto-deploy. Wait 90s then check health."
