#!/usr/bin/env python3
"""Check Phase 31 deployment status."""
import json, urllib.request, sys

url = "https://frankensteintrading.com/api/frankenstein/status"
req = urllib.request.Request(url)
with urllib.request.urlopen(req, timeout=15) as resp:
    d = json.loads(resp.read())

print("=== FRANKENSTEIN STATUS ===")
print(f"Alive: {d.get('is_alive')}")
print(f"Trading: {d.get('is_trading')}")
print(f"Model: {d.get('model_version')}")
print(f"Generation: {d.get('generation')}")
print(f"Scans: {d.get('total_scans')}")
print(f"Trades: {d.get('total_trades_executed')}")
print(f"Daily: {d.get('daily_trade_count')}")
print(f"Circuit Breaker: {d.get('circuit_breaker_triggered')}")
print()

# Arb scanner
arb = d.get("arb_scanner") or {}
print("=== ARB SCANNER ===")
print(f"Scans: {arb.get('scans', 'N/A')}")
print(f"Signals Found: {arb.get('signals_found', 'N/A')}")
print(f"Trades Triggered: {arb.get('trades_triggered', 'N/A')}")
print(f"Active Signals: {arb.get('active_signals', 'N/A')}")
print(f"By Source: {arb.get('by_source', {})}")
for s in (arb.get("top_signals") or [])[:3]:
    print(f"  -> {s['ticker']}: {s['source']} edge={s['edge']} side={s['side']}")
print()

# Fill predictor
fp = d.get("fill_predictor") or {}
print("=== FILL PREDICTOR ===")
print(f"Observations: {fp.get('total_observations', 'N/A')}")
print(f"Trained: {fp.get('is_trained', 'N/A')}")
print()

# Order manager
om = d.get("order_manager") or {}
frs = om.get("fill_rate_stats") or {}
print("=== ORDER MANAGER ===")
print(f"Placed: {frs.get('placed', 0)}, Filled: {frs.get('filled', 0)}, Amended: {frs.get('amended', 0)}")
rqs = om.get("requote_stats") or {}
print(f"Requotes: attempted={rqs.get('requotes_attempted',0)}, succeeded={rqs.get('requotes_succeeded',0)}")
print(f"Fill Rate: {om.get('fill_rate', 'N/A')}")
print()

# Performance
perf = d.get("performance") or {}
print("=== PERFORMANCE ===")
print(f"Win Rate: {perf.get('win_rate', 'N/A')}")
print(f"Total PnL: {perf.get('total_pnl_cents', 'N/A')}c")
print(f"Sharpe: {perf.get('sharpe_ratio', 'N/A')}")
print(f"Real Trades: {perf.get('real_trades', 'N/A')}")
print()

# Strategy
strat = d.get("strategy") or {}
params = strat.get("current_params") or {}
print("=== STRATEGY ===")
print(f"Adaptations: {strat.get('total_adaptations', 'N/A')}")
print(f"Aggression: {strat.get('aggression', 'N/A')}")
print(f"Min Confidence: {params.get('min_confidence', 'N/A')}")
print(f"Min Edge: {params.get('min_edge', 'N/A')}")
print(f"Kelly: {params.get('kelly_fraction', 'N/A')}")
