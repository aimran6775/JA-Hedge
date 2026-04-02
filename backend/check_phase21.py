#!/usr/bin/env python3
"""Check Frankenstein status after Phase 21 fixes."""
import json
import urllib.request

url = "http://localhost:8000/api/frankenstein/status"
data = json.loads(urllib.request.urlopen(url).read())

print("=== PAPER TRADING ===")
health = json.loads(urllib.request.urlopen("http://localhost:8000/health").read())
pt = health.get("paper_trading", {})
print(f"  Balance: ${pt.get('balance', '?')}")
print(f"  PnL: ${pt.get('pnl', '?')}")
print(f"  Trades: {pt.get('total_trades', '?')}")

print()
print("=== FRANKENSTEIN STATE ===")
print(f"  Alive: {data['is_alive']}")
print(f"  Trading: {data['is_trading']}")
print(f"  Generation: {data['generation']}")
print(f"  Scans: {data['total_scans']}")
print(f"  Trades: {data['total_trades_executed']}")
print(f"  Signals: {data['total_signals']}")

print()
print("=== CATEGORY ANALYTICS (from memory) ===")
ca = data.get("memory", {}).get("category_analytics", {})
for cat, stats in sorted(ca.items(), key=lambda x: x[1].get("trades", 0), reverse=True):
    t = stats.get("trades", 0)
    w = stats.get("wins", 0)
    l = stats.get("losses", 0)
    wr = stats.get("win_rate", 0)
    pnl = stats.get("total_pnl", 0)
    print(f"  {cat:20s} trades={t:3d} wins={w:3d} losses={l:3d} WR={wr:.1%} PnL=${pnl:.2f}")

print()
unknown = ca.get("unknown", {}).get("trades", 0)
total = sum(s.get("trades", 0) for s in ca.values())
if total > 0:
    pct = unknown / total * 100
    print(f"Unknown: {unknown}/{total} = {pct:.0f}% of trades")
    if pct < 20:
        print("FIXED: Unknown category no longer dominant!")
    else:
        print("WARNING: Unknown still high (historical data, new trades should be categorized)")

# WS Stats
ws = data.get("ws_stats", {})
if ws:
    print()
    print("=== WEBSOCKET ===")
    for k, v in ws.items():
        print(f"  {k}: {v}")

# Recent trades
print()
print("=== LAST SCAN ===")
debug = data.get("last_scan_debug", {})
for k, v in debug.items():
    if k != "top_candidates":
        print(f"  {k}: {v}")
top = debug.get("top_candidates", [])
if top:
    print(f"  top_candidates ({len(top)}):")
    for c in top[:5]:
        print(f"    {c}")

# Check recent trades for category
print()
print("=== RECENT TRADES (checking categories) ===")
try:
    trades_url = "http://localhost:8000/api/frankenstein/memory?limit=10"
    trades_data = json.loads(urllib.request.urlopen(trades_url).read())
    trades = trades_data if isinstance(trades_data, list) else trades_data.get("trades", trades_data.get("recent", []))
    for t in trades[:10]:
        ticker = t.get("ticker", "?")
        cat = t.get("category", "?")
        side = t.get("predicted_side", "?")
        edge = t.get("edge", 0)
        print(f"  {ticker:40s} cat={cat:15s} side={side} edge={edge:.3f}")
except Exception as e:
    print(f"  Could not fetch memory: {e}")
