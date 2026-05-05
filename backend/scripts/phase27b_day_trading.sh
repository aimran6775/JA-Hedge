#!/usr/bin/env bash
# Phase 27b: tighten to day-trading horizons + rank-bias toward fast settlement
set -euo pipefail
cd "$(dirname "$0")/../.."

echo "==> Import check"
( cd backend && python -c "from app.main import app; print('OK')" )

echo "==> git push"
git add -A
git commit -m "phase 27b: day-trading horizon (24h learning / 168h max) + speed-rank bias

- MAX_HOURS_TO_EXPIRY_LEARNING: 72h -> 24h (intraday only while training)
- MAX_HOURS_TO_EXPIRY_TRAINED:   336h -> 168h (1 week absolute ceiling)
- scanner _rank_score now multiplies by speed_factor:
    <=12h  1.00x   <=24h 0.90x   <=72h 0.65x   else 0.45x
  so same-day markets win ties over week-out markets"
git push origin main

echo "==> railway up"
railway up --service backend || true

echo "==> sleep 90s"
sleep 90

echo "==> wipe any positions that snuck in beyond 1 week"
curl -s -X POST "https://frankensteintrading.com/api/frankenstein/paper-reset?token=PURGE_FRANKENSTEIN" | head -c 400
echo

echo "==> recovery-status"
curl -s https://frankensteintrading.com/api/frankenstein/recovery-status \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('rejections:', json.dumps(d.get('scan_rejections', {}), indent=2)); print('side_balance:', d.get('side_balance')); print('memory:', d.get('memory'))"
