#!/usr/bin/env python3
"""Deep check of live server - full JSON dump of key endpoints."""
import json
import urllib.request

BASE = "https://frankensteintrading.com"

def fetch(path):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=15) as r:
        return json.loads(r.read())

# Full status - dump everything
print("=" * 60)
print("FULL STATUS JSON (key fields)")
print("=" * 60)
st = fetch("/api/frankenstein/status")

# Print all top-level keys
print(f"Top-level keys: {list(st.keys())}")

# Active positions detail
print(f"\n--- Active positions ---")
print(json.dumps(st.get("active_positions"), indent=2, default=str))

# Open orders
print(f"\n--- Open orders ---")
print(json.dumps(st.get("open_orders"), indent=2, default=str))

# Exchange session
print(f"\n--- Exchange ---")
print(json.dumps(st.get("exchange_session"), indent=2, default=str))

# WS Bridge
print(f"\n--- WS Bridge ---")
print(json.dumps(st.get("ws_bridge"), indent=2, default=str))

# Memory detail
print(f"\n--- Memory ---")
print(json.dumps(st.get("memory"), indent=2, default=str))

# Full paper trading info
print(f"\n--- Paper trading ---")
print(json.dumps(st.get("paper_trading"), indent=2, default=str))

# Scanner
print(f"\n--- Scanner ---")
print(json.dumps(st.get("scanner"), indent=2, default=str))

# Capital
print(f"\n--- Capital ---")
print(json.dumps(st.get("capital"), indent=2, default=str))

# Dashboard overview for more context
print(f"\n\n{'='*60}")
print("DASHBOARD OVERVIEW")
print("=" * 60)
try:
    dash = fetch("/api/dashboard/overview")
    print(json.dumps(dash, indent=2, default=str)[:3000])
except Exception as e:
    print(f"Dashboard error: {e}")

# Paper trading simulator state
print(f"\n\n{'='*60}")
print("PAPER TRADING STATE")
print("=" * 60)
try:
    # Check if there's a specific paper trading endpoint
    paper = fetch("/api/portfolio/fills?limit=50")
    fills = paper if isinstance(paper, list) else paper.get("fills", [])
    # Group by ticker
    ticker_fills = {}
    for f in fills:
        t = f.get("ticker", "?")
        if t not in ticker_fills:
            ticker_fills[t] = []
        ticker_fills[t].append(f)
    
    print(f"Total fills: {len(fills)}")
    print(f"Unique tickers in fills: {len(ticker_fills)}")
    for t, fl in list(ticker_fills.items())[:5]:
        print(f"\n  {t}: {len(fl)} fills")
        for f in fl[:3]:
            print(f"    side={f.get('side')} action={f.get('action')} yes_px={f.get('yes_price')} no_px={f.get('no_price')} ct={f.get('count')} @ {str(f.get('created_time',''))[:19]}")
except Exception as e:
    print(f"Paper fills error: {e}")
