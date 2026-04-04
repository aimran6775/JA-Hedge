#!/usr/bin/env python3
"""Check Phase 28 status."""
import json
import urllib.request

url = "https://frankensteintrading.com/api/frankenstein/status"
with urllib.request.urlopen(url) as r:
    d = json.loads(r.read())

print("=== Phase 28b Status ===")
print(f"Uptime: {d['uptime_human']}")
print(f"Scans: {d['total_scans']}")
print(f"Signals: {d['total_signals']}")
print(f"Trades Executed: {d['total_trades_executed']}")
print(f"Trades Rejected: {d['total_trades_rejected']}")
print(f"Daily Trades: {d['daily_trades']}/{d['daily_trade_cap']}")
print(f"Learning Mode: {d['learning_mode']}")

lsd = d["last_scan_debug"]
print(f"\n--- Last Scan ---")
print(f"Candidates: {lsd.get('candidates', 0)}")
print(f"Trade Candidates: {lsd.get('trade_candidates', 0)}")
print(f"Exec Successes: {lsd.get('exec_successes', 0)}")
print(f"Portfolio Rejections: {lsd.get('portfolio_rejections', 0)}")
print(f"Exec Rejections: {lsd.get('exec_rejections', 0)}")
print(f"Scan ms: {lsd.get('ms', 0)}")

om = d.get("order_manager", {})
print(f"\n--- Order Manager ---")
print(f"Pending Orders: {om.get('pending_orders', 0)}")
frs = om.get("fill_rate_stats", {})
print(f"Placed: {frs.get('placed', 0)}")
print(f"Filled: {frs.get('filled', 0)}")
print(f"Amended: {frs.get('amended', 0)}")
fr = om.get("fill_rate", 0)
print(f"Fill Rate: {fr:.1%}")

# Top candidates
for tc in lsd.get("top_candidates", [])[:5]:
    print(f"  {tc}")

# Paper trading
url2 = "https://frankensteintrading.com/health"
with urllib.request.urlopen(url2) as r2:
    h = json.loads(r2.read())
pt = h.get("paper_trading", {})
print(f"\n--- Paper Trading ---")
print(f"Balance: ${pt.get('balance', '?')}")
print(f"PnL: ${pt.get('pnl', '?')}")
print(f"Total Trades: {pt.get('total_trades', '?')}")
