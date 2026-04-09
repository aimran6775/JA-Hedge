#!/usr/bin/env python3
"""Count Kalshi events and their market types."""
import json
import urllib.request

BASE = "https://api.elections.kalshi.com/trade-api/v2"

total_events = 0
series_counts = {}
cursor = None
page = 0

while page < 100:
    url = f"{BASE}/events?limit=200&status=open&with_nested_markets=false"
    if cursor:
        url += f"&cursor={cursor}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read())
    events = d.get("events", [])
    cursor = d.get("cursor", "")
    total_events += len(events)
    for e in events:
        st = e.get("series_ticker", "")
        cat = e.get("category", "unknown")
        series_counts[cat] = series_counts.get(cat, 0) + 1
    page += 1
    if not cursor or not events:
        break

print(f"Total events: {total_events} (in {page} pages)")
print(f"\nBy category:")
for c, n in sorted(series_counts.items(), key=lambda x: -x[1]):
    print(f"  {c:30s}  {n}")
