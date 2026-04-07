#!/usr/bin/env python3
"""Check requote stats on production."""
import json
import urllib.request

url = "https://frankensteintrading.com/api/frankenstein/status"
with urllib.request.urlopen(url, timeout=15) as resp:
    d = json.loads(resp.read())

print(f"Generation: {d.get('generation')}")
print(f"Version: {d.get('version')}")
print(f"Uptime: {d.get('uptime_human')}")
print(f"Total scans: {d.get('total_scans')}")
print(f"Total trades: {d.get('total_trades_executed')}")
print()

om = d.get("order_manager", {})
print("=== ORDER MANAGER ===")
print(f"  pending_orders: {om.get('pending_orders')}")
fr = om.get("fill_rate_stats", {})
print(f"  placed: {fr.get('placed')}, filled: {fr.get('filled')}, amended: {fr.get('amended')}")
print(f"  fill_rate: {om.get('fill_rate', 0):.1%}")
rq = om.get("requote_stats", {})
print(f"  requotes_attempted: {rq.get('requotes_attempted')}")
print(f"  requotes_succeeded: {rq.get('requotes_succeeded')}")
print(f"  requotes_skipped_edge: {rq.get('requotes_skipped_edge')}")
print(f"  requotes_skipped_delta: {rq.get('requotes_skipped_delta')}")
print(f"  requotes_cancelled_edge: {rq.get('requotes_cancelled_edge')}")
fp = om.get("fill_predictor", {})
print()
print("=== FILL PREDICTOR ===")
print(f"  observations: {fp.get('observations')}")
print(f"  fills: {fp.get('fills')}")
print(f"  cancels: {fp.get('cancels')}")
print(f"  model_active: {fp.get('model_active')}")
print(f"  model_fitted: {fp.get('model_fitted')}")

# Check paper trading balance
url2 = "https://frankensteintrading.com/health"
with urllib.request.urlopen(url2, timeout=15) as resp:
    h = json.loads(resp.read())
pt = h.get("paper_trading", {})
print()
print("=== PAPER TRADING ===")
print(f"  balance: ${pt.get('balance')}")
print(f"  pnl: ${pt.get('pnl')}")
print(f"  total_trades: {pt.get('total_trades')}")
