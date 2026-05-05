#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
( cd backend && python -c "from app.main import app; print('OK')" )
git add -A
git commit -m "phase 27c: relax learning ceiling 24h->96h (bot was starved of candidates)

24h dropped 126k candidates and produced 0 trades. Most Kalshi markets
(politics, econ, weather) settle 2-7 days out. Speed-rank bias still
strongly prefers same-day (<12h=1.0x, <24h=0.9x, <72h=0.65x, else 0.45x)
so day-trading priority is preserved."
git push origin main
railway up --service backend || true
sleep 90
echo "==> health"
curl -s https://frankensteintrading.com/health | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['paper_trading'])"
echo "==> recovery"
curl -s https://frankensteintrading.com/api/frankenstein/recovery-status | python3 -c "import json,sys; d=json.load(sys.stdin); print('memory:',d.get('memory')); print('side:',d.get('side_balance')); print('rejections:',d.get('scan_rejections'))"
echo "==> status"
curl -s https://frankensteintrading.com/api/frankenstein/status | python3 -c "import json,sys; d=json.load(sys.stdin); print('uptime_h:',round(d.get('uptime_seconds',0)/3600,2),'scans:',d.get('total_scans'),'trades:',d.get('total_trades_executed'),'daily:',d.get('daily_trades'))"
