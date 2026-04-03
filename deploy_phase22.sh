#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "=== 1. Kill old server ==="
kill $(lsof -t -i :8000) 2>/dev/null || true
sleep 2
echo "   Done"

echo "=== 2. Start fresh server ==="
cd backend
nohup ~/.jahedge-venv/bin/python run_server.py > /tmp/jahedge-server.log 2>&1 &
echo "   PID: $!"
cd ..

echo "=== 3. Wait for startup ==="
sleep 8
curl -s http://localhost:8000/health | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'   Status: {d[\"status\"]}, Frankenstein: {d[\"components\"][\"frankenstein\"]}')"

echo "=== 4. Commit & push ==="
git add -A
git commit -m "fix: Phase 22 \u2014 5 accuracy root causes

Root cause analysis from 1,192 trades (31.1% WR, -\$157.72 PnL):

1. Toxic market blacklist: blocked KXEPLGOAL (2% WR), KXEPLFIRSTGOAL (5%),
   KXMVECROSSCATEGORY (5%), KXNCAAMB1HSPREAD (13%), KXQUICKSETTLE (34%),
   and 15-min crypto (unpredictable coin flips). Both full scan and reactive.

2. Edge floor raised: learning-mode min edge 0.03\u21920.06. Absolute floor of
   0.04 for ALL trades. Data: 443 trades at edge\u22480 had 22% WR (coin flips),
   62 trades at edge\u22650.05 had 95% WR.

3. Faster outcome resolution: extreme price threshold 0.99/0.01\u21920.95/0.05.
   Timeout reduced 48h\u21926h with price-based resolution (was: 45.6% expired).

4. Circuit breaker tuning: min trades 30\u219215 (faster trip), cooldown 4h\u21922h
   (faster recovery).

5. Diagnosis tooling: diagnose_accuracy.py for ongoing monitoring."

echo "   Committed"
git push origin main
echo "   Pushed"

echo ""
echo "=== DONE. Server running locally + Railway deploy triggered. ==="
