#!/bin/bash
set -e
cd /Users/abdullahimran/Documents/JA\ Hedge

git add -A
git commit -m "Phase 34: Fix exit-trade memory pollution, slow down trade burn rate, disable retirement

Root causes found via live production audit:
- ALL 30 recent trades showed conf=0.00, edge=0.000 — these were EXIT
  trade records (model_version='exit') not real entry predictions
- Same tickers exited 5-9x because maker fill probability (15-40%) left
  positions open, and position manager re-attempted exit every cycle
- Daily trade cap of 500 hit in 30 minutes with 41K markets available
- Sports category auto-retired despite +\$14 PnL

Fixes:
1. order_manager.py: Remove memory.record_trade() from execute_exit()
   - Exit records (conf=0, edge=0) were polluting trade memory
   - Resolver tracks outcomes on original entry — exits don't need entries

2. positions.py: Add exit cooldown (5 min) to prevent exit re-attempts
   - Track \$_exit_cooldown dict: ticker → last attempt timestamp
   - Skip tickers with recent exit attempts

3. constants.py: Reduce MAX_DAILY_TRADES 500→200
   - At 500, system burned through cap in 30 minutes
   - 200 spreads capital more carefully over full trading day

4. scanner.py: Reduce max trades/scan 12→5, increase cooldowns
   - Ticker cooldown 30s→120s (prevent rapid re-entry)
   - Event cooldown 15s→60s
   - Max 5 trades per scan cycle (was 12)

5. brain.py: Disable category retirement entirely
   - Was retiring profitable categories (sports at +\$14 PnL)
   - Quality gates (confidence, edge, features) are the real filters
   - Force-unretire all categories every snapshot cycle"

git push origin main
