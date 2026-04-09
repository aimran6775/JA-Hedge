#!/usr/bin/env python3
"""Quick status check for gen 32."""
import json
import urllib.request

def fetch(path):
    url = f"https://frankensteintrading.com{path}"
    with urllib.request.urlopen(url, timeout=15) as resp:
        return json.loads(resp.read())

d = fetch("/api/frankenstein/status")

print(f"Gen: {d.get('generation')} | Version: {d.get('version')}")
print(f"Alive: {d.get('is_alive')} | Trading: {d.get('is_trading')} | Paused: {d.get('is_paused')}")
print(f"Uptime: {d.get('uptime_human')} | Scans: {d.get('total_scans')} | Signals: {d.get('total_signals')} | Daily: {d.get('daily_trades')}")
print(f"Learning: {d.get('learning_mode')} ({d.get('learning_progress')})")

st = d.get('strategy', {}).get('current_params', {})
print(f"\nStrategy: conf={st.get('min_confidence')} edge={st.get('min_edge')} kelly={st.get('kelly_fraction')}")
print(f"  max_pos={st.get('max_position_size')} aggression={st.get('aggression')}")
print(f"  adaptations={d.get('strategy',{}).get('total_adaptations')}")

lsd = d.get('last_scan_debug', {})
print(f"\nLast scan: {json.dumps(lsd)}")

p = d.get('performance', {})
print(f"Retired categories: {p.get('retired_categories', {})}")

om = d.get('order_manager', {})
fr = om.get('fill_rate_stats', {})
rq = om.get('requote_stats', {})
print(f"\nOrders: placed={fr.get('placed')} filled={fr.get('filled')} fill_rate={om.get('fill_rate',0):.1%}")
print(f"Requotes: {rq.get('requotes_attempted')}/{rq.get('requotes_succeeded')} succeeded")
print(f"Pending: {om.get('pending_orders')}")

m = d.get('memory', {})
ca = m.get('category_analytics', {})
print(f"\nMemory: recorded={m.get('total_recorded')} resolved={m.get('total_resolved')} WR={m.get('win_rate')} PnL={m.get('total_pnl')}")
if ca:
    print("Categories:")
    for cat, s in sorted(ca.items()):
        print(f"  {cat:15s}: {s.get('trades',0):4d}t  WR={s.get('win_rate',0):.1%}  PnL=${s.get('total_pnl',0):>8.2f}")

h = fetch("/health")
pt = h.get("paper_trading", {})
print(f"\nPaper: balance=${pt.get('balance')} PnL=${pt.get('pnl')} trades={pt.get('total_trades')}")
