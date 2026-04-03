#!/bin/bash
set -e
cd "$(dirname "$0")/../.."

echo "=== Phase 24+24b: Commit & Push ==="
git add -A
git commit -m "Phase 24+24b: Fix all broken data sources, retirement logic, DB models

Phase 24 fixes:
- memory.py: Backfill categories on load() using detect_category()
- performance.py: Loosen retirement thresholds (WR 28→22%, min_trades 20→30)
- routes/frankenstein.py: Fix all frank._* → frank._scanner._* references
- db/models.py: Add ForeignKey to PriceSnapshot.ticker
- order_manager.py: Paper fill rate detection
- sports_odds.py: Full rewrite DK/FD → ESPN public scoreboard API
- google_trends.py: Full rewrite dead API → RSS feed

Phase 24b retirement overhaul:
- performance.py: Session-aware rolling window for retirement evaluation
  - Only evaluates trades from current session (not poisoned by old model)
  - Rolling window of last 50 trades per category
  - Add unretire_category() and unretire_all() methods
- routes/frankenstein.py: Add POST /categories/unretire endpoint
  - Force-unretire one or all categories
  - GET /categories/retirement-stats for rolling window diagnostics

Result: Trades flowing again (20+ executed, 0 rejected in first 6 scans)"
git push origin main
echo "=== Push complete ==="
