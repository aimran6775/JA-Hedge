#!/bin/bash
cd "$(dirname "$0")/../.."

git add -A && \
git commit -m "Phase 30: Sports Predictor V2 — multi-signal fusion + hedging + circuit breaker

New: predictor_v2.py (~550 LOC)
- SportsPredictorV2: 4-signal fusion (Vegas, social, line movement, live game)
- SportsCircuitBreaker: per-category auto-pause after 8 losses or <20% WR
- SportsHedger: cross-market hedge detection on same game events
- Time-decay on stale data (30min dead threshold)
- Signal agreement scoring for trade quality

scanner.py:
- V2 predictor primary, V1 as fallback
- Sports Kelly multiplier 0.9 → 1.3
- Hedge registration on successful execution
- Grade-based sizing boost for hedged/high-agreement trades
- Fixed has_vegas detection for V2 predictions

brain.py: Wire V2 predictor to scanner + resolver
resolver.py: Feed circuit breaker outcomes + fix sports_risk position leak
capital_allocator.py: Sports share 15% → 30%
main.py: Import and inject predictor_v2 into Frankenstein" && \
git push origin main

echo "Done: $(git log --oneline -1)"
