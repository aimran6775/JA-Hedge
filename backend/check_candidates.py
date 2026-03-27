#!/usr/bin/env python3
"""Quick check: what the scan loop sees vs debug endpoint."""
import json, urllib.request

BASE = "https://api.frankensteintrading.com"

def fetch(path):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=15) as r:
        return json.loads(r.read())

# Status
st = fetch("/api/frankenstein/status")
sd = st.get('last_scan_debug', {})
print(f"Scan loop: {sd.get('candidates','?')} candidates -> {sd.get('trade_candidates','?')} trades -> {sd.get('exec_successes','?')} exec")
print(f"Total scans: {st['total_scans']}, signals: {st['total_signals']}, executed: {st['total_trades_executed']}")

# Debug
rej = fetch("/api/frankenstein/debug/rejections")
print(f"\nDebug endpoint:")
print(f"  Active: {rej.get('total_active')}, Pre-filtered: {rej.get('total_pre_filtered')}")
print(f"  Model trained: {rej.get('model_trained')}, Learning: {rej.get('is_learning_mode')}")
for c in rej.get('candidates', []):
    print(f"\n  {c['ticker'][:50]}")
    print(f"    {c['title'][:70]}")
    p = c['prediction']
    m = c['market']
    g = c['confidence_grade']
    s = c['sizing']
    print(f"    Side={p['side']}, Edge={p['edge']:.4f}, Conf={p['confidence']:.3f}")
    print(f"    Mid={m['midpoint']}, Spread={m['spread']}, Vol={m['volume']}, Fee%={m['fee_pct']:.1%}")
    print(f"    Grade={g['grade']} ({g['score']:.1f}), ShouldTrade={g['should_trade']}")
    print(f"    Kelly={s['kelly']:.4f}, NetEdge={s['net_edge']:.4f}")
    if c['gates_blocking']:
        print(f"    BLOCKED: {', '.join(c['gates_blocking'])}")
    else:
        print(f"    >>> WOULD EXECUTE")
