#!/usr/bin/env python3
"""Live production audit — full deep-dive."""
import json
import urllib.request

BASE = "https://frankensteintrading.com"

def fetch(path):
    try:
        req = urllib.request.Request(f"{BASE}{path}", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"_error": str(e)}

# 1. Health
h = fetch("/health")
pt = h.get("paper_trading", {})
print("=== HEALTH ===")
print(f"  Status: {h.get('status')}")
print(f"  Balance: ${pt.get('balance', '?')}  PnL: ${pt.get('pnl', '?')}  Trades: {pt.get('total_trades', '?')}")
print()

# 2. Full status
d = fetch("/api/frankenstein/status")
print("=== FRANKENSTEIN ===")
print(f"  Alive={d.get('is_alive')}  Trading={d.get('is_trading')}  Paused={d.get('is_paused')}")
print(f"  Pause reason: {d.get('pause_reason')}")
print(f"  Gen: {d.get('generation')}  Uptime: {d.get('uptime_human')}")
print(f"  Learning: {d.get('learning_mode')} ({d.get('learning_progress')})")
print(f"  Daily trades: {d.get('daily_trades')} / {d.get('daily_trade_cap')}")
print(f"  Circuit breaker: {d.get('circuit_breaker_active')}")
print(f"  sports_only: {d.get('sports_only_mode')}")
print()

# Performance
perf = d.get("performance", {})
print("=== PERFORMANCE ===")
for k, v in perf.items():
    print(f"  {k}: {v}")
print()

# Memory
mem = d.get("memory", {})
print("=== MEMORY ===")
for k, v in mem.items():
    if k != "category_analytics":
        print(f"  {k}: {v}")
print()

# Categories
ca = mem.get("category_analytics", {})
print("=== CATEGORIES (all time) ===")
for cat, s in sorted(ca.items(), key=lambda x: x[1].get("trades", 0), reverse=True):
    t = s.get("trades", 0)
    wr = s.get("win_rate", 0)
    pnl = s.get("total_pnl", 0)
    res = s.get("resolved", 0)
    unres = t - res
    print(f"  {cat:20s}  trades={t:5d}  resolved={res:5d}  WR={wr:.1%}  PnL=${pnl:+.2f}")
print()

# Last scan
sd = d.get("last_scan_debug", {})
print("=== LAST SCAN ===")
for k, v in sd.items():
    if k != "top_candidates":
        print(f"  {k}: {v}")
print("  Top candidates:")
for c in sd.get("top_candidates", [])[:10]:
    print(f"    {c.get('stage','?'):15s}  {c.get('ticker','')}")
print()

# Orders
om = d.get("order_manager", {})
print("=== ORDERS ===")
for k, v in om.items():
    print(f"  {k}: {v}")
print()

# Capital
cap = d.get("capital", {})
print("=== CAPITAL ===")
for k, v in cap.items():
    print(f"  {k}: {v}")
print()

# Live engine
le = d.get("live_engine")
print(f"Live engine: {le}")

# WS
ws = d.get("ws_bridge", {})
print(f"WS bridge: {ws}")
print(f"Reactive trades: {d.get('reactive_trades')}")
print()

# Strategy
strat = d.get("strategy", {})
print("=== STRATEGY ===")
for k, v in strat.items():
    print(f"  {k}: {v}")
print()

# Risk
risk = d.get("portfolio_risk", {})
print("=== PORTFOLIO RISK ===")
for k, v in risk.items():
    print(f"  {k}: {v}")
print()

# 3. Recent trades
print("=== RECENT 30 TRADES ===")
recent = fetch("/api/frankenstein/memory/recent?limit=30")
if isinstance(recent, list):
    cats = {}
    for t in recent:
        c = t.get("category", "?")
        cats[c] = cats.get(c, 0) + 1
    print(f"  By category: {dict(sorted(cats.items(), key=lambda x: -x[1]))}")
    print()
    for t in recent:
        ticker = t.get("ticker", "?")
        cat = t.get("category", "?")
        side = t.get("predicted_side", "?")
        conf = t.get("confidence", 0)
        edge = t.get("edge", 0)
        result = t.get("market_result", "pending")
        pnl = t.get("pnl_cents", 0)
        print(f"  {result:8s}  {cat:15s}  {side:3s}  conf={conf:.2f}  edge={edge:+.3f}  pnl={pnl:+.0f}c  {ticker}")
print()

# 4. Rejections
print("=== REJECTIONS ===")
rej = fetch("/api/frankenstein/debug/rejections")
if "_error" not in rej:
    print(f"  Total active markets: {rej.get('total_active', '?')}")
    print(f"  Pre-filtered: {rej.get('total_pre_filtered', '?')}")
    print(f"  Model trained: {rej.get('model_trained', '?')}")
    print(f"  Learning mode: {rej.get('is_learning_mode', '?')}")
    # Show a few candidates with blocking gates
    cands = rej.get("candidates", [])
    blocked = [c for c in cands if c.get("gates_blocking")]
    print(f"  Candidates shown: {len(cands)}, blocked: {len(blocked)}")
    for c in blocked[:5]:
        print(f"    {c.get('ticker','?')}: {c.get('gates_blocking')}")
print()

# 5. Market cache
print("=== MARKET CACHE ===")
mkt = fetch("/api/markets?limit=1")
print(f"  Total cached: {mkt.get('total', '?')}")

# 6. Portfolio
print()
print("=== PORTFOLIO ===")
port = fetch("/api/portfolio/balance")
print(f"  Balance: {port}")
pos = fetch("/api/portfolio/positions")
if isinstance(pos, dict):
    positions = pos.get("positions", pos.get("event_positions", []))
    print(f"  Open positions: {len(positions) if isinstance(positions, list) else '?'}")
elif isinstance(pos, list):
    print(f"  Open positions: {len(pos)}")
