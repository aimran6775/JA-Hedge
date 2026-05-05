#!/usr/bin/env bash
# Phase 27: cap MAX hours-to-expiry so bot stops buying 2029-2030 futures
# that never resolve, blocking the training loop.
set -euo pipefail
cd "$(dirname "$0")/../.."

echo "==> Import check"
( cd backend && python -c "from app.main import app; print('OK')" )

echo "==> git commit + push"
git add -A
git commit -m "phase 27: cap max hours-to-expiry (72h learning / 336h trained)

- bot was burning daily trade cap on 2029-2030 entertainment/political
  futures (KXTRUMPPARDONS-29*, BEYONCEGENRE-30*, KXTAYLORSWIFTWEDDING-30*)
  that never resolve in our lifetime → 0/200 trades labeled → model
  stays untrained forever, learning loop blocked
- new constants MAX_HOURS_TO_EXPIRY_LEARNING=72 / TRAINED=336
- enforced in scanner._pre_filter, surfaces as scan_rejections.max_expiry_ceiling"
git push origin main

echo "==> railway up (deploy)"
railway up --service backend || true

echo "==> sleep 90s for deploy"
sleep 90

echo "==> wipe stale long-dated paper positions"
curl -s -X POST "https://frankensteintrading.com/api/frankenstein/paper-reset?token=PURGE_FRANKENSTEIN" | head -c 600
echo

echo "==> health"
curl -s https://frankensteintrading.com/health | head -c 400
echo

echo "==> recovery-status (look for max_expiry_ceiling counter)"
curl -s https://frankensteintrading.com/api/frankenstein/recovery-status \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(json.dumps(d.get('scan_rejections', {}), indent=2)); print('side_balance:', d.get('side_balance'))"
