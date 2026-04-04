#!/usr/bin/env python3
"""Analyze the local frankenstein_memory.json."""
import json
from collections import Counter

with open("data/frankenstein_memory.json") as f:
    mem = json.load(f)

trades = mem.get("trades", [])
print(f"Total trades in file: {len(trades)}")

outcomes = Counter(t.get("outcome") for t in trades)
print(f"Outcomes: {dict(outcomes)}")

pending = [t for t in trades if t.get("outcome") == "pending"]
breakeven = [t for t in trades if t.get("outcome") == "breakeven"]

print(f"\nPending: {len(pending)}")
print(f"Breakeven: {len(breakeven)}")

# Check if breakeven trades have market_result
be_with_result = [t for t in breakeven if t.get("market_result") in ("yes", "no")]
be_no_result = [t for t in breakeven if t.get("market_result") not in ("yes", "no")]
print(f"Breakeven WITH market_result: {len(be_with_result)}")
print(f"Breakeven WITHOUT market_result: {len(be_no_result)}")

results = Counter(t.get("market_result") for t in breakeven)
print(f"market_result values in breakeven: {dict(results)}")

pnls = [t.get("pnl_cents", 0) for t in breakeven]
print(f"Breakeven PnL range: {min(pnls)} to {max(pnls)}, sum={sum(pnls)}")

methods = Counter(t.get("resolution_method") for t in breakeven)
print(f"Resolution methods: {dict(methods)}")

# Look at a few breakeven trades
print("\n--- Sample breakeven trades ---")
for t in breakeven[:3]:
    keys = ["ticker","side","action","entry_price","exit_price","pnl_cents","outcome","market_result","resolution_method","resolve_price","hold_time_seconds"]
    print(json.dumps({k: t.get(k) for k in keys}, indent=2))

# Look at pending trades - recent
print(f"\n--- Sample pending trades (last 5) ---")
for t in pending[-5:]:
    keys = ["ticker","side","action","entry_price","confidence","edge","timestamp","outcome","hold_time_seconds"]
    print(json.dumps({k: t.get(k) for k in keys}, indent=2))

# Check actions distribution
actions = Counter(t.get("action") for t in trades)
print(f"\nActions: {dict(actions)}")

# Check sell trades
sells = [t for t in trades if t.get("action") == "sell"]
print(f"\nSell trades: {len(sells)}")
if sells:
    sell_outcomes = Counter(s.get("outcome") for s in sells)
    print(f"Sell outcomes: {dict(sell_outcomes)}")
    for s in sells[:3]:
        keys = ["ticker","side","action","entry_price","exit_price","pnl_cents","outcome","hold_time_seconds"]
        print(json.dumps({k: s.get(k) for k in keys}, indent=2))

# Check if pending trades have timestamps (to see how old they are)
import time
now = time.time()
if pending:
    ages = [(now - t.get("timestamp", now)) / 3600 for t in pending]
    print(f"\nPending trade ages: min={min(ages):.1f}h, max={max(ages):.1f}h, avg={sum(ages)/len(ages):.1f}h")

# Unique tickers in pending
pending_tickers = Counter(t.get("ticker") for t in pending)
print(f"\nPending tickers ({len(pending_tickers)} unique):")
for ticker, count in pending_tickers.most_common(15):
    print(f"  {ticker}: {count} trades")
