#!/usr/bin/env python3
"""Full production health audit."""
import json
import urllib.request

def fetch(path):
    url = f"https://frankensteintrading.com{path}"
    with urllib.request.urlopen(url, timeout=15) as resp:
        return json.loads(resp.read())

d = fetch("/api/frankenstein/status")
h = fetch("/health")

print("=" * 60)
print("  FRANKENSTEIN PRODUCTION HEALTH AUDIT")
print("=" * 60)

print(f"\nGeneration: {d.get('generation')}  |  Version: {d.get('version')}")
print(f"Alive: {d.get('is_alive')}  |  Trading: {d.get('is_trading')}  |  Paused: {d.get('is_paused')}")
print(f"Circuit breaker: {d.get('circuit_breaker_active')}")
print(f"Learning: {d.get('learning_mode')} ({d.get('learning_progress')})")
print(f"Real trades (from memory): {d.get('real_trades')}")
print(f"Uptime: {d.get('uptime_human')}")
print(f"Scans: {d.get('total_scans')}  |  Signals: {d.get('total_signals')}")
print(f"Daily trades: {d.get('daily_trades')}/{d.get('daily_trade_cap')}")
lsd = d.get("last_scan_debug", {})
print(f"Last scan: {d.get('last_scan_ms')}ms  |  candidates={lsd.get('candidates')} signals={lsd.get('signals')} exec={lsd.get('exec_successes')}")

# Memory
m = d.get("memory", {})
print(f"\n--- MEMORY ---")
print(f"Recorded: {m.get('total_recorded')}  |  Resolved: {m.get('total_resolved')}  |  Pending: {m.get('pending')}")
print(f"Win rate: {m.get('win_rate')}  |  PnL: {m.get('total_pnl')}  |  Avg: {m.get('avg_pnl_per_trade')}")
oc = m.get("outcomes", {})
print(f"Outcomes: W={oc.get('win')} L={oc.get('loss')} BE={oc.get('breakeven')} Exp={oc.get('expired')}")
ca = m.get("category_analytics", {})
if ca:
    print("\nCategory breakdown:")
    for cat, s in sorted(ca.items()):
        wr = s.get("win_rate", 0)
        pnl = s.get("total_pnl", 0)
        avg = s.get("avg_pnl", 0)
        t = s.get("trades", 0)
        flag = " ⚠️" if wr < 0.40 and t > 10 else ""
        print(f"  {cat:15s}: {t:4d}t  WR={wr:.1%}  PnL=${pnl:>8.2f}  avg=${avg:.3f}{flag}")

# Order manager
om = d.get("order_manager", {})
fr = om.get("fill_rate_stats", {})
rq = om.get("requote_stats", {})
fp = om.get("fill_predictor", {})
print(f"\n--- ORDER MANAGER ---")
print(f"Pending: {om.get('pending_orders')}  |  Fill rate: {om.get('fill_rate', 0):.1%}")
print(f"Placed: {fr.get('placed')}  |  Filled: {fr.get('filled')}  |  Amended: {fr.get('amended')}")
print(f"Requotes: {rq.get('requotes_attempted')} attempted / {rq.get('requotes_succeeded')} succeeded")
print(f"Fill predictor: obs={fp.get('observations')} active={fp.get('model_active')}")

# Performance
p = d.get("performance", {})
snap = p.get("snapshot", {})
print(f"\n--- PERFORMANCE ---")
print(f"Total PnL: ${snap.get('total_pnl', 0):.2f}  |  Daily: ${snap.get('daily_pnl', 0):.2f}")
print(f"Win rate: {snap.get('win_rate', 0):.1%}  |  Sharpe: {snap.get('sharpe_ratio', 0):.3f}")
print(f"Max drawdown: ${snap.get('max_drawdown', 0):.2f}  |  Regime: {snap.get('regime')}")
print(f"Model degrading: {p.get('model_degrading')}")

# Strategy
st = d.get("strategy", {})
cp = st.get("current_params", {})
print(f"\n--- STRATEGY ---")
print(f"min_conf={cp.get('min_confidence')}  min_edge={cp.get('min_edge')}  kelly={cp.get('kelly_fraction')}")
print(f"max_pos={cp.get('max_position_size')}  max_simul={cp.get('max_simultaneous_positions')}  scan={cp.get('scan_interval')}s")
print(f"aggression={st.get('aggression')}  adaptations={st.get('total_adaptations')}")

# Arb
arb = d.get("arb_scanner", {})
print(f"\n--- ARB SCANNER ---")
print(f"Scans: {arb.get('scans')}  |  Signals: {arb.get('signals_found')}  |  Trades: {arb.get('trades_triggered')}")

# Paper trading
pt = h.get("paper_trading", {})
print(f"\n--- PAPER TRADING ---")
print(f"Balance: ${pt.get('balance')}  |  PnL: ${pt.get('pnl')}  |  Trades: {pt.get('total_trades')}")

# Health components
comp = h.get("components", {})
print(f"\n--- COMPONENTS ---")
for k, v in comp.items():
    flag = " ⚠️" if v not in ("ready", "connected", "available", "active", "ok", "alive") else ""
    print(f"  {k}: {v}{flag}")

# Identify issues
print(f"\n{'=' * 60}")
print("  ISSUES DETECTED")
print("=" * 60)
issues = []

if not d.get("is_alive"):
    issues.append("❌ Frankenstein is NOT alive")
if d.get("is_paused"):
    issues.append("⚠️  Trading is PAUSED: " + d.get("pause_reason", ""))
if d.get("circuit_breaker_active"):
    issues.append("❌ Circuit breaker is ACTIVE")

wr = snap.get("win_rate", 0)
if wr < 0.40 and snap.get("total_pnl", 0) < -50:
    issues.append(f"⚠️  Low win rate {wr:.1%} with negative PnL")

fill_rate = om.get("fill_rate", 0)
if fill_rate < 0.15 and fr.get("placed", 0) > 20:
    issues.append(f"⚠️  Low fill rate: {fill_rate:.1%}")

rq_att = rq.get("requotes_attempted", 0)
rq_suc = rq.get("requotes_succeeded", 0)
if rq_att > 10 and rq_suc == 0:
    issues.append(f"❌ Requoting broken: {rq_att} attempted, 0 succeeded")

for cat, s in ca.items():
    if s.get("trades", 0) > 20 and s.get("win_rate", 0) < 0.10:
        issues.append(f"⚠️  Category '{cat}' hemorrhaging: {s['trades']}t WR={s['win_rate']:.1%}")

dd = snap.get("max_drawdown", 0)
if dd < -200:
    issues.append(f"⚠️  Large drawdown: ${dd:.2f}")

if d.get("daily_trades", 0) > d.get("daily_trade_cap", 500) * 0.9:
    issues.append(f"⚠️  Near daily trade cap: {d['daily_trades']}/{d['daily_trade_cap']}")

if p.get("model_degrading"):
    issues.append("⚠️  Model marked as degrading")

if not issues:
    print("✅ No critical issues found — system is healthy!")
else:
    for i in issues:
        print(f"  {i}")
print()
