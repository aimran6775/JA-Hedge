#!/usr/bin/env python3
"""Inspect recent trade details from production."""
import json
import urllib.request

BASE = "https://frankensteintrading.com"

def fetch(path):
    req = urllib.request.Request(f"{BASE}{path}", headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

# Get 3 most recent trades with ALL fields
trades = fetch("/api/frankenstein/memory/recent?limit=3")
print("=== RAW RECENT TRADES (full fields) ===")
for t in trades:
    print(json.dumps(t, indent=2, default=str)[:1200])
    print("---")

# Check model state
status = fetch("/api/frankenstein/status")
print()
print("=== MODEL INFO ===")
lm = status.get("learning_mode")
lp = status.get("learning_progress")
gen = status.get("generation")
print(f"  Learning mode: {lm}")
print(f"  Learning progress: {lp}")
print(f"  Generation: {gen}")
print(f"  Retired categories: {status.get('retired_categories')}")

# Check scan debug
sd = status.get("last_scan_debug", {})
print()
print("=== LAST SCAN ===")
print(f"  exit: {sd.get('exit', '?')}")
print(f"  candidates: {sd.get('candidates', '?')}")
print(f"  signals: {sd.get('signals', '?')}")
print(f"  trade_candidates: {sd.get('trade_candidates', '?')}")
print(f"  exec_successes: {sd.get('exec_successes', '?')}")

# Check strategy params
strat = status.get("strategy", {})
print()
print("=== STRATEGY PARAMS ===")
for k, v in strat.items():
    print(f"  {k}: {v}")

# Also check if there are any trades with NON-zero confidence
print()
print("=== CHECKING FOR NON-ZERO CONFIDENCE ===")
all_recent = fetch("/api/frankenstein/memory/recent?limit=100")
has_conf = [t for t in all_recent if t.get("confidence", 0) > 0.001]
zero_conf = [t for t in all_recent if t.get("confidence", 0) <= 0.001]
print(f"  Trades with conf > 0: {len(has_conf)}")
print(f"  Trades with conf = 0: {len(zero_conf)}")
if has_conf:
    t = has_conf[0]
    print(f"  Example with conf > 0: ticker={t['ticker']}, conf={t['confidence']:.4f}, edge={t['edge']:.4f}, source={t.get('source','?')}")
if zero_conf:
    t = zero_conf[0]
    print(f"  Example with conf = 0: ticker={t['ticker']}, conf={t['confidence']:.4f}, edge={t['edge']:.4f}, source={t.get('source','?')}")
    print(f"    model_version={t.get('model_version','?')}")
    print(f"    features (first 10): {t.get('features', [])[:10]}")
    print(f"    predicted_prob={t.get('predicted_prob', '?')}")
    print(f"    raw_predicted_prob={t.get('raw_predicted_prob', '?')}")
    print(f"    side={t.get('predicted_side', '?')}")
    print(f"    price_cents={t.get('price_cents', '?')}")
    print(f"    count={t.get('count', '?')}")
    print(f"    total_cost_cents={t.get('total_cost_cents', '?')}")
    print(f"    market_bid_cents={t.get('market_bid_cents', '?')}")
    print(f"    market_ask_cents={t.get('market_ask_cents', '?')}")
    print(f"    confidence_breakdown={t.get('confidence_breakdown', {})}")
    print(f"    outcome={t.get('outcome', '?')}")
    print(f"    timestamp={t.get('timestamp', '?')}")
