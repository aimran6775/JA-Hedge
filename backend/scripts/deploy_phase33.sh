#!/bin/bash
set -e
cd /Users/abdullahimran/Documents/JA\ Hedge

echo "=== Phase 33: Full Platform Trading + Live Engine ==="
echo ""
echo "Changes:"
echo "  1. Live in-game engine wired into scanner (score arb, momentum, garbage time)"
echo "  2. Brain uses 15s scan interval during live games (was 30s)"
echo "  3. Pipeline now fetches via events endpoint — gets ALL market types"
echo "     (crypto, politics, weather, science, finance, etc.) instead of"
echo "     only 171 sports markets from the old 200K-market MVE pagination wall"
echo "  4. Live engine stats added to status endpoint"
echo ""

git add -A && git commit -m "Phase 33: Wire live in-game engine + fetch all market types via events

- LiveTradingEngine.analyze() now called during scan for live sports
  markets: score arb, momentum scalp, garbage time, halftime signals
  boost prediction confidence and can flip trade direction
- Brain scan loop: 15s interval during live games (was 30s always)
- Pipeline: switch from /markets pagination (200K entries, 99% MVE
  parlay bloat, only found 171 individual markets) to /events with
  nested markets (clean, no MVE, gets ALL ~1400 individual markets)
- Scanner: _live_engine attribute wired through brain._wire_sports()
- Status: live_engine stats exposed in /api/frankenstein/status" && git push origin main

echo ""
echo "Deployed! Waiting 90s for Railway to pick up..."
sleep 90

echo ""
echo "=== Verifying ==="
curl -s https://frankensteintrading.com/health | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'Status: {d.get(\"status\")}')
print(f'Paper: {d.get(\"paper_trading\",{}).get(\"balance\")} (trades: {d.get(\"paper_trading\",{}).get(\"total_trades\")})')
"

echo ""
echo "=== Market Cache ==="
curl -s "https://frankensteintrading.com/api/markets?limit=1" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'Total cached: {d.get(\"total\", \"?\")}')
"

echo ""
echo "=== Market Type Distribution ==="
curl -s "https://frankensteintrading.com/api/markets?limit=500" | python3 -c "
import json, sys
d = json.load(sys.stdin)
markets = d.get('markets', [])
prefixes = {}
for m in markets:
    t = m.get('ticker', '')
    prefix = t.split('-')[0] if '-' in t else t[:10]
    prefixes[prefix] = prefixes.get(prefix, 0) + 1
for p, c in sorted(prefixes.items(), key=lambda x: -x[1])[:20]:
    print(f'  {p:35s}  {c}')
"

echo ""
echo "=== Frankenstein Status ==="
curl -s https://frankensteintrading.com/api/frankenstein/status | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'Alive: {d.get(\"is_alive\")}')
print(f'Trading: {d.get(\"is_trading\")}')
print(f'Daily trades: {d.get(\"daily_trades\")}')
le = d.get('live_engine')
if le:
    print(f'Live engine: {le}')
else:
    print('Live engine: not available')
"
