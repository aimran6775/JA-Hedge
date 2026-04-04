#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/../.."

cd backend && source .venv/bin/activate 2>/dev/null || true
python -c "from app.main import app; print('✅ Import OK')"
cd ..

git add -A
git commit -m "Phase 25b-3: Fix maker learning mode — zero spread cost, 0.005 edge floor

Maker + hold-to-settlement = no spread crossing cost. Previously
cost_to_beat included half_spread even in maker learning mode,
which set effective_min_edge to 0.025+ (blocking heuristic's
0.005-0.02 edges). Now cost_to_beat = 0 for maker learning mode."

git push origin main
echo "✅ Deployed. Wait ~3 min."
