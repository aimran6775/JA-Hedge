#!/usr/bin/env python3
"""Check total Kalshi active markets by paginating directly."""
import json
import urllib.request

BASE = "https://api.elections.kalshi.com/trade-api/v2"

total = 0
mve = 0
individual = 0
cat_counts = {}
cursor = None
page = 0

while page < 200:
    url = f"{BASE}/markets?limit=1000&status=open"
    if cursor:
        url += f"&cursor={cursor}"
    
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read())
    
    markets = d.get("markets", [])
    cursor = d.get("cursor", "")
    total += len(markets)
    
    for m in markets:
        t = m.get("ticker", "").upper()
        if t.startswith(("KXMVE", "KXPARLAY", "KXSPOTSTREAMGLOBAL")):
            mve += 1
        else:
            individual += 1
            cat = m.get("category", "unknown")
            cat_counts[cat] = cat_counts.get(cat, 0) + 1
    
    page += 1
    print(f"Page {page}: +{len(markets)} (total={total}, MVE={mve}, individual={individual})")
    
    if not cursor or not markets:
        break

print(f"\n=== TOTALS ===")
print(f"Total active: {total}")
print(f"MVE/parlay:   {mve}")
print(f"Individual:   {individual}")
print(f"\nCategories:")
for c, n in sorted(cat_counts.items(), key=lambda x: -x[1]):
    print(f"  {c:25s}  {n}")
