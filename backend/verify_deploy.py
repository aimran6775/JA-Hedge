"""Verify that the fee-aware overhaul deployed correctly."""
import json
import urllib.request

BASE = "https://api.frankensteintrading.com"

def fetch(path):
    req = urllib.request.Request(f"{BASE}{path}")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())

# 1. Status
d = fetch("/api/frankenstein/status")
print("=== FRANKENSTEIN STATUS ===")
print(f"Alive: {d['is_alive']}, Trading: {d['is_trading']}")
print(f"Scans: {d['total_scans']}, Trades: {d['total_trades_executed']}")
print(f"Rejected: {d['total_trades_rejected']}")
print(f"Model: {d.get('model_version', d.get('model', {}).get('version', '?'))}")
print()

# 2. Strategy params
p = d.get('strategy_params', {})
print("=== STRATEGY PARAMS ===")
checks = [
    ("min_edge", p.get("min_edge"), 0.10),
    ("min_confidence", p.get("min_confidence"), 0.50),
    ("scan_interval", p.get("scan_interval"), 45.0),
    ("max_position_size", p.get("max_position_size"), 4),
    ("max_simultaneous", p.get("max_simultaneous_positions"), 20),
    ("max_spread_cents", p.get("max_spread_cents"), 15),
    ("min_volume", p.get("min_volume"), 20.0),
    ("min_hours_to_expiry", p.get("min_hours_to_expiry"), 2.0),
    ("take_profit_pct", p.get("take_profit_pct"), 0.20),
]
all_ok = True
for name, actual, expected in checks:
    ok = actual == expected
    status = "✅" if ok else "❌"
    if not ok:
        all_ok = False
    print(f"  {status} {name}: {actual} (expected {expected})")

print()
print("✅ ALL PARAMS CORRECT" if all_ok else "❌ SOME PARAMS WRONG — adaptive strategy may have shifted values")

# 3. Check recent debug for fee filtering
debug = d.get("last_scan_debug", {})
print(f"\n=== LAST SCAN DEBUG ===")
print(f"Candidates: {debug.get('candidates', '?')}")
print(f"Trade candidates: {debug.get('trade_candidates', '?')}")
print(f"Signals: {debug.get('signals', '?')}")
print(f"Executed: {debug.get('exec_successes', '?')}")
print(f"Rejected: {debug.get('exec_rejections', '?')}")
