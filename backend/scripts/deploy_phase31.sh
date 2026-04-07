#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."

echo "=== Phase 31: 20-Phase Overhaul Deploy ==="
echo ""
echo "Files changed:"
git status --short
echo ""

# Stage all
git add -A

# Commit
git commit -m "Phase 31: 20-phase overhaul — arb engine, bootstrap removal, calibration reset, fill predictor, exit logic, requoting fix

Critical fixes:
- NEW: arb_engine.py — cross-platform arbitrage (Polymarket/Vegas/crypto/FRED vs Kalshi)
- FIX: Bootstrap DISABLED — was poisoning XGBoost with 500 fake crypto trades (92% WR)
- FIX: Calibration reset on stale checkpoint — 0% accuracy across all bins cleared
- FIX: Paper trader amend_order — requoting was 0/1021 (now functional)
- FIX: Fill predictor activation — paper fills now train SGD model
- FIX: V1 sports fallback DISABLED — 3.7% WR hemorrhaging money
- FIX: Adaptation guard raised 100→500 trades — stops death spiral (17 adaptations/hr)

New capabilities:
- ArbScanner: bypasses ML for direct price arb (6% Poly, 5% Vegas, 8% crypto edges)
- Sibling market arb: probability sum violation detection (>1.10 or <0.90)
- Intelligence-driven position exits (pay 7¢ when external source says run)
- Momentum exit: 4+ consecutive adverse price moves + >15% unrealized loss
- Model trains ONLY on real resolved trades (source=='live')

Files: arb_engine.py(new), scanner.py, brain.py, strategy.py, paper_trader.py,
       positions.py, order_manager.py, models.py, check_recent_trades.py(new)"

# Push
git push origin main

echo ""
echo "=== Deployed! Wait 90s then check health ==="
