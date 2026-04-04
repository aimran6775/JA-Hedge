#!/usr/bin/env python3
"""Quick Phase 25b deploy check."""
import json
import urllib.request

BASE = "https://frankensteintrading.com"

def fetch(path):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=15) as r:
        return json.loads(r.read())

st = fetch("/api/frankenstein/status")
print(f"Version:        {st['version']}")
print(f"Uptime:         {st['uptime_human']}")
print(f"Learning mode:  {st['learning_mode']}")
print(f"Learning prog:  {st['learning_progress']}")
print(f"Daily trades:   {st['daily_trades']}/{st['daily_trade_cap']}")
print(f"Total scans:    {st['total_scans']}")
print(f"Trades exec:    {st['total_trades_executed']}")
print(f"Scan debug:     {st['last_scan_debug']}")
lr = st.get('learner', {})
print(f"Model version:  {lr.get('current_version')}")
print(f"Champion:       {lr.get('champion')}")
ws = st.get('ws_bridge', {})
print(f"WS connected:   {ws.get('connected')}")
mem = st.get('memory', {})
print(f"Memory pending: {mem.get('pending')}")
print(f"Outcomes:       {mem.get('outcomes')}")
sp = st.get('strategy', {}).get('current_params', {})
print(f"Strategy:       min_conf={sp.get('min_confidence')} min_edge={sp.get('min_edge')}")

# Check rejections
print("\n--- Rejections ---")
rej = fetch("/api/frankenstein/debug/rejections")
print(f"Model trained:  {rej['model_trained']}")
print(f"Learning mode:  {rej['is_learning_mode']}")
candidates = rej.get('candidates', [])
would_exec = [c for c in candidates if c.get('would_execute')]
print(f"Candidates:     {len(candidates)}")
print(f"Would execute:  {len(would_exec)}")
gate_counts = {}
for c in candidates:
    for g in c.get('gates_blocking', []):
        key = g.split(' ')[0] + '...' if len(g) > 30 else g
        gate_counts[key] = gate_counts.get(key, 0) + 1
if gate_counts:
    print(f"Gates:          {gate_counts}")

# Show top would-execute
for c in would_exec[:5]:
    p = c['prediction']
    print(f"  {c['ticker'][:45]}: side={p['side']} edge={p['edge']:+.4f} conf={p['confidence']:.2f} grade={c['confidence_grade']['grade']}")
