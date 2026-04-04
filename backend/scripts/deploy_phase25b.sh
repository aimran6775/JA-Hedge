#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."

echo "=== Phase 25b: Fix Learning Mode Detection ==="
echo ""

# Verify import chain
echo "🔍 Verifying imports..."
source .venv/bin/activate 2>/dev/null || true
python -c "from app.main import app; print('✅ Import chain OK')"

# Commit and push
cd ..
echo ""
echo "📦 Committing..."
git add -A
git commit -m "Phase 25b: Fix learning mode — use training data count, not model.is_trained

Root cause: Scanner/positions used 'not model.is_trained' for learning mode,
but a stale checkpoint from the churn phase loaded at startup, making
is_trained=True with ZERO usable training data.  This forced the system
into strict non-learning filters (B+ min grade, higher edge thresholds)
while the degenerate model predicted everything at 0.99 confidence.

Fixes:
- scanner.py: Added _is_in_learning_mode() that checks memory for
  trades with definitive market_result (yes/no). Replaced all 7
  is_trained checks.
- positions.py: Same pattern — added memory dependency + learning
  mode helper. Hold-to-settlement and edge reversal gates now use
  actual training data count.
- brain.py: Added is_in_learning_mode property. Stale checkpoint
  auto-detected and reset to heuristic if no usable training data.
  status() now uses unified learning mode.
- routes/frankenstein.py: Rejections endpoint uses memory-based
  learning mode instead of model.is_trained.

Effect: System correctly enters learning mode (relaxed filters:
C+ grade, 2% min edge, hold-to-settlement, fixed 1-2 contract
sizing) even when a checkpoint model is loaded."

echo "✅ Committed"

echo ""
echo "🚀 Pushing to Railway..."
git push origin main

echo ""
echo "✅ Phase 25b pushed. Wait ~3 min for Railway to rebuild."
