#!/usr/bin/env python3
"""Phase 27 pre-analysis: full status dump."""
import json
import urllib.request

BASE = "https://frankensteintrading.com"

def fetch(path):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=15) as r:
        return json.loads(r.read())

st = fetch("/api/frankenstein/status")

print("=== OVERVIEW ===")
for k in ["uptime_human","daily_trades","daily_trade_cap","learning_mode","learning_progress","real_trades","total_scans"]:
    print(f"  {k}: {st.get(k)}")

mem = st.get("memory", {})
print("\n=== MEMORY ===")
for k,v in mem.items():
    if k != "category_analytics":
        print(f"  {k}: {v}")

print("\n=== LEARNER ===")
lr = st.get("learner", {})
for k,v in lr.items():
    print(f"  {k}: {v}")

print("\n=== STRATEGY ===")
strat = st.get("strategy", {})
sp = strat.get("current_params", {})
for k,v in sp.items():
    print(f"  {k}: {v}")
print(f"  aggression: {strat.get('aggression')}")
print(f"  adaptations: {strat.get('total_adaptations')}")

print("\n=== CAPITAL ===")
cap = st.get("capital", {})
for k,v in cap.items():
    print(f"  {k}: {v}")

print("\n=== ORDER MANAGER ===")
om = st.get("order_manager", {})
for k,v in om.items():
    print(f"  {k}: {v}")

print("\n=== ACTIVE POSITIONS ===")
ap = st.get("active_positions", {})
print(f"  count: {ap.get('count')}")
for p in ap.get("positions", [])[:15]:
    print(f"  {p.get('ticker')}: side={p.get('side')} qty={p.get('quantity')} entry={p.get('entry_price')} held={p.get('held_time')}")

print("\n=== PERFORMANCE ===")
perf = st.get("performance", {})
snap = perf.get("snapshot", {})
for k,v in snap.items():
    print(f"  {k}: {v}")
print(f"  should_pause: {perf.get('should_pause')}")
print(f"  pause_reason: {perf.get('pause_reason')}")

print("\n=== SCANNER ===")
sc = st.get("scanner", {})
for k,v in sc.items():
    print(f"  {k}: {v}")

print("\n=== PORTFOLIO RISK ===")
risk = st.get("portfolio_risk", {})
for k,v in risk.items():
    print(f"  {k}: {v}")

print("\n=== WS BRIDGE ===")
ws = st.get("ws_bridge", {})
for k,v in ws.items():
    print(f"  {k}: {v}")

print("\n=== EXCHANGE ===")
ex = st.get("exchange_session", {})
print(f"  {ex}")

# Rejections
print("\n=== REJECTIONS ===")
try:
    rej = fetch("/api/frankenstein/debug/rejections")
    reasons = {}
    for r in rej.get("rejections", []):
        reason = r.get("last_rejection_reason", "unknown")
        reasons[reason] = reasons.get(reason, 0) + 1
    for reason, count in sorted(reasons.items(), key=lambda x: -x[1])[:15]:
        print(f"  {count:3d}x  {reason}")
    print(f"  total rejected tickers: {len(rej.get('rejections', []))}")
except Exception as e:
    print(f"  Error: {e}")

# Balance
print("\n=== PORTFOLIO ===")
try:
    bal = fetch("/api/portfolio/balance")
    print(f"  balance: ${bal.get('balance_dollars')}")
    print(f"  positions: {bal.get('position_count')}")
    print(f"  open_orders: {bal.get('open_orders')}")
except Exception as e:
    print(f"  Error: {e}")

# Recent trades
print("\n=== RECENT TRADES (last 20) ===")
try:
    trades = fetch("/api/frankenstein/trades?limit=20")
    tl = trades if isinstance(trades, list) else trades.get("trades", trades.get("recent", []))
    for t in tl[:20]:
        ticker = t.get("ticker", "?")[:45]
        side = t.get("side", "?")
        outcome = t.get("outcome", "?")
        pnl = t.get("pnl_cents", 0)
        conf = t.get("confidence", 0)
        edge = t.get("edge", 0)
        source = t.get("source", "live")
        action = t.get("action", "?")
        if source != "bootstrap":
            print(f"  {ticker:45s} {side:3s} {action:4s} out={outcome:10s} pnl={pnl:+5d}c conf={conf:.2f} edge={edge:+.4f}")
except Exception as e:
    print(f"  Error: {e}")
