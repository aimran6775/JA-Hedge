#!/usr/bin/env python3
"""Check live portfolio and position details."""
import json
import urllib.request

BASE = "https://frankensteintrading.com"

def fetch(path):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=15) as r:
        return json.loads(r.read())

# Portfolio
print("=" * 60)
print("PORTFOLIO & POSITIONS")
print("=" * 60)

try:
    bal = fetch("/api/portfolio/balance")
    print(f"\nBalance: ${bal.get('balance_dollars', '?')}")
    print(f"Starting: $100.00 (paper)")
    profit = float(bal.get('balance_dollars', '10000').replace(',', '')) - 10000
    print(f"Profit/Loss: ${profit:+.2f} ({profit/10000*100:+.2f}%)")
    print(f"Positions: {bal.get('position_count', 0)}")
    print(f"Open orders: {bal.get('open_orders', 0)}")
except Exception as e:
    print(f"Balance error: {e}")

# Positions
print(f"\n--- Open Positions ---")
try:
    positions = fetch("/api/portfolio/positions")
    pos_list = positions if isinstance(positions, list) else positions.get('positions', positions.get('market_positions', []))
    for p in pos_list[:20]:
        ticker = p.get('ticker', '?')
        qty = p.get('position', p.get('total_traded', 0))
        cost = p.get('total_cost', 0)
        value = p.get('market_value', p.get('resting_orders_count', 0))
        print(f"  {ticker}: qty={qty}, cost={cost}")
except Exception as e:
    print(f"Positions error: {e}")

# Fills
print(f"\n--- Recent Fills ---")
try:
    fills = fetch("/api/portfolio/fills?limit=30")
    fill_list = fills if isinstance(fills, list) else fills.get('fills', [])
    print(f"Total fills: {len(fill_list)}")
    for f in fill_list[:15]:
        ticker = f.get('ticker', '?')[:40]
        side = f.get('side', '?')
        price = f.get('yes_price', f.get('no_price', '?'))
        count = f.get('count', 1)
        ts = f.get('created_time', '?')
        action = f.get('action', '?')
        print(f"  {ticker:40s} {side:3s} px={price} ct={count} act={action} @ {str(ts)[:19]}")
except Exception as e:
    print(f"Fills error: {e}")

# Frankenstein trades endpoint
print(f"\n--- Frankenstein Status Deep ---")
try:
    st = fetch("/api/frankenstein/status")

    # Check model info
    model = st.get('model', {})
    print(f"\nModel:")
    print(f"  Version: {model.get('version')}")
    print(f"  Features: {model.get('feature_count')}")
    print(f"  Training samples: {model.get('training_samples')}")
    print(f"  is_trained: {model.get('is_trained')}")

    # Active positions from Frankenstein
    active = st.get('active_positions', {})
    print(f"\nActive positions: {active.get('count', 0)}")
    positions_list = active.get('positions', [])
    for p in positions_list:
        print(f"  {p.get('ticker', '?')}: side={p.get('side', '?')} qty={p.get('quantity', '?')} entry={p.get('entry_price', '?')} held={p.get('held_time', '?')}")

    # Scanner stats
    scanner = st.get('scanner', {})
    print(f"\nScanner:")
    print(f"  Last scan: {scanner.get('last_scan_time', '?')}")
    print(f"  Markets scanned: {scanner.get('markets_scanned', 0)}")
    print(f"  Candidates found: {scanner.get('candidates_found', 0)}")

    # Settings
    settings = st.get('settings', {})
    print(f"\nSettings:")
    print(f"  sports_only: {settings.get('sports_only_mode')}")
    print(f"  paper_trading: {settings.get('paper_trading')}")

except Exception as e:
    print(f"Status error: {e}")

# Check rejections for insight
print(f"\n--- Rejection Analysis ---")
try:
    rej = fetch("/api/frankenstein/debug/rejections")
    rejections = rej.get("rejections", [])
    reasons = {}
    for r in rejections:
        reason = r.get("last_rejection_reason", "unknown")
        reasons[reason] = reasons.get(reason, 0) + 1
    print(f"Rejection reasons (top 10):")
    for reason, count in sorted(reasons.items(), key=lambda x: -x[1])[:10]:
        print(f"  {count:3d}x  {reason}")
except Exception as e:
    print(f"Rejections error: {e}")
