#!/bin/bash
set -e
cd "$(dirname "$0")/../.."

echo "=== Phase 27: Aggressive Capital Deployment ==="
echo ""
echo "Key changes:"
echo "  • Position sizing: 5→20 contracts, Kelly 0.15→0.30"
echo "  • Portfolio limits: $1.5K→$5K deployed, 50→150 positions"
echo "  • Daily trades: 300→500, scan interval 20s→15s"
echo "  • Edge thresholds: 4-8%→3-5% category min edges"
echo "  • Fill rate: confidence skew +2¢ across all tiers"
echo "  • Risk: $150→$500 daily loss, 15%→25% max drawdown"
echo "  • 24/7: liquidity factor 0.4→0.65 overnight, 0.5→0.70 weekend"
echo "  • Trade all categories + 15-min crypto (model trained on these)"
echo ""

# Verify
cd backend
python -c "from app.main import app; print('Import OK')"
cd ..

# Deploy
git add -A
git commit -m "Phase 27: aggressive capital deployment — 10x position sizing, 3x portfolio, 24/7 trading

GOAL: Double \$10K paper trading balance.

Position Sizing:
- Kelly 0.15→0.30, max_position_size 5→20 contracts
- Grade-based: A+ gets 5 min, A gets 3, B+ gets 2
- Category Kelly multipliers raised across the board

Portfolio Limits:
- max_portfolio_cost: \$1,500→\$5,000 (50% of capital)
- max_positions: 50→150 concurrent positions
- max_per_event: 2→5, max_per_category: 10→25
- max_daily_loss: \$150→\$500, max_drawdown: 15%→25%
- Capital reserved: 70%→85%, min balance: \$3→\$1

Edge & Signal Thresholds:
- Category min edges: 5-8%→3-5% (model AUC 0.77 supports this)
- Absolute min edge: 4%→2.5% graduated
- Confidence min_grade: B+→B for more trade flow
- Edge caps raised +3-5% across all categories
- Unlocked 15-min crypto markets (bootstrap trained on these)

Fill Rate Improvements:
- Confidence skew: +2¢ across all tiers (bid+6¢ for best signals)
- Wide-spread bonus: +2¢ for ≥10¢ spread, +1¢ for ≥6¢
- Order stale timeout: 4 min→2.5 min (faster capital recycling)

24/7 Trading:
- Liquidity factor: weekend 0.5→0.70, overnight 0.4→0.65
- Scan interval: 20s→15s
- Cooldowns: ticker 60→30s, event 30→15s
- Daily trades: 300→500"

git push origin main

echo ""
echo "=== Deploy initiated. This is the aggressive config. ==="
echo "After ~90s: curl https://frankensteintrading.com/health"
