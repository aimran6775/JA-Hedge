#!/bin/bash
cd /Users/abdullahimran/Documents/JA\ Hedge

git reset HEAD 2>/dev/null
git add -A

git commit -m 'fix: paper trading persistence + spread limits + category rebalance

Phase 32: survive redeploys + maximize profitability

1. Paper trading persistence (critical):
   - PaperTradingSimulator.save/load_state_to_file() to PERSIST_DIR
   - main.py: load on startup, save on shutdown
   - brain.py: periodic save every 60s during scan loop
   - Balance, positions, stats all survive Railway redeploys

2. Spread recheck widened for maker mode:
   - scanner.py: spread_recheck 55->95c for maker (we CREATE liquidity)
   - config.py: risk_max_spread_cents 55->95
   - Was rejecting valid candidates (spread 64 > limit 55)

3. Category capital rebalanced from actual performance:
   - Crypto: 12->25% (92pct WR, best category)
   - Science: 5->12% (positive PnL)
   - Sports: 30->15% (break-even on 1504 trades)
   - Politics: 12->4% (negative PnL)
   - Weather: 8->3% (negative PnL)'

git push origin main
