#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
( cd backend && python -c "from app.main import app; print('OK')" )
git add -A
git commit -m "phase 27d: 1-week ceiling for both modes (96h starved candidate pool)

Bot's actual market universe doesn't have enough <4-day binaries to feed
the daily cap. User requirement is 1-week max anyway. Speed-rank bias
in _rank_score still strongly prefers same-day markets so day-trading
priority is preserved without starving the bot."
git push origin main
railway up --service backend || true
echo "==> sleep 120s for full rebuild"
sleep 120
echo "==> health"
curl -s https://frankensteintrading.com/health | python3 -c "import json,sys;print(json.load(sys.stdin).get('paper_trading'))"
echo "==> status"
curl -s https://frankensteintrading.com/api/frankenstein/status | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('uptime_h:', round(d.get('uptime_seconds',0)/3600,2))
print('scans:', d.get('total_scans'),'signals:',d.get('total_signals'),'trades:',d.get('total_trades_executed'))
print('last_scan:', d.get('last_scan_debug'))
"
echo "==> recovery"
curl -s https://frankensteintrading.com/api/frankenstein/recovery-status | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('memory:',d.get('memory'))
print('side:',d.get('side_balance'))
print('rejections:',d.get('scan_rejections'))
"
