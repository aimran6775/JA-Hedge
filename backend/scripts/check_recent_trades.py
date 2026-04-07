#!/usr/bin/env python3
"""Check recent trades from production."""
import json, urllib.request, sys

url = "https://frankensteintrading.com/api/frankenstein/trades?limit=20"
req = urllib.request.Request(url)
with urllib.request.urlopen(req, timeout=10) as resp:
    data = json.loads(resp.read())

trades = data.get("trades", data) if isinstance(data, dict) else data
if not trades:
    print("No trades returned")
    sys.exit(0)

print(f"{'Time':>8s} | {'Category':12s} | Side | {'Outcome':10s} | {'PnL':>7s} | Ticker")
print("-" * 95)
for t in (trades[:20] if isinstance(trades, list) else []):
    cat = t.get("category", "?")
    ticker = t.get("ticker", "?")[:40]
    side = t.get("side", "?")
    outcome = t.get("outcome", "pending")
    pnl = t.get("pnl_cents", 0)
    ts = t.get("timestamp", "?")[-8:]
    print(f"{ts:>8s} | {cat:12s} | {side:>3s}  | {outcome:10s} | ${pnl/100:+6.2f} | {ticker}")
