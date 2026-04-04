#!/usr/bin/env python3
"""Detailed filter analysis - see where every market is being rejected."""
import json
import urllib.request

BASE = "https://frankensteintrading.com"

def fetch(path):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=30) as r:
        return json.loads(r.read())

# Fetch a good sample of markets
print("Fetching markets...")
data = fetch("/api/markets?limit=200&status=active")
markets = data.get("markets", [])
print(f"Got {len(markets)} markets (total active: {data.get('total', '?')})")

# Simulate _filter_candidates logic
JUNK_PREFIXES = (
    "KXMVE", "KXSPOTSTREAMGLOBAL", "KXPARLAY",
    "KXEPLGOAL", "KXEPLFIRSTGOAL",
    "KXMVECROSSCATEGORY",
    "KXNCAAMB1HSPREAD",
    "KXQUICKSETTLE",
    "KXBTC15M", "KXETH15M", "KXSOL15M", "KXDOGE15M", "KXXRP15M",
    "KXADA15M", "KXAVAX15M", "KXLINK15M", "KXDOT15M", "KXMATIC15M",
)

MAX_SPREAD_CENTS = 15  # from strategy.py
MIN_VOLUME = 2  # from scanner.py filter (lowered from 5)

counters = {
    "total": 0,
    "junk_prefix": 0,
    "no_prices": 0,
    "no_spread": 0,
    "spread_too_wide": 0,
    "no_bids_asks": 0,
    "mid_extreme": 0,
    "low_volume": 0,
    "spread_pct_too_high": 0,
    "PASSED": 0,
}

spread_values = []
volume_values = []
mid_values = []

for m in markets:
    counters["total"] += 1
    ticker = (m.get("ticker") or "").upper()
    
    # Junk prefix
    if any(ticker.startswith(p) for p in JUNK_PREFIXES):
        counters["junk_prefix"] += 1
        continue
    
    bid = m.get("yes_bid") or 0
    ask = m.get("yes_ask") or 0
    last = m.get("last_price") or 0
    mid = m.get("midpoint") or last or 0
    vol = m.get("volume") or 0
    spread = m.get("spread")
    
    if isinstance(bid, str): bid = float(bid)
    if isinstance(ask, str): ask = float(ask)
    if isinstance(mid, str): mid = float(mid)
    if isinstance(vol, str): vol = float(vol)
    
    # No prices at all
    if bid == 0 and ask == 0 and last == 0:
        counters["no_prices"] += 1
        continue
    
    # No spread data
    if spread is None:
        counters["no_spread"] += 1
        continue
    
    spread = float(spread)
    spread_cents = int(spread * 100)
    spread_values.append(spread_cents)
    
    # Spread too wide
    if spread_cents > MAX_SPREAD_CENTS:
        counters["spread_too_wide"] += 1
        continue
    
    # No bids/asks
    if bid <= 0 and ask <= 0:
        counters["no_bids_asks"] += 1
        continue
    
    mid_values.append(mid)
    
    # Mid extreme
    if mid < 0.02 or mid > 0.98:
        counters["mid_extreme"] += 1
        continue
    
    volume_values.append(vol)
    
    # Low volume
    if vol < MIN_VOLUME:
        counters["low_volume"] += 1
        continue
    
    # Spread pct too high
    if mid > 0:
        spread_pct = float(spread_cents) / (mid * 100)
        if spread_pct > 0.40:
            counters["spread_pct_too_high"] += 1
            continue
    
    counters["PASSED"] += 1
    print(f"  ✅ {m.get('ticker'):50s} mid={mid:.2f} spread={spread_cents}c vol={vol:.0f} bid={bid:.2f} ask={ask:.2f}")

print()
print("=" * 60)
print("FILTER REJECTION BREAKDOWN (from 200 market sample):")
print("=" * 60)
for k, v in counters.items():
    pct = v / max(counters["total"], 1) * 100
    bar = "█" * int(pct / 2)
    print(f"  {k:25s}: {v:5d} ({pct:5.1f}%) {bar}")

print()
if spread_values:
    spread_values.sort()
    print(f"Spread distribution (cents) of non-junk markets with prices:")
    print(f"  Min: {min(spread_values)}  Median: {spread_values[len(spread_values)//2]}  Max: {max(spread_values)}")
    print(f"  <=5c: {sum(1 for s in spread_values if s <= 5)}")
    print(f"  <=10c: {sum(1 for s in spread_values if s <= 10)}")
    print(f"  <=15c: {sum(1 for s in spread_values if s <= 15)}")
    print(f"  <=20c: {sum(1 for s in spread_values if s <= 20)}")
    print(f"  <=30c: {sum(1 for s in spread_values if s <= 30)}")
    print(f"  >30c: {sum(1 for s in spread_values if s > 30)}")

if volume_values:
    volume_values.sort()
    print(f"\nVolume distribution of markets passing spread+price filters:")
    print(f"  Min: {min(volume_values):.0f}  Median: {volume_values[len(volume_values)//2]:.0f}  Max: {max(volume_values):.0f}")
    print(f"  vol==0: {sum(1 for v in volume_values if v == 0)}")
    print(f"  vol<2: {sum(1 for v in volume_values if v < 2)}")
    print(f"  vol>=2: {sum(1 for v in volume_values if v >= 2)}")
    print(f"  vol>=5: {sum(1 for v in volume_values if v >= 5)}")
    print(f"  vol>=15: {sum(1 for v in volume_values if v >= 15)}")
