#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."

git add -A
git commit -m "Phase 29: Fix 14 bugs from comprehensive audit — production-ready

CRITICAL FIXES:
- Fix dead drawdown protection: _peak_equity_cents now initialized from
  actual portfolio balance on first check (was stuck at 0)
- Fix resolver double-counting: removed duplicate category tracking from
  _report_sports_outcome (was inflating stats 2×)
- Fix NO-side inventory skew: changed qty > 0 to qty < 0 for NO position
  detection (NO-side penalty was never firing)
- Harmonize resolver Method 2 thresholds to use constants (0.98/0.02)
  instead of inconsistent hardcoded 0.95/0.05
- Remove backtest recs mutating module-level MAX_DAILY_TRADES constant
  (was silently capping to 50 trades/day)

IMPORTANT FIXES:
- Cache _is_in_learning_mode() per scan cycle (was O(N) over 50K+ trades,
  called 5+ times per scan — now cached with _learning_mode_cache)
- Fix wrong cooldown dict in _merge_strategy_engine (checked _recently_traded
  instead of _recently_traded_events for event dedup)
- Add ConfidenceScorer gate to reactive scan path (was skipping quality
  check entirely, allowing junk reactive trades)
- Fix sports-only mode: return empty list when no sports found instead of
  falling back to 50 non-sports markets
- Grade-based \$5 min bet floor: only A+/A grades get forced to \$5 minimum,
  preventing oversized positions on low-grade signals
- Sync paper trader order expiry to ORDER_STALE_SECONDS (150s) instead of
  hardcoded 300s (2× mismatch with real system)

MINOR FIXES:
- Fix holdout log: compute holdout_size before truncation (was always 0)
- Fix MarketCache docstring: removed false 'Thread-safe' claim
- Move datetime import to module level in scanner.py (was in hot loop)
"
git push origin main
