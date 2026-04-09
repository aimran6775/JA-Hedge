#!/usr/bin/env python3
"""Quick production status audit."""
import json, urllib.request

BASE = "https://frankensteintrading.com"

def fetch(path):
    try:
        req = urllib.request.Request(f"{BASE}{path}", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}

# 1. Frankenstein status
d = fetch("/api/frankenstein/status")
sd = d.get("last_scan_debug", {})
print("=== Last Scan ===")
print(f"Signals: {sd.get('signals',0)}")
print(f"Candidates: {sd.get('candidates',0)}")
print(f"Executed: {sd.get('exec_successes',0)}")
print(f"Rejected: {sd.get('exec_rejections',0)}")
for c in sd.get("top_candidates", [])[:10]:
    print(f"  {c.get('stage','?'):25s}  {c.get('ticker','')}")

print(f"\nDaily trades: {d.get('daily_trades',0)} / {d.get('daily_trade_cap',0)}")
print(f"Uptime: {d.get('uptime_human','?')}")

# Categories
mem = d.get("memory", {})
ca = mem.get("category_analytics", {})
print(f"\n=== Categories (all time) ===")
for cat, s in sorted(ca.items(), key=lambda x: x[1].get("trades",0), reverse=True):
    print(f"  {cat:20s}  trades={s.get('trades',0):5d}  WR={s.get('win_rate',0):.1%}  PnL=${s.get('total_pnl',0):.2f}")

# 2. Sports status
print(f"\n=== Sports Module ===")
sp = fetch("/api/sports/status")
if "error" not in sp:
    for k, v in list(sp.items())[:15]:
        print(f"  {k}: {v}")
else:
    print(f"  {sp}")

# 3. Live engine
print(f"\n=== Live In-Game Engine ===")
le = fetch("/api/sports/live")
if "error" not in le:
    for k, v in list(le.items())[:15]:
        val = f"({len(v)} items)" if isinstance(v, (list, dict)) and len(str(v)) > 100 else v
        print(f"  {k}: {val}")
else:
    print(f"  {le}")

# 4. Recent trade tickers
print(f"\n=== Recent 20 Trades ===")
recent = fetch("/api/frankenstein/memory/recent?limit=20")
if isinstance(recent, list):
    for t in recent:
        ticker = t.get("ticker", "?")
        cat = t.get("category", "?")
        side = t.get("predicted_side", "?")
        conf = t.get("confidence", 0)
        edge = t.get("edge", 0)
        print(f"  {cat:15s}  {side:3s}  conf={conf:.2f}  edge={edge:.2f}  {ticker}")

# 5. Market count
print(f"\n=== Market Cache ===")
mkt = fetch("/api/markets?limit=1")
if "error" not in mkt:
    print(f"Total cached: {mkt.get('total', mkt.get('count', '?'))}")

# 6. Unique market types in recent trades
if isinstance(recent, list):
    tickers = [t.get("ticker","") for t in recent]
    types = set()
    for tk in tickers:
        parts = tk.split("-")
        if parts:
            prefix = parts[0]
            types.add(prefix)
    print(f"\nMarket type prefixes traded: {sorted(types)}")
