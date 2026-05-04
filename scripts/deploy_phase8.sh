#!/usr/bin/env bash
# Phase 8: Decimal/float fix + paper-reset endpoint + raise position cap.
set -e
cd "$(dirname "$0")/.."
git add -A
git commit -m "fix(phase 8): Decimal/float exec bug + paper-reset + raise pos cap to absorb carryover

- advanced_risk.py: float() coerce all division operands (was throwing
  Decimal/float TypeError on every trade attempt)
- paper_trader.py: _to_cents handles Decimal correctly (any numeric)
- order_manager.py: log full traceback on execution_failed
- strategy.py: max_simultaneous_positions 30 -> 150 (absorb 66 carryover)
- routes/frankenstein.py: POST /paper-reset (token-gated) wipes paper
  positions + advanced_risk position registry
"
git push origin main
echo "==> waiting 100s for redeploy..."
sleep 100

HOST="https://frankensteintrading.com"

echo "==> paper-reset"
curl -fsS -X POST "$HOST/api/frankenstein/paper-reset?token=PURGE_FRANKENSTEIN" | python3 -m json.tool || true

echo
echo "==> recovery-status"
curl -fsS "$HOST/api/frankenstein/recovery-status" | python3 -m json.tool

echo
echo "==> waiting 60s then check status for trade flow..."
sleep 60
curl -fsS "$HOST/api/frankenstein/status" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f\"trades_executed: {d.get('total_trades_executed')}\")
print(f\"trades_rejected: {d.get('total_trades_rejected')}\")
print(f\"daily_trades:    {d.get('daily_trades')}/{d.get('daily_trade_cap')}\")
print(f\"open_positions:  {d.get('last_scan_debug',{}).get('open_positions')}\")
print(f\"max_per_scan:    {d.get('last_scan_debug',{}).get('max_trades')}\")
top = d.get('last_scan_debug',{}).get('top_candidates',[])
for c in top[:3]:
    print(f\"  candidate: {c}\")
"
