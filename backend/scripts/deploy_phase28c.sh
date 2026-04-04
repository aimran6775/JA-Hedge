#!/bin/bash
# Phase 28c: Fix risk limits + Kelly aggressiveness
# - Railway env vars already updated: RISK_MAX_POSITION_SIZE=50, RISK_MAX_DAILY_LOSS=500, RISK_MAX_PORTFOLIO_EXPOSURE=5000
# - Code defaults synced: position size 50 in config.py, strategy.py, risk.py
# - Kelly sizing: removed +0.01 buffer in maker mode (use bid directly)
# - Debug endpoint: added error handling + response cap

set -e
cd "$(dirname "$0")/.."

echo "=== Phase 28c: Risk limits + Kelly fix ==="
echo "Changed files:"
git diff --stat

echo ""
echo "Committing..."
git add -A
git commit -m "Phase 28c: fix risk limits (was 10, now 50) + Kelly aggressiveness for maker mode

Railway env vars were overriding code defaults:
- RISK_MAX_POSITION_SIZE: 10 -> 50
- RISK_MAX_DAILY_LOSS: 50 -> 500
- RISK_MAX_PORTFOLIO_EXPOSURE: 500 -> 5000

Code fixes:
- config.py, strategy.py, risk.py: defaults to 50 contracts
- scanner.py: Kelly uses bid directly in maker mode (was bid+0.01, filtering good signals)
- routes/frankenstein.py: debug/rejections error handling + cap at 20 results"

echo ""
echo "Pushing..."
git push origin main

echo ""
echo "✅ Phase 28c deployed. Railway will auto-deploy."
echo "Note: Railway env vars already updated separately."
