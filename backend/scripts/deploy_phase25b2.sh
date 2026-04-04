#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/../.."

echo "=== Phase 25b-2: Relax Learning Mode Filters ==="

# Verify
cd backend
source .venv/bin/activate 2>/dev/null || true
python -c "from app.main import app; print('✅ Import OK')"
cd ..

# Commit & push
git add -A
git commit -m "Phase 25b-2: Relax learning mode — bypass grade gate, lower edge floor

Learning mode (< 50 usable training samples) now truly permissive:
- Grade minimum: C+ → F (bypass grade gate entirely)
- Absolute edge floor: 0.02 → 0.003 (heuristic produces 0.005-0.02)
- Effective min edge: 0.03 → 0.005 for makers (0¢ fees)
- Rejections endpoint: min_grade B → F for consistency

Rationale: Learning mode exists to collect training data. Maker mode
means 0¢ fees, hold-to-settlement, fixed 1-2 contract sizing. The
cost of trading with weak signals is tiny; the cost of NOT collecting
training data is the system never learns."

echo "✅ Committed"
git push origin main
echo "✅ Pushed. Wait ~3 min for Railway rebuild."
