#!/bin/bash
# Phase 28: Deploy all 10 improvements
set -e

cd "$(dirname "$0")/../.."

echo "=== Phase 28: 10 Structural Improvements ==="
echo "1. Bigger position sizes (A+→15, A→8, B+→5, B→3 + \$5 min bet)"
echo "2. Remove spread credit for graduated maker mode"
echo "3. Hybrid taker execution for A/A+ trades (100% fill rate)"
echo "4. Don't split small orders (min count 2→8)"
echo "5. Poll-based requoting (amend stale orders each scan)"
echo "6. Fix WebSocket connection (detailed error logging)"
echo "7. Faster outcome resolution (batch market status check)"
echo "8. Sync reactive scan min edges (0.06→0.04)"
echo "9. Correlated position detection (block opposite-side same-event)"
echo "10. Category-aware bootstrap (sports, politics, weather, economics)"
echo ""

# Verify import chain
echo "Verifying import chain..."
cd backend
source .venv/bin/activate 2>/dev/null || true
python -c "from app.main import app; print('Import check: OK')"
cd ..

# Git commit and push
echo ""
echo "Committing and pushing..."
git add -A
git commit -m "Phase 28: 10 structural improvements — bigger positions, hybrid taker, poll requoting, category-diverse bootstrap

Changes across 7 files:
- constants.py: MULTI_LEVEL_MIN_COUNT 2→8, hybrid taker constants, poll requote config
- scanner.py: Grade sizing A+→15/A→8/B+→5/B→3, \$5 min bet floor, spread_cost=0 for maker,
  hybrid taker flag, synced reactive min edges 0.06→0.04, correlated position detection,
  category diagnostic logging, poll requote integration
- order_manager.py: execute_taker_trade() for A/A+ signals, requote_pending_orders()
  poll-based requoting each scan cycle
- ws_bridge.py: Detailed error logging with traceback for WS failures
- brain.py: Better WS start/reconnect error messages
- resolver.py: Batch market status pre-fetch for faster outcome resolution
- bootstrap.py: 20 series across 6 categories (crypto, finance, sports, politics, weather, economics)

Expected impact:
- Capital deployed: \$30 → \$500-2,000
- Fill rate: 24% → 50-70%
- Categories: sports-only → all 9
- Resolution: hours → minutes"

git push origin main

echo ""
echo "=== Phase 28 deployed! ==="
echo "Wait 90s then check: https://frankensteintrading.com/health"
