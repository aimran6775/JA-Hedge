#!/usr/bin/env python3
"""Pull live performance summary from frankensteintrading.com"""
import json
import urllib.request

BASE = "https://frankensteintrading.com"


def fetch(path):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=15) as r:
        return json.loads(r.read())


an = fetch("/api/frankenstein/analytics")
perf = fetch("/api/frankenstein/performance")
st = fetch("/api/frankenstein/status")
bal = fetch("/api/portfolio/balance")
risk = fetch("/api/risk/snapshot")
health = fetch("/health")

print("=" * 64)
print("LIVE FRANKENSTEIN — frankensteintrading.com")
print("=" * 64)
print(f"Mode:             {health.get('mode')} (effective: {health.get('effective_mode')})")
print(f"Paper trading:    {health.get('paper_trading',{}).get('enabled')}")
print(f"Uptime:           {st.get('uptime_human')} ({st.get('uptime_seconds',0)/86400:.1f} days)")
print(f"Generation:       {st.get('generation')} (model: {st.get('version')})")
print(f"Alive/Trading:    {st.get('is_alive')} / {st.get('is_trading')} / paused={st.get('is_paused')}")
print(f"Real trades:      {st.get('real_trades')}")
print(f"Total scans:      {st.get('total_scans')}")
print(f"Signals:          {st.get('total_signals')}")
print(f"Trades exec/rej:  {st.get('total_trades_executed')} / {st.get('total_trades_rejected')}")
print()
print("--- BALANCE ---")
pt = health.get("paper_trading", {})
print(f"Start balance:    ${pt.get('starting_balance')}")
print(f"Current balance:  ${bal.get('balance_dollars')}")
print(f"Paper P&L:        ${pt.get('pnl')}  (over {pt.get('total_trades')} paper trades)")
print(f"Total exposure:   ${bal.get('total_exposure')}")
print(f"Open positions:   {bal.get('position_count')}")
print(f"Open orders:      {bal.get('open_orders')}")
print()
ov = an.get("overview", {})
print("--- TRADE OUTCOMES (Frank memory) ---")
print(f"Total trades:     {ov.get('total_trades')}")
print(f"Pending:          {ov.get('pending_trades')}")
print(f"Win rate:         {ov.get('win_rate', 0)*100:.1f}%")
print(f"Total P&L:        ${ov.get('total_pnl_dollars')}")
print(f"ROI:              {ov.get('roi_pct')}%")
print(f"Profit factor:    {ov.get('profit_factor')}")
print(f"Total cost:       ${ov.get('total_cost_dollars')}")
print()
sn = perf.get("snapshot", {})
print("--- PERF METRICS ---")
print(f"Total P&L:        ${sn.get('total_pnl', 0):.2f}")
print(f"Daily P&L:        ${sn.get('daily_pnl', 0):.2f}")
print(f"Sharpe:           {sn.get('sharpe_ratio', 0):.2f}")
print(f"Max drawdown:     ${sn.get('max_drawdown', 0):.2f}")
print(f"Largest win:      ${sn.get('largest_win', 0):.2f}")
print(f"Largest loss:     ${sn.get('largest_loss', 0):.2f}")
print()
print("--- BY CATEGORY ---")
for cat, d in an.get("by_category", {}).items():
    print(
        f"  {cat:15} trades={d.get('trades'):4}  "
        f"WR={d.get('win_rate', 0)*100:5.1f}%  "
        f"PnL=${d.get('pnl_dollars', 0):8.2f}  "
        f"ROI={d.get('roi_pct', 0):7.1f}%"
    )
