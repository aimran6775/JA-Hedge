#!/bin/bash
set -e
cd "$(dirname "$0")/../.."

echo "=== Phase 26: Synchronous Startup Bootstrap ==="
echo "Changes:"
echo "  1. brain.py: _startup_bootstrap() replaces fire-and-forget _auto_bootstrap()"  
echo "  2. bootstrap.py: Multi-series _fetch_settled_markets() for diverse training data"
echo "  3. brain.py: bootstrap_training_data() targets 500/2000 (up from 300/1000)"
echo ""

# Verify import
echo ">>> Verifying imports..."
cd backend
python -c "from app.main import app; print('Import OK')"
cd ..

# Commit and push
echo ">>> Committing..."
git add -A
git commit -m "Phase 26: synchronous startup bootstrap — XGBoost trained from settled markets before first scan

- Replace fire-and-forget _auto_bootstrap with synchronous _startup_bootstrap
- Clean stale memory on startup (old churn trades without labels)  
- Multi-series bootstrap: BTC/ETH 15m, BTC/ETH daily, Nasdaq, S&P500 + generic
- Target 500+ labeled records from 2000 settled markets
- Train XGBoost with walk-forward CV before scan loop starts
- Model is always ready from first trade opportunity
- Fall back to heuristic only if network/API failure"

echo ">>> Pushing..."
git push origin main

echo ""
echo "=== Deploy initiated. Monitor Railway for build status ==="
echo "After ~90s, check: curl https://frankensteintrading.com/health"
echo "Then check model: curl https://frankensteintrading.com/api/frankenstein/status | python3 -m json.tool | grep -A5 learner"
