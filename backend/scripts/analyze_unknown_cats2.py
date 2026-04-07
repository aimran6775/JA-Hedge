"""Deeper analysis of the empty-category trades."""
import json
from pathlib import Path
from collections import Counter

fp = Path("data/frankenstein_memory.json")
data = json.load(open(fp))
trades = data.get("trades", [])

# Focus on empty-category trades
empty_cats = [t for t in trades if not t.get("category")]

print(f"Total trades: {len(trades)}")
print(f"Empty category trades: {len(empty_cats)}")
print()

# What ticker prefixes are in empty-category trades?
prefix_counter = Counter()
ticker_counter = Counter()
for t in empty_cats:
    ticker = t.get("ticker", "")
    # Extract prefix (everything before first digit after KX)
    import re
    m = re.match(r"(KX[A-Z]+)", ticker.upper())
    if m:
        prefix_counter[m.group(1)] += 1
    ticker_counter[ticker[:30]] += 1

print("=== Top Ticker Prefixes (empty-category trades) ===")
for prefix, count in prefix_counter.most_common(20):
    print(f"  {prefix:30s}: {count}")

print()
print("=== Outcome breakdown (empty-category) ===")
outcome_counter = Counter(t.get("outcome", "") for t in empty_cats)
for outcome, count in outcome_counter.most_common():
    pnl = sum(t.get("pnl_cents", 0) for t in empty_cats if t.get("outcome") == outcome)
    print(f"  {outcome:15s}: {count:5d} trades, PnL: ${pnl/100:.2f}")

print()
print("=== market_title field (empty-category) ===")
has_title = sum(1 for t in empty_cats if t.get("market_title"))
no_title = sum(1 for t in empty_cats if not t.get("market_title"))
print(f"  Has title: {has_title}")
print(f"  No title:  {no_title}")

print()
print("=== category_analytics() simulation ===")
# Simulate what category_analytics does
from enum import Enum
cats: dict = {}
for t in trades:
    outcome = t.get("outcome", "")
    if outcome in ("pending", "cancelled", "expired"):
        continue
    cat = t.get("category") or "unknown"  # THIS IS THE KEY LINE
    cats.setdefault(cat, []).append(t)

for cat, cat_trades in sorted(cats.items(), key=lambda x: -len(x[1])):
    wins = sum(1 for t in cat_trades if t.get("outcome") == "win")
    losses = sum(1 for t in cat_trades if t.get("outcome") == "loss")
    pnl = sum(t.get("pnl_cents", 0) for t in cat_trades)
    total = len(cat_trades)
    wr = wins / total if total else 0
    print(f"  {cat:20s}: {total:5d} trades | W:{wins} L:{losses} WR:{wr:.1%} PnL:${pnl/100:.2f}")
