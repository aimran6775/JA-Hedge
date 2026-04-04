#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/../.."

cd backend && source .venv/bin/activate 2>/dev/null || true
python -c "from app.main import app; print('✅ Import OK')"
cd ..

git add -A
git commit -m "Phase 25b-4: Fix Net EV check — no spread cost in maker hold-to-settlement

The Net EV check subtracted half_spread from edge, making it negative
for all heuristic predictions (edge 0.005-0.02, spread 0.04-0.08).
But in maker mode with hold-to-settlement:
- Entry: maker order at our price (no spread crossing)
- Exit: settlement (binary 0¢ or \$1, no spread crossing)
Spread cost is ZERO. Now uses spread_cost=0 in maker+learning mode."

git push origin main
echo "✅ Deployed."
