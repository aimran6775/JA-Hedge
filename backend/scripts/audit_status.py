#!/usr/bin/env python3
"""Quick audit script — pull Frankenstein status and summarize."""
import json, sys, urllib.request

def fetch(path):
    try:
        r = urllib.request.urlopen(f"http://localhost:8000{path}", timeout=5)
        return json.loads(r.read())
    except Exception as e:
        return {"_error": str(e)}

status = fetch("/api/frankenstein/status")
mem = status.get("memory", {})
outcomes = mem.get("outcomes", {})
cat_analytics = mem.get("category_analytics", {})

print("=== MEMORY OUTCOMES ===")
for k, v in outcomes.items():
    print(f"  {k}: {v}")
print(f"  Win rate: {mem.get('win_rate')}")
print(f"  Total PnL: {mem.get('total_pnl')}")
print(f"  Avg PnL: {mem.get('avg_pnl_per_trade')}")

print("\n=== CATEGORY ANALYTICS ===")
for cat, stats in cat_analytics.items():
    wr = stats["win_rate"]
    pnl = stats["total_pnl"]
    streak = stats["current_loss_streak"]
    print(f"  {cat:15s}: trades={stats['trades']:3d} wins={stats['wins']:3d} losses={stats['losses']:3d} WR={wr:.1%} pnl=${pnl:.2f} streak={streak}")

print("\n=== ORDER MANAGER ===")
om = status.get("order_manager", {})
frs = om.get("fill_rate_stats", {})
print(f"  Pending: {om.get('pending_orders')}")
for k, v in frs.items():
    print(f"  {k}: {v}")
print(f"  Fill rate: {om.get('fill_rate')}")

print("\n=== CAPITAL ===")
cap = status.get("capital", {})
print(f"  Balance: {cap.get('balance_cents')} cents")
print(f"  Reserved: {cap.get('reserved_cents')} ({cap.get('reserved_pct')})")
print(f"  Available: {cap.get('available_cents')} cents")
print(f"  Orders gated: {cap.get('orders_gated')}")
print(f"  Approved: {cap.get('orders_approved')}")
print(f"  Category deployed: {cap.get('category_deployed')}")

print("\n=== SCAN DEBUG ===")
sd = status.get("last_scan_debug", {})
for k, v in sd.items():
    print(f"  {k}: {v}")

print("\n=== INTELLIGENCE ===")
intel = fetch("/api/intelligence/status")
if "_error" not in intel:
    for s in intel.get("sources", []):
        st = "OK" if s["signal_count"] > 0 else ("ERR" if s["error_count"] > 0 else "EMPTY")
        print(f"  {s['name']:30s} signals={s['signal_count']:5d} errs={s['error_count']} [{st}]")
    print(f"  Total signals: {intel.get('total_signals_lifetime')}")
else:
    print(f"  Error: {intel['_error']}")

print("\n=== REJECTIONS ENDPOINT ===")
rej = fetch("/api/frankenstein/debug/rejections")
if "_error" in rej or "error" in rej:
    print(f"  BROKEN: {rej}")
else:
    print(f"  OK: {len(rej.get('candidates', []))} candidates analyzed")
