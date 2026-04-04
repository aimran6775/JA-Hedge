#!/usr/bin/env python3
"""Check for individual (non-MVE) markets deeper in the cache."""
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
    # Fetch markets at higher offsets to skip MVE parlays
    non_mve = []
    prefixes = Counter()

    for offset in [5000, 8000, 10000, 12000, 13000]:
        try:
            data = fetch(f"/api/markets?limit=100&offset={offset}")
            batch = data.get("markets", [])
            for m in batch:
                t = m.get("ticker", "").upper()
                prefix = t.split("-")[0]
                prefixes[prefix] += 1
                if not t.startswith("KXMVE"):
                    non_mve.append(m)
            print(f"Offset {offset}: {len(batch)} markets, {len([m for m in batch if not m.get('ticker','').upper().startswith('KXMVE')])} non-MVE")
        except Exception as e:
            print(f"Offset {offset}: error - {e}")

    print(f"\nTotal non-MVE found: {len(non_mve)}")
    print(f"\nAll prefixes seen:")
    for p, c in prefixes.most_common(30):
        print(f"  {p}: {c}")

    if non_mve:
        print(f"\nNon-MVE markets:")
        for m in non_mve[:30]:
            bid = m.get("yes_bid") or 0
            ask = m.get("yes_ask") or 0
            last = m.get("last_price") or 0
            vol = m.get("volume") or 0
            t = m.get("ticker", "")[:55]
            title = (m.get("title") or "")[:50]
            cat = m.get("category") or "?"
            print(f"  {t:55s} bid={bid:.2f} ask={ask:.2f} last={last:.3f} vol={vol:6.0f} cat={cat:12s} {title}")

    # Also try: hit Kalshi API directly to get a single known market type
    print("\n" + "=" * 60)
    print("Trying specific event/market lookups:")
    for search in ["KXNBA", "KXMLB", "KXBTC", "KXWEATHER", "KXINX", "KXFED"]:
        data = fetch(f"/api/markets?limit=5&search={search}")
        results = data.get("markets", [])
        non = [m for m in results if not m.get("ticker","").upper().startswith("KXMVE")]
        print(f"  '{search}': {len(results)} total, {len(non)} non-MVE")
        for m in non[:2]:
            print(f"    {m['ticker'][:50]}  last={m.get('last_price',0)}")


if __name__ == "__main__":
    main()
