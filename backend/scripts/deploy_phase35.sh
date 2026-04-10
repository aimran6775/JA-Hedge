#!/bin/bash
# Phase 35: Deploy multi-model ensemble + LLM + Bayesian edge
set -e

cd "$(dirname "$0")/../.."

echo "=== Phase 35: Multi-Model Ensemble + LLM Deploy ==="
echo ""

# Import check
echo "1. Verifying imports..."
cd backend
source .venv/bin/activate
python -c "from app.main import app; print('   ✅ Import OK')"
cd ..

# Git
echo "2. Committing..."
git add -A
git commit -m "Phase 35: Multi-model ensemble (XGBoost+LightGBM+LLM+Bayesian edge) + price-crossing fills

- NEW: app/ai/llm_analyzer.py — GPT-4o-mini market analyzer with structured output,
  per-ticker cache (15min TTL), rate limiting, cost tracking, anchoring detection
- ENHANCED: app/ai/ensemble.py — v2.0.0 with 4-model blend:
  XGBoost (40%) + LightGBM (20%) + LLM (25% scaled by confidence) + Market baseline (15%)
  Bayesian edge: posterior shrunk toward market price by model agreement
  High-conviction detection when all non-baseline models agree on direction
- ENHANCED: app/frankenstein/scanner.py — LLM enrichment step after predict_batch:
  analyzes top 15 candidates by edge, blends 70/30 ML/LLM for high-confidence calls
- ENHANCED: app/frankenstein/learner.py — trains LightGBM alongside XGBoost on retrain
- ENHANCED: app/engine/paper_trader.py — price-crossing fill detection replaces
  random coin flips: checks if market price has moved through our resting order
- UPDATED: config.py (openai_api_key, llm_enabled), pyproject.toml (+openai, +lightgbm)"

echo "3. Pushing..."
git push origin main

echo ""
echo "=== Phase 35 deployed! ==="
echo "Set OPENAI_API_KEY on Railway to enable LLM analysis."
