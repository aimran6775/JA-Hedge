#!/usr/bin/env python3
"""Deep analysis of what's in the production market cache."""
import json
import urllib.request
from collections import Counter

BASE = "https://frankensteintrading.com"


def fetch(path):
    url = f"{BASE}{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "diag/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def main():
    # Fetch multiple pages to find non-MVE markets
    all_markets = []
    for offset in range(0, 2000, 500):
        data = fetch(f"/api/markets?limit=500&offset={offset}")
        batch = data.get("markets", [])
        all_markets.extend(batch)
        total = data.get("total", "?")
        if len(batch) < 500:
            break

    print(f"Fetched {len(all_markets)} markets (total in cache: {total})")

    # Prefix analysis
    prefix_counts = Counter()
    non_mve = []
    for m in all_markets:
        t = m.get("ticker", "")
        # Extract prefix (everything before first '-')
        prefix = t.split("-")[0] if "-" in t else t
        prefix_counts[prefix] += 1
        if not t.upper().startswith("KXMVE"):
            non_mve.append(m)

    print(f"\nTop 20 ticker prefixes:")
    for prefix, count in prefix_counts.most_common(20):
        print(f"  {prefix}: {count}")

    print(f"\nNon-MVE markets: {non_mve}")

    # Try fetching events to find individual markets
    print("\n" + "=" * 60)
    print("CHECKING EVENTS:")
    try:
        # Use the Kalshi API directly via our backend
        events_data = fetch("/api/sports/markets")
        print(f"Sports markets response: {json.dumps(events_data, indent=2)[:500]}")
    except Exception as e:
        print(f"Sports markets error: {e}")

    # Check what ticker prefixes exist in the full cache
    print("\n" + "=" * 60)
    print("SEARCHING FOR SPECIFIC MARKET TYPES:")
    searches = ["weather", "crypto", "MLB", "NFL", "election", "temperature", "rain"]
    for s in searches:
        try:
            data = fetch(f"/api/markets?limit=5&search={s}")
            markets = data.get("markets", [])
            non_mve_results = [m for m in markets if not m.get("ticker", "").upper().startswith("KXMVE")]
            print(f"  '{s}': {len(markets)} total, {len(non_mve_results)} non-MVE")
            for m in non_mve_results[:2]:
                print(f"    {m['ticker'][:50]}  last={m.get('last_price', 0)}")
        except Exception as e:
            print(f"  '{s}': error - {e}")


if __name__ == "__main__":
    main()
