#!/usr/bin/env python3
"""Check what production market data looks like and why filter rejects everything."""
import json
import urllib.request

BASE = "https://frankensteintrading.com"

JUNK = (
    "KXMVE", "KXSPOTSTREAMGLOBAL", "KXPARLAY", "KXEPLGOAL", "KXEPLFIRSTGOAL",
    "KXMVECROSSCATEGORY", "KXNCAAMB1HSPREAD", "KXQUICKSETTLE",
    "KXBTC15M", "KXETH15M", "KXSOL15M", "KXDOGE15M", "KXXRP15M",
    "KXADA15M", "KXAVAX15M", "KXLINK15M", "KXDOT15M", "KXMATIC15M",
)


def fetch(path):
    url = f"{BASE}{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "diag/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def main():
    print("=" * 70)
    print("PRODUCTION MARKET DATA ANALYSIS")
    print("=" * 70)

    # Get markets
    data = fetch("/api/markets?limit=500")
    markets = data.get("markets", [])
    print(f"\nTotal markets returned: {len(markets)}")

    # Separate junk vs non-junk
    junk = []
    good = []
    for m in markets:
        t = (m.get("ticker") or "").upper()
        if any(t.startswith(j) for j in JUNK):
            junk.append(m)
        else:
            good.append(m)

    print(f"Junk-prefix markets: {len(junk)}")
    print(f"Non-junk markets: {len(good)}")

    # Analyze price data
    has_bid = sum(1 for m in good if (m.get("yes_bid") or 0) > 0)
    has_ask = sum(1 for m in good if (m.get("yes_ask") or 0) > 0)
    has_last = sum(1 for m in good if (m.get("last_price") or 0) > 0)
    has_any = sum(
        1 for m in good
        if (m.get("yes_bid") or 0) > 0
        or (m.get("yes_ask") or 0) > 0
        or (m.get("last_price") or 0) > 0
    )

    print(f"\nNon-junk price data:")
    print(f"  Has bid > 0: {has_bid}")
    print(f"  Has ask > 0: {has_ask}")
    print(f"  Has last_price > 0: {has_last}")
    print(f"  Has ANY price > 0: {has_any}")

    # Show non-junk with price
    priced = [
        m for m in good
        if (m.get("yes_bid") or 0) > 0
        or (m.get("yes_ask") or 0) > 0
        or (m.get("last_price") or 0) > 0
    ]
    if priced:
        print(f"\n{'─' * 70}")
        print("Non-junk markets with prices:")
        for m in priced[:20]:
            bid = m.get("yes_bid") or 0
            ask = m.get("yes_ask") or 0
            last = m.get("last_price") or 0
            mid_val = m.get("midpoint") or 0
            vol = m.get("volume") or 0
            spr = m.get("spread") or 0
            ticker = m.get("ticker", "?")[:50]
            print(
                f"  {ticker:50s} bid={bid:5.2f} ask={ask:5.2f} last={last:5.3f} "
                f"mid={mid_val:5.2f} spr={spr:4.2f} vol={vol:6.0f}"
            )

    # Simulate maker filter
    print(f"\n{'─' * 70}")
    print("SIMULATING MAKER FILTER on non-junk markets:")
    passed = []
    reject_reasons = {}
    for m in good:
        bid = m.get("yes_bid") or 0
        ask = m.get("yes_ask") or 0
        last = m.get("last_price") or 0

        # Compute mid
        if bid > 0 and ask > 0:
            mid = (bid + ask) / 2.0
        elif last > 0:
            mid = last
        elif bid > 0:
            mid = bid
        elif ask > 0:
            mid = ask
        else:
            reject_reasons["no_price"] = reject_reasons.get("no_price", 0) + 1
            continue

        if mid < 0.02 or mid > 0.98:
            reject_reasons["extreme_mid"] = reject_reasons.get("extreme_mid", 0) + 1
            continue

        if bid > 0 and ask > 0:
            spread_cents = int((ask - bid) * 100)
            if spread_cents > 60:
                reject_reasons["insane_spread"] = reject_reasons.get("insane_spread", 0) + 1
                continue

        passed.append(m)

    print(f"  Passed filter: {len(passed)}")
    print(f"  Rejection reasons: {json.dumps(reject_reasons, indent=4)}")

    if passed:
        print(f"\n  Markets that pass filter:")
        for m in passed[:20]:
            bid = m.get("yes_bid") or 0
            ask = m.get("yes_ask") or 0
            last = m.get("last_price") or 0
            mid_val = m.get("midpoint") or 0
            spr = m.get("spread") or 0
            vol = m.get("volume") or 0
            ticker = m.get("ticker", "?")[:50]
            title = (m.get("title") or "")[:60]
            print(
                f"  {ticker:50s} bid={bid:5.2f} ask={ask:5.2f} last={last:5.3f} "
                f"spr={spr:4.2f} vol={vol:6.0f}  {title}"
            )

    # Check junk-prefix breakdown
    print(f"\n{'─' * 70}")
    print("Junk-prefix breakdown:")
    prefix_counts = {}
    for m in junk:
        t = (m.get("ticker") or "").upper()
        for j in JUNK:
            if t.startswith(j):
                prefix_counts[j] = prefix_counts.get(j, 0) + 1
                break
    for p, c in sorted(prefix_counts.items(), key=lambda x: -x[1]):
        print(f"  {p}: {c}")

    # Also check what % of ALL 10K markets have junk prefixes
    print(f"\n{'─' * 70}")
    print("Checking full cache stats:")
    try:
        status = fetch("/api/frankenstein/status")
        scan_debug = status.get("last_scan_debug", {})
        print(f"  Last scan: {json.dumps(scan_debug)}")
        print(f"  Total scans: {status.get('total_scans')}")
        print(f"  Uptime: {status.get('uptime_human')}")
        print(f"  Signals: {status.get('total_signals')}")
        print(f"  Trades: {status.get('total_trades_executed')}")
    except Exception as e:
        print(f"  Error: {e}")


if __name__ == "__main__":
    main()
