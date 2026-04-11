#!/usr/bin/env python3
"""Analyze Frankenstein performance and suggest optimizations."""
import json
import subprocess

# Fetch status
result = subprocess.run(
    ["curl", "-s", "https://frankensteintrading.com/api/frankenstein/status"],
    capture_output=True, text=True
)
d = json.loads(result.stdout)

perf = d.get('performance', {}).get('snapshot', {})
print('=== PERFORMANCE ===')
print(f"Total PnL: ${perf.get('total_pnl', 0):.2f}")
print(f"Win Rate: {perf.get('win_rate', 0)*100:.1f}%")
print(f"Avg Win: ${perf.get('avg_win', 0):.2f}")
print(f"Avg Loss: ${perf.get('avg_loss', 0):.2f}")
print(f"Profit Factor: {perf.get('profit_factor', 0):.2f}")
print(f"Sharpe: {perf.get('sharpe_ratio', 0):.2f}")
print(f"Trades: {perf.get('total_trades', 0)} | Today: {perf.get('trades_today', 0)}")

print('\n=== TOP CATEGORIES (by PnL) ===')
cats = d.get('performance', {}).get('by_category', {})
for cat, data in sorted(cats.items(), key=lambda x: x[1].get('total_pnl', 0), reverse=True):
    pnl = data.get('total_pnl', 0)
    wr = data.get('win_rate', 0) * 100
    trades = data.get('trades', 0)
    avg = data.get('avg_pnl', 0)
    print(f"  {cat:15} ${pnl:>8.2f} | WR: {wr:>5.1f}% | {trades:>4} trades | avg: ${avg:.3f}")

print('\n=== STRATEGY PARAMS ===')
s = d.get('strategy', {}).get('current_params', {})
print(f"  Min Confidence: {s.get('min_confidence', 0):.3f}")
print(f"  Min Edge: {s.get('min_edge', 0):.4f}")
print(f"  Kelly Fraction: {s.get('kelly_fraction', 0):.3f}")
print(f"  Max Position Size: {s.get('max_position_size', 0)}")
print(f"  Max Simultaneous: {s.get('max_simultaneous_positions', 0)}")
print(f"  Max Daily Loss: ${s.get('max_daily_loss', 0):.0f}")

print('\n=== CAPITAL UTILIZATION ===')
c = d.get('capital', {})
bal = c.get('balance_cents', 0) / 100
res = c.get('reserved_cents', 0) / 100
avail = c.get('available_cents', 0) / 100
max_budget = c.get('max_trade_budget_cents', 0) / 100
print(f"  Balance: ${bal:.2f}")
print(f"  Reserved: ${res:.2f} ({res/bal*100:.2f}%)")
print(f"  Available: ${avail:.2f}")
print(f"  Max Trade Budget: ${max_budget:.2f}")
print(f"  Orders Approved: {c.get('orders_approved', 0)}")
print(f"  Orders Gated: {c.get('orders_gated', 0)}")

print('\n=== ORDER MANAGER ===')
om = d.get('order_manager', {})
frs = om.get('fill_rate_stats', {})
print(f"  Placed: {frs.get('placed', 0)} | Filled: {frs.get('filled', 0)} | Cancelled: {frs.get('cancelled', 0)}")
print(f"  Fill Rate: {om.get('fill_rate', 0)*100:.1f}%")
print(f"  Pending Orders: {om.get('pending_orders', 0)}")

print('\n=== BOTTLENECKS IDENTIFIED ===')
# Identify issues
issues = []

# 1. Capital underutilization
if res / bal < 0.05:
    issues.append(f"CAPITAL IDLE: Only {res/bal*100:.1f}% deployed. Increase position sizes or trade more.")

# 2. Low win rate categories draining profits
losing_cats = [(cat, data) for cat, data in cats.items() 
               if data.get('total_pnl', 0) < -5 and data.get('trades', 0) > 20]
for cat, data in losing_cats:
    issues.append(f"LOSING CATEGORY: {cat} has ${data['total_pnl']:.2f} PnL - consider reducing allocation")

# 3. Low fill rate
if om.get('fill_rate', 0) < 0.7:
    issues.append(f"LOW FILL RATE: {om.get('fill_rate',0)*100:.0f}% - tighten pricing or use more aggressive quotes")

# 4. Position size too small
if s.get('max_position_size', 0) < 50:
    issues.append(f"SMALL POSITIONS: max_position_size={s.get('max_position_size')} - increase for faster compounding")

# 5. Check daily trade count
if perf.get('trades_today', 0) < 50:
    issues.append(f"LOW ACTIVITY: Only {perf.get('trades_today',0)} trades today - lower thresholds or scan faster")

for i, issue in enumerate(issues, 1):
    print(f"  {i}. {issue}")

if not issues:
    print("  No major bottlenecks detected!")

print('\n=== RECOMMENDATIONS TO 2X ===')
print("  1. Increase max_position_size from 31 to 75 (bigger bets on high-confidence)")
print("  2. Increase kelly_fraction from 0.24 to 0.35 (more aggressive sizing)")
print("  3. Focus on crypto (92% WR, +$221) - increase category allocation")
print("  4. Reduce politics allocation (0% WR, -$14)")
print("  5. Lower min_edge from 0.038 to 0.025 (more trades)")
print("  6. Faster scan_interval: 15s -> 10s")
