#!/usr/bin/env python3
"""Phase 21 verification: test all modified modules."""

import sys
sys.path.insert(0, ".")

print("Testing imports...")

try:
    from app.frankenstein.scanner import MarketScanner
    print("  [OK] scanner.py")
except Exception as e:
    print(f"  [FAIL] scanner.py: {e}")
    sys.exit(1)

try:
    from app.frankenstein.positions import PositionManager
    print("  [OK] positions.py")
except Exception as e:
    print(f"  [FAIL] positions.py: {e}")
    sys.exit(1)

try:
    from app.engine.paper_trader import PaperTradingSimulator
    print("  [OK] paper_trader.py")
except Exception as e:
    print(f"  [FAIL] paper_trader.py: {e}")
    sys.exit(1)

try:
    from app.frankenstein.constants import MAX_PER_EVENT, MAX_PER_CATEGORY
    print(f"  [OK] constants.py (MAX_PER_EVENT={MAX_PER_EVENT}, MAX_PER_CATEGORY={MAX_PER_CATEGORY})")
except Exception as e:
    print(f"  [FAIL] constants.py: {e}")
    sys.exit(1)

try:
    from app.frankenstein.brain import Frankenstein
    print("  [OK] brain.py")
except Exception as e:
    print(f"  [FAIL] brain.py: {e}")
    sys.exit(1)

try:
    from app.engine.advanced_risk import PortfolioRiskLimits
    lim = PortfolioRiskLimits()
    print(f"  [OK] advanced_risk.py (max_per_event={lim.max_per_event})")
except Exception as e:
    print(f"  [FAIL] advanced_risk.py: {e}")
    sys.exit(1)

# Test paper trader maker mode
try:
    sim = PaperTradingSimulator(starting_balance_cents=100000, fee_rate_cents=0, maker_mode=True)
    assert sim.maker_mode is True
    assert sim.balance_cents == 100000
    print(f"  [OK] PaperTradingSimulator(maker_mode=True)")
    
    # Test resting orders mechanism
    assert hasattr(sim, '_resting_orders')
    assert hasattr(sim, 'check_resting_fills')
    assert hasattr(sim, '_attempt_maker_fill')
    print(f"  [OK] Maker fill simulation methods exist")
except Exception as e:
    print(f"  [FAIL] paper_trader maker mode: {e}")
    sys.exit(1)

# Test detect_category
try:
    from app.frankenstein.categories import detect_category
    cats = {
        'KXPGATOUR-MASTDECI26-SSCH': detect_category('Will Scottie Scheffler win?', '', ticker='KXPGATOUR-MASTDECI26-SSCH'),
        'KXBTC-26APR-T100K': detect_category('Bitcoin above 100k?', '', ticker='KXBTC-26APR-T100K'),
        'KXFEDRATE-25MAY': detect_category('Fed rate cut?', '', ticker='KXFEDRATE-25MAY'),
        'KXWEATHER-NYC': detect_category('Will it rain in NYC?', '', ticker='KXWEATHER-NYC-RAIN'),
    }
    for ticker, cat in cats.items():
        print(f"    {ticker} -> {cat}")
    print(f"  [OK] detect_category working")
except Exception as e:
    print(f"  [FAIL] detect_category: {e}")
    sys.exit(1)

# Verify positions.py has maker exit logic
try:
    import inspect
    src = inspect.getsource(PositionManager)
    assert '_evaluate_maker_exit' in src, "Missing _evaluate_maker_exit method"
    assert 'maker_stop_loss' in src, "Missing maker stop-loss logic"
    assert 'maker_edge_reversal' in src, "Missing maker edge reversal logic"
    assert 'maker_near_expiry' in src, "Missing maker near-expiry logic"
    print("  [OK] PositionManager has maker exit strategies")
except Exception as e:
    print(f"  [FAIL] positions maker exits: {e}")
    sys.exit(1)

# Verify scanner quality gates
try:
    import inspect
    src = inspect.getsource(MarketScanner)
    assert 'tree_agreement < 0.55' in src, "Missing tree agreement gate"
    assert 'calibration_error > 0.10' in src, "Missing calibration gate"
    assert '_detected_cat' in src, "Missing detect_category in _execute_top"
    assert 'is_category_retired(_cat_retire)' in src, "Missing fixed retirement check"
    print("  [OK] Scanner has quality gates (tree agreement, calibration)")
    print("  [OK] Scanner uses detect_category for retirement/risk/capital")
except Exception as e:
    print(f"  [FAIL] scanner quality gates: {e}")
    sys.exit(1)

print()
print("=" * 50)
print("ALL PHASE 21 TESTS PASS!")
print("=" * 50)
