#!/usr/bin/env python3
"""Quick P&L + data-source audit."""
import json, urllib.request

BASE = "https://frankensteintrading.com"

def fetch(path):
    req = urllib.request.Request(f"{BASE}{path}", headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

h = fetch("/health")
d = fetch("/api/frankenstein/status")
perf = d.get("performance", {})
snap = perf.get("snapshot", {})
by_cat = perf.get("by_category", {})
mem = d.get("memory", {})
outcomes = mem.get("outcomes", {})
pt = h.get("paper_trading", {})

print("=" * 60)
print("  FRANKENSTEIN LIVE AUDIT — Is it profitable? Is it real?")
print("=" * 60)

print()
print("── DATA SOURCE ──")
print(f"  API endpoint:     {h.get('rest_url')}")
print(f"  Mode config:      {h.get('mode')}")
print(f"  Effective mode:   {h.get('effective_mode')}")
print(f"  Has API keys:     {h.get('has_api_keys')}")
print(f"  Paper trading:    {pt.get('enabled')}")
print()

is_prod = "elections.kalshi.com" in (h.get("rest_url") or "")
print(f"  → Market data is {'REAL (production Kalshi)' if is_prod else 'SANDBOX (demo)'}")
print(f"  → Orders go to {'PAPER SIMULATOR (fake money)' if pt.get('enabled') else 'LIVE KALSHI (real money)'}")

print()
print("── PROFITABILITY ──")
print(f"  Starting balance: ${pt.get('starting_balance', '?')}")
print(f"  Current balance:  ${pt.get('balance', '?')}")
print(f"  Paper PnL:        ${pt.get('pnl', '?')}")
print(f"  Total trades:     {pt.get('total_trades', '?')}")
print()
print(f"  Resolved PnL:     ${snap.get('total_pnl', 0):.2f}")
print(f"  Today's PnL:      ${snap.get('daily_pnl', 0):.2f}")
print(f"  Win Rate:         {snap.get('win_rate', 0):.1%}")
print(f"  Profit Factor:    {snap.get('profit_factor', 0):.2f}")
print(f"  Avg Win:          ${snap.get('avg_win', 0):.2f}")
print(f"  Avg Loss:         ${snap.get('avg_loss', 0):.2f}")
print(f"  Largest Win:      ${snap.get('largest_win', 0):.2f}")
print(f"  Largest Loss:     ${snap.get('largest_loss', 0):.2f}")
print(f"  Sharpe Ratio:     {snap.get('sharpe_ratio', 0):.3f}")
print(f"  Max Drawdown:     ${snap.get('max_drawdown', 0):.2f}")

print()
print("── TRADE OUTCOMES ──")
print(f"  Wins:       {outcomes.get('win', 0)}")
print(f"  Losses:     {outcomes.get('loss', 0)}")
print(f"  Breakeven:  {outcomes.get('breakeven', 0)}")
print(f"  Expired:    {outcomes.get('expired', 0)}")
print(f"  Pending:    {outcomes.get('pending', 0)}")

wins = outcomes.get("win", 0)
losses = outcomes.get("loss", 0)
total_decided = wins + losses
if total_decided > 0:
    real_wr = wins / total_decided
    print(f"  → Win/Loss WR:  {real_wr:.1%}  ({wins}W / {losses}L)")

print()
print("── BY CATEGORY (sorted by PnL) ──")
for cat, s in sorted(by_cat.items(), key=lambda x: x[1].get("total_pnl", 0), reverse=True):
    t = s.get("trades", 0)
    wr = s.get("win_rate", 0)
    pnl = s.get("total_pnl", 0)
    avg = s.get("avg_pnl", 0)
    print(f"  {cat:18s}  {t:5d} trades  WR={wr:5.1%}  PnL=${pnl:+8.2f}  avg=${avg:+.3f}")

print()
print("── SYSTEM STATE ──")
print(f"  Generation:   {d.get('generation')}")
print(f"  Uptime:       {d.get('uptime_human')}")
print(f"  Daily trades: {d.get('daily_trades')} / {d.get('daily_trade_cap')}")
print(f"  Learning:     {d.get('learning_mode')} ({d.get('learning_progress')})")
print(f"  Retired cats: {perf.get('retired_categories', {})}")

# Check recent trades for real signals
recent = fetch("/api/frankenstein/memory/recent?n=5")
print()
print("── LAST 5 TRADES (showing real signals?) ──")
for t in recent:
    print(f"  {t['action']:4s}  conf={t['confidence']:.3f}  edge={t['edge']:+.4f}  "
          f"mv={t.get('model_version','?')[:15]}  {t['ticker'][:50]}")

print()
print("=" * 60)
print("VERDICT:")
pnl_val = float(pt.get("pnl", "0"))
if pnl_val > 0:
    print(f"  ✅ PROFITABLE: +${pnl_val:.2f} ({pnl_val/100:.1f}% return)")
else:
    print(f"  ❌ NOT PROFITABLE: ${pnl_val:.2f}")
print(f"  {'✅' if is_prod else '❌'} Market data: {'Real Kalshi production prices' if is_prod else 'Sandbox/demo prices'}")
print(f"  {'⚠️' if pt.get('enabled') else '✅'} Execution: {'PAPER (simulated fills, no real money)' if pt.get('enabled') else 'LIVE (real money)'}")
print("=" * 60)
