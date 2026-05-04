#!/usr/bin/env bash
# Phase 4+ verification: import chain + key constants present.
set -e
cd "$(dirname "$0")/.."
source .venv/bin/activate 2>/dev/null || true
python - <<'PY'
from app.main import app  # noqa
from app.frankenstein import constants as C
from app.frankenstein.strategy import StrategyParams
print("OK app imports")
assert C.MAX_DAILY_TRADES == 100, C.MAX_DAILY_TRADES
assert C.MIN_PRICE_FLOOR_CENTS == 18, C.MIN_PRICE_FLOOR_CENTS
assert hasattr(C, "MAX_PRICE_CEILING_CENTS")
assert hasattr(C, "KILL_SWITCH_MAX_DRAWDOWN_PCT")
assert hasattr(C, "SIDE_BALANCE_WINDOW")
assert hasattr(C, "USE_SYNTHETIC_OVERSAMPLING")
p = StrategyParams()
assert p.min_confidence == 0.58, p.min_confidence
assert p.min_edge == 0.045, p.min_edge
assert p.max_position_size == 10, p.max_position_size
print("OK constants:")
print(f"  MAX_DAILY_TRADES={C.MAX_DAILY_TRADES}")
print(f"  PRICE_FLOOR/CEIL={C.MIN_PRICE_FLOOR_CENTS}-{C.MAX_PRICE_CEILING_CENTS}c")
print(f"  KILL_SWITCH dd={C.KILL_SWITCH_MAX_DRAWDOWN_PCT*100}% losses={C.KILL_SWITCH_MAX_CONSECUTIVE_LOSSES}")
print(f"  StrategyParams min_conf={p.min_confidence} min_edge={p.min_edge} max_pos={p.max_position_size}")
PY
