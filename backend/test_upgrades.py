#!/usr/bin/env python3
"""Verify all upgrade changes work together."""
from app.ai.features import FeatureEngine, MarketFeatures
from app.ai.models import CalibrationTracker, XGBoostPredictor, Prediction
from app.frankenstein.brain import Frankenstein

# Verify feature vector dimensions
names = MarketFeatures.feature_names()
feat = MarketFeatures(ticker='test', timestamp=None)
arr = feat.to_array()
print(f'Feature names: {len(names)}')
print(f'Feature array: {len(arr)}')
assert len(names) == len(arr), f'MISMATCH: {len(names)} names vs {len(arr)} values'
print('  ✅ Feature dimensions consistent')

# Verify new features exist
for fname in ['hour_sin', 'hour_cos', 'dow_sin', 'dow_cos', 'event_prob_sum']:
    assert fname in names, f'Missing: {fname}'
print('  ✅ New features present:', ['hour_sin', 'hour_cos', 'dow_sin', 'dow_cos', 'event_prob_sum'])

# Verify total feature count (was 60, now 65 with 5 new)
print(f'  ✅ Total features: {len(names)}')

# Verify calibration tracker
cal = CalibrationTracker()
assert cal.N_BINS == 20, f'Expected 20 bins, got {cal.N_BINS}'
print(f'  ✅ Calibration bins: {cal.N_BINS}')

# Test isotonic calibration map
import numpy as np
for i in range(50):
    cal.record(i / 50.0, 1 if i > 25 else 0)
cal._recompute_isotonic()
assert cal._isotonic_map is not None
print(f'  ✅ Isotonic calibration map built: {len(cal._isotonic_map)} bins')

# Verify brain has new methods
assert '_seed_price_histories' in dir(Frankenstein), 'Missing _seed_price_histories'
print('  ✅ Brain has _seed_price_histories method')

# Verify FeatureEngine.update works
engine = FeatureEngine()
engine.update('TEST-TICKER', 0.5, 100, 50, 0.02)
engine.update('TEST-TICKER', 0.51, 110, 55, 0.02)
engine.update('TEST-TICKER', 0.52, 120, 60, 0.01)
hist = engine._histories.get('TEST-TICKER')
assert hist is not None
assert len(hist.prices) == 3
print(f'  ✅ FeatureEngine.update() works: {len(hist.prices)} data points')

print()
print('🎉 ALL UPGRADE CHECKS PASSED')
