#!/usr/bin/env python3
"""Check raw market data from Kalshi API to see if prices exist."""
import json
import urllib.request

BASE = "https://frankensteintrading.com"

def fetch(path):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=30) as r:
        return json.loads(r.read())

# Check the raw markets endpoint for markets with actual prices
print("=== Markets with volume (should have prices) ===")
data = fetch("/api/markets?limit=20&sort_by=volume")
for m in data.get("markets", [])[:20]:
    t = m.get("ticker", "?")[:45]
    print(f"  {t:45s} bid={m.get('yes_bid','?'):>5} ask={m.get('yes_ask','?'):>5} mid={m.get('midpoint','?'):>5} vol={m.get('volume','?'):>8} last={m.get('last_price','?'):>5} spread={m.get('spread','?')}")

print()
print("=== Market data pipeline status ===")
h = fetch("/health")
print(f"  Pipeline: {h.get('components', {}).get('market_pipeline', 'unknown')}")

# Check if there's a pipeline debug endpoint
try:
    pipe = fetch("/api/dashboard")
    print(f"  Dashboard data: {list(pipe.keys())[:10]}")
    if "markets" in pipe:
        md = pipe["markets"]
        print(f"  Markets in dashboard: {json.dumps(md, indent=2)[:500]}")
except Exception as e:
    print(f"  Dashboard: {e}")

# Check Frankenstein's last scan for more detail
print()
print("=== Frankenstein scan detail ===")
st = fetch("/api/frankenstein/status")
lsd = st.get("last_scan_debug", {})
print(f"  Exit: {lsd.get('exit')}")
print(f"  Active markets: {lsd.get('active_markets')}")
for k, v in lsd.items():
    if k not in ("exit", "active_markets"):
        print(f"  {k}: {v}")

# Try to find markets with actual prices
print()
print("=== Searching for ANY market with bid > 0 ===")
# Try different sorting/filtering
for endpoint in [
    "/api/markets?limit=10&sort_by=volume",
    "/api/markets?limit=10",
]:
    data = fetch(endpoint)
    priced = [m for m in data.get("markets", []) if (m.get("yes_bid") or 0) > 0]
    print(f"  {endpoint}: {len(priced)} have bid>0 out of {len(data.get('markets',[]))}")
    for m in priced[:3]:
        print(f"    {m['ticker'][:40]:40s} bid={m['yes_bid']} ask={m['yes_ask']} mid={m['midpoint']} vol={m['volume']}")
