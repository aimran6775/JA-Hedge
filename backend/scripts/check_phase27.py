#!/usr/bin/env python3
"""Quick Phase 27 status check."""
import json
import urllib.request

def fetch(path):
    url = f"https://frankensteintrading.com{path}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

d = fetch("/api/frankenstein/status")
print("=== FRANKENSTEIN PHASE 27 STATUS ===")
print(f"Uptime: {d['uptime_human']}")
print(f"Model: {d['version']} gen {d['generation']}")
print(f"Learning mode: {d['learning_mode']} ({d['learning_progress']})")
print(f"Trading: {d['is_trading']}, Paused: {d['is_paused']}")
print(f"Circuit breaker: {d['circuit_breaker_active']}")
print()

print("=== TRADING ACTIVITY ===")
print(f"Total scans: {d['total_scans']}")
print(f"Total signals: {d['total_signals']}")
print(f"Daily trades: {d['daily_trades']}/{d['daily_trade_cap']}")
print(f"Total executed: {d['total_trades_executed']}")
print(f"Total rejected: {d['total_trades_rejected']}")
ls = d.get("last_scan_debug", {})
print(f"Last scan: candidates={ls.get('candidates',0)}, signals={ls.get('signals',0)}, executed={ls.get('exec_successes',0)}")
if ls.get("top_candidates"):
    for c in ls["top_candidates"][:5]:
        print(f"  {c}")
print()

c = d.get("capital", {})
print("=== CAPITAL ===")
print(f"Balance: ${c.get('balance_cents',0)/100:.2f}")
print(f"Reserved: ${c.get('reserved_cents',0)/100:.2f} ({c.get('reserved_pct')})")
print(f"Available: ${c.get('available_cents',0)/100:.2f}")
print(f"Max trade budget: ${c.get('max_trade_budget_cents',0)/100:.2f}")
print(f"Orders approved: {c.get('orders_approved',0)}")
print(f"Orders gated: {c.get('orders_gated',0)}")
dep = c.get("category_deployed", {})
if dep:
    print(f"Category deployed: {dep}")
print()

om = d.get("order_manager", {})
fr = om.get("fill_rate_stats", {})
print("=== ORDERS ===")
print(f"Pending: {om.get('pending_orders',0)}")
print(f"Placed: {fr.get('placed',0)}, Filled: {fr.get('filled',0)}, Fill rate: {om.get('fill_rate',0):.0%}")
ml = om.get("multi_level_stats", {})
print(f"Multi-level: {ml.get('multi_level_trades',0)}, Single: {ml.get('single_level_trades',0)}")
print()

ws = d.get("ws_bridge", {})
print("=== WEBSOCKET ===")
print(f"Connected: {ws.get('connected')}")
print(f"Reconnects: {ws.get('reconnect_count')}")
print(f"Ticker updates: {ws.get('ticker_updates')}")
print()

eb = d.get("event_bus", {})
print(f"=== EVENT BUS ===")
print(f"Total events: {eb.get('total_published',0)}")
ec = eb.get("event_counts", {})
for k, v in ec.items():
    print(f"  {k}: {v}")
print()

# Check rejections
try:
    rej = fetch("/api/frankenstein/debug/rejections")
    print("=== REJECTIONS ===")
    print(f"Total: {rej.get('total_rejections', 0)}")
    reasons = rej.get("rejection_reasons", {})
    if reasons:
        for r, cnt in sorted(reasons.items(), key=lambda x: -x[1])[:10]:
            print(f"  {r}: {cnt}")
    else:
        print("  (none)")
except Exception as e:
    print(f"Rejections: error - {e}")
