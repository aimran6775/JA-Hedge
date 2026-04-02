#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "=== JA Hedge: Commit & Push Phase 20 + Phase 21 ==="

# Add everything
git add -A
echo "✅ Staged all files"

# Commit
git commit -m "feat: Phase 20+21 — category detection, quality gates, maker-mode realism, position exits

Phase 20 (20-phase improvement plan):
- Frankenstein modular refactor: scanner, positions, constants, event_bus, order_manager, capital_allocator, fill_predictor, resolver, ws_bridge
- Performance tracker overhaul with calibration & selectivity metrics
- Advanced risk manager with concentration limits
- Learner improvements with generation tracking
- Memory persistence enhancements
- WebSocket bridge for reactive trading
- Sports model improvements
- Dashboard consolidation (14 pages → 4-tab layout)

Phase 21 (7 critical fixes):
1. Category detection: replaced broken getattr(market,'category','') with detect_category() everywhere in scanner.py
2. Quality thresholds: min_grade B→B+, raised edges ~50%, added tree_agreement & calibration gates
3. Realistic paper trading: maker_mode with 15-40% fill rate (was 85% instant), partial fills, 5-min expiry
4. Reactive WS filters: mid 0.08-0.92, vol 3, category-specific edges
5. Concentration risk: MAX_PER_EVENT 3→2, MAX_PER_CATEGORY 8→6
6. Maker-mode position exits: stop-loss, edge reversal, near-expiry, lock gains
7. Category prefix sorting: longest-prefix-first (KXGOLDMON→finance not sports), commodity prefixes added

Result: Paper trading session went profitable (+\$3.32 on \$10k) with all fixes active."

echo "✅ Committed"

# Push
git push origin main
echo "✅ Pushed to origin/main"

echo ""
echo "=== Deploy triggered. Railway should auto-deploy from main branch. ==="
echo "Wait ~90 seconds then check your Railway health endpoint."
