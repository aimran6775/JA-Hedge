#!/usr/bin/env python3
"""Phase 28c status check."""
import json, urllib.request

def fetch(path):
    url = f"https://frankensteintrading.com{path}"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}

# Health
h = fetch("/health")
pt = h.get("paper_trading", {})
print("=== HEALTH ===")
print(f"Balance: ${pt.get('balance', '?')}")
print(f"PnL: ${pt.get('pnl', '?')}")
print(f"Trades: {pt.get('total_trades', '?')}")
print(f"Frankenstein: {h.get('components', {}).get('frankenstein', '?')}")

# Status
d = fetch("/api/frankenstein/status")
print(f"\n=== FRANKENSTEIN STATUS ===")
print(f"Version: {d.get('version')}")
print(f"Uptime: {d.get('uptime_human')}")
print(f"Scans: {d.get('total_scans')}")
print(f"Signals: {d.get('total_signals')}")
print(f"Trades executed: {d.get('total_trades_executed')}")
print(f"Trades rejected: {d.get('total_trades_rejected')}")
print(f"Daily: {d.get('daily_trades')} / {d.get('daily_trade_cap')}")
print(f"Learning: {d.get('learning_mode')}")

sd = d.get("last_scan_debug", {})
print(f"\n=== LAST SCAN ===")
print(f"Candidates: {sd.get('candidates')}")
print(f"Signals: {sd.get('signals')}")
print(f"Trade candidates: {sd.get('trade_candidates')}")
print(f"Open positions: {sd.get('open_positions')}")
print(f"Exec successes: {sd.get('exec_successes')}")
print(f"Exec rejections: {sd.get('exec_rejections')}")
print(f"Portfolio rejections: {sd.get('portfolio_rejections')}")

print(f"\n=== TOP CANDIDATES ===")
for c in sd.get("top_candidates", [])[:10]:
    tk = c.get("ticker", "?")[:50]
    stage = c.get("stage", "?")
    err = c.get("error", "")[:60]
    oid = c.get("order_id", "")[:20]
    print(f"  {tk}: {stage} {err}{oid}")

mem = d.get("memory", {})
print(f"\n=== MEMORY ===")
print(f"Recorded: {mem.get('total_recorded')}")
print(f"Pending: {mem.get('pending')}")
print(f"Win rate: {mem.get('win_rate')}")
print(f"PnL: {mem.get('total_pnl')}")

ca = mem.get("category_analytics", {})
print(f"\n=== CATEGORIES ===")
for cat, v in sorted(ca.items()):
    t = v.get("trades", 0)
    w = v.get("wins", 0)
    l = v.get("losses", 0)
    wr = v.get("win_rate", 0)
    pnl = v.get("total_pnl", 0)
    print(f"  {cat}: trades={t} W={w} L={l} WR={wr:.0%} PnL=${pnl:.2f}")

# Risk limits
r = fetch("/api/risk/limits")
print(f"\n=== RISK LIMITS ===")
for k, v in r.items():
    if k != "error":
        print(f"  {k}: {v}")

# Positions
pos = fetch("/api/portfolio/positions")
if isinstance(pos, list):
    print(f"\n=== POSITIONS ({len(pos)}) ===")
    total_exposure = 0
    for p in pos[:20]:
        tk = p.get("ticker", "?")[:50]
        qty = p.get("position", "?")
        exp = float(p.get("market_exposure_dollars", 0))
        total_exposure += exp
        print(f"  {tk}: qty={qty} exposure=${exp:.2f}")
    print(f"  TOTAL EXPOSURE: ${total_exposure:.2f}")
