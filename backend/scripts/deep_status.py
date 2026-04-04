#!/usr/bin/env python3
"""Deep analysis of current system performance for improvement identification."""
import json
import urllib.request

def fetch(path):
    url = f"https://frankensteintrading.com{path}"
    with urllib.request.urlopen(url, timeout=15) as r:
        return json.loads(r.read())

d = fetch("/api/frankenstein/status")

# Memory
mem = d.get("memory", {})
print("=== MEMORY & PNL ===")
print(f"Total recorded: {mem.get('total_recorded')}")
print(f"Resolved: {mem.get('total_resolved')}")
print(f"Pending: {mem.get('pending')}")
print(f"Win rate: {mem.get('win_rate')}")
print(f"Total PnL: {mem.get('total_pnl')}")
print(f"Avg PnL/trade: {mem.get('avg_pnl_per_trade')}")
print(f"Outcomes: {mem.get('outcomes')}")
ca = mem.get("category_analytics", {})
for cat, stats in ca.items():
    wr = stats.get("win_rate", 0)
    print(f"  {cat}: {stats['trades']}t W{wr:.0%} PnL=${stats['total_pnl']:.2f} avg=${stats['avg_pnl']:.2f}")

# Orders
print("\n=== ORDER LIFECYCLE ===")
om = d.get("order_manager", {})
fr = om.get("fill_rate_stats", {})
for k, v in fr.items():
    print(f"  {k}: {v}")
print(f"  fill_rate: {om.get('fill_rate', 0):.0%}")
ml = om.get("multi_level_stats", {})
for k, v in ml.items():
    print(f"  {k}: {v}")

# Capital
print("\n=== CAPITAL ALLOCATION ===")
cap = d.get("capital", {})
print(f"Balance: ${cap.get('balance_cents',0)/100:.2f}")
print(f"Reserved: ${cap.get('reserved_cents',0)/100:.2f} ({cap.get('reserved_pct')})")
print(f"Peak reserved: ${cap.get('peak_reserved',0)/100:.2f}")
print(f"Total freed: ${cap.get('total_freed_cents',0)/100:.2f}")
print(f"Recycled trades: {cap.get('total_recycled_trades',0)}")
print(f"Orders gated: {cap.get('orders_gated',0)}")
print(f"Category gated: {cap.get('category_gated',0)}")
dep = cap.get("category_deployed", {})
if dep:
    for cat, amt in dep.items():
        print(f"  {cat}: {amt}")

# Performance
print("\n=== PERFORMANCE SNAPSHOT ===")
perf = d.get("performance", {}).get("snapshot", {})
print(f"Total PnL: ${perf.get('total_pnl', 0):.2f}")
print(f"Daily PnL: ${perf.get('daily_pnl', 0):.2f}")
print(f"Sharpe: {perf.get('sharpe_ratio', 0):.2f}")
print(f"Win rate: {perf.get('win_rate', 0):.0%}")
print(f"Largest win: ${perf.get('largest_win', 0):.2f}")
print(f"Largest loss: ${perf.get('largest_loss', 0):.2f}")

# WebSocket
print("\n=== WEBSOCKET ===")
ws = d.get("ws_bridge", {})
print(f"Connected: {ws.get('connected')}")
print(f"Messages: {ws.get('ticker_updates', 0)}")
print(f"Reconnects: {ws.get('reconnect_count')}")

# Scan debug
print("\n=== LAST SCAN ===")
ls = d.get("last_scan_debug", {})
print(f"Candidates: {ls.get('candidates', 0)}")
print(f"Signals: {ls.get('signals', 0)}")
print(f"Trade candidates: {ls.get('trade_candidates', 0)}")
print(f"Executed: {ls.get('exec_successes', 0)}")
print(f"Portfolio rejected: {ls.get('portfolio_rejections', 0)}")
print(f"Exec rejected: {ls.get('exec_rejections', 0)}")
tc = ls.get("top_candidates", [])
if tc:
    for c in tc[:5]:
        print(f"  {c}")

# Balance
print("\n=== PAPER TRADING ===")
h = fetch("/health")
pt = h.get("paper_trading", {})
print(f"Balance: ${float(pt.get('balance', 0)):.2f}")
print(f"Starting: ${float(pt.get('starting_balance', 0)):.2f}")
print(f"PnL: ${float(pt.get('pnl', 0)):.2f}")
print(f"Total trades: {pt.get('total_trades', 0)}")

# Positions
print("\n=== POSITIONS ===")
bal = fetch("/api/portfolio/balance")
print(f"Position count: {bal.get('position_count', 0)}")
print(f"Open orders: {bal.get('open_orders', 0)}")
print(f"Total exposure: ${bal.get('total_exposure', 0)/100:.2f}" if isinstance(bal.get('total_exposure'), (int, float)) and bal.get('total_exposure', 0) > 100 else f"Total exposure: ${bal.get('total_exposure', 0):.2f}")

# Check rejections
try:
    rej = fetch("/api/frankenstein/debug/rejections")
    print(f"\n=== REJECTIONS ===")
    print(f"Total: {rej.get('total_rejections', 0)}")
    reasons = rej.get("rejection_reasons", {})
    if reasons:
        for r, cnt in sorted(reasons.items(), key=lambda x: -x[1])[:10]:
            print(f"  {r}: {cnt}")
except Exception:
    pass
