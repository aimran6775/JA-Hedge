#!/usr/bin/env python3
"""Diagnose: WHY 0% win rate? Look at every settled trade outcome distribution."""
import json
import urllib.request
from collections import Counter

BASE = "https://frankensteintrading.com"


def fetch(path):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=20) as r:
        return json.loads(r.read())


# Get ALL trades from memory (we have ~1035 resolved)
data = fetch("/api/frankenstein/memory/recent?n=10000")
print(f"Total trades fetched: {len(data)}")

# Outcome distribution
outcomes = Counter(t.get("outcome") for t in data)
print(f"\nOutcome distribution: {dict(outcomes)}")

# Action distribution
actions = Counter(t.get("action") for t in data)
print(f"Action distribution: {dict(actions)}")

# Source distribution (bootstrap vs live)
sources = Counter(t.get("source") for t in data)
print(f"Source distribution: {dict(sources)}")

# Model versions
mv = Counter(t.get("model_version") for t in data)
print(f"Model versions: {dict(mv)}")

# For LIVE buy trades only
live_buys = [t for t in data if t.get("source") == "live" and t.get("action") == "buy"]
print(f"\n=== LIVE BUY trades only: {len(live_buys)} ===")
live_outcomes = Counter(t.get("outcome") for t in live_buys)
print(f"Live buy outcomes: {dict(live_outcomes)}")

# Predicted side vs market result for resolved live buys
resolved_live = [t for t in live_buys if t.get("outcome") not in ("pending", None)]
print(f"\n=== RESOLVED live buys: {len(resolved_live)} ===")

predicted = Counter(t.get("predicted_side") for t in resolved_live)
results = Counter(t.get("market_result") for t in resolved_live)
print(f"Predicted side: {dict(predicted)}")
print(f"Market result: {dict(results)}")

# Sample some win/loss/expired trades to see what's going on
print("\n=== Sample WIN trades ===")
wins = [t for t in resolved_live if t.get("outcome") == "win"][:5]
for t in wins:
    print(f"  {t.get('ticker')[:30]:30} pred={t.get('predicted_side')} result={t.get('market_result')} pnl={t.get('pnl_cents')} count={t.get('count')} cost={t.get('total_cost_cents')}")

print("\n=== Sample LOSS trades ===")
losses = [t for t in resolved_live if t.get("outcome") == "loss"][:5]
for t in losses:
    print(f"  {t.get('ticker')[:30]:30} pred={t.get('predicted_side')} result={t.get('market_result')} pnl={t.get('pnl_cents')} count={t.get('count')} cost={t.get('total_cost_cents')} price={t.get('price_cents')}")

print("\n=== Sample EXPIRED ===")
exp = [t for t in resolved_live if t.get("outcome") == "expired"][:5]
for t in exp:
    print(f"  {t.get('ticker')[:30]:30} pred={t.get('predicted_side')} result={t.get('market_result')} pnl={t.get('pnl_cents')} count={t.get('count')}")

print("\n=== Sample BREAKEVEN ===")
be = [t for t in resolved_live if t.get("outcome") == "breakeven"][:5]
for t in be:
    print(f"  {t.get('ticker')[:30]:30} pred={t.get('predicted_side')} result={t.get('market_result')} pnl={t.get('pnl_cents')} count={t.get('count')}")

print("\n=== Sample CANCELLED ===")
cn = [t for t in resolved_live if t.get("outcome") == "cancelled"][:5]
for t in cn:
    print(f"  {t.get('ticker')[:30]:30} pred={t.get('predicted_side')} result={t.get('market_result')} pnl={t.get('pnl_cents')} count={t.get('count')}")

# Check pnl_cents distribution
pnl_values = [t.get("pnl_cents", 0) for t in resolved_live]
print(f"\n=== PnL stats over {len(pnl_values)} resolved live buys ===")
print(f"  positive: {sum(1 for p in pnl_values if p > 0)}")
print(f"  zero:     {sum(1 for p in pnl_values if p == 0)}")
print(f"  negative: {sum(1 for p in pnl_values if p < 0)}")
print(f"  sum:      {sum(pnl_values)} cents = ${sum(pnl_values)/100:.2f}")

# Model version on resolved trades
mv_resolved = Counter(t.get("model_version") for t in resolved_live)
print(f"\nModel versions of resolved live buys: {dict(mv_resolved)}")
