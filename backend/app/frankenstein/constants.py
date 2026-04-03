"""
Frankenstein — Shared Constants. 🧟⚙️

Module-level constants shared across all Frankenstein modules:
brain.py, scanner.py, order_manager.py, positions.py, resolver.py.

Centralised here to avoid circular imports and make tuning easy.
"""

from __future__ import annotations


# ── Fee constants ────────────────────────────────────────────────────
# Kalshi taker fee: 7¢/contract, maker fee: 0¢.
# A round-trip (buy + sell) as taker costs 14¢/contract in fees.
# MAKER ORDERS PAY NO FEES — this is the profitability unlock.
TAKER_FEE_CENTS = 7        # per contract, per side
ROUND_TRIP_FEE_CENTS = 14  # buy fee + sell fee (taker path)
MAKER_FEE_CENTS = 0        # maker orders are FREE on Kalshi

# ── MAKER MODE ───────────────────────────────────────────────────────
# When True, Frankenstein places limit orders at the bid (maker) instead
# of crossing the spread (taker).  With 0¢ maker fees:
#   - Breakeven at 50¢: 50.0% WR (vs 61.3% as taker)
#   - Breakeven at 70¢: 70.0% WR (vs 82.8% as taker)
# Backtested result: +$47.47 on 1,180 trades at 67.5% WR (maker)
#                    vs -$115.72 on same trades as taker.
# Trade-off: fill rate is lower (~50-70%) because we don't cross spread.
# Strategy: hold to settlement — no early exit (avoids sell-side fees).
USE_MAKER_ORDERS = True

# Phase 6: Hard daily trade cap — prevents churning
# Raised for 24/7 maker mode: 0¢ fees means more trades = more profit.
# 150 trades/day = ~6/hour sustained throughput for all Kalshi categories.
MAX_DAILY_TRADES = 150

# Phase 7: Price floor — minimum contract cost to avoid fee traps
# With maker mode the fee-trap concern is gone, but extreme-probability
# contracts still have poor risk/reward, so keep a floor.
MIN_PRICE_FLOOR_CENTS = 20             # 20¢ minimum — maker mode has no fees
MIN_PRICE_FLOOR_LEARNING_CENTS = 15    # 15¢ minimum (learning mode)

# Phase 15: Circuit breaker — pause trading if accuracy drops below threshold
# Phase 22: Lowered from 30→15 trades so breaker trips faster on bad streaks.
# Cooldown 4h→2h: resume sooner after retrain to collect fresh learning data.
CIRCUIT_BREAKER_MIN_TRADES = 15
CIRCUIT_BREAKER_MIN_ACCURACY = 0.35    # pause if accuracy < 35%
CIRCUIT_BREAKER_COOLDOWN_HOURS = 2     # stay paused for 2 hours (was 4)

# ── Dynamic edge caps by market category ────────────────────────────
# Maximum edge the model is allowed to claim.  Edges above these caps
# are almost certainly model errors — markets are too efficient.
# MAKER MODE: caps unchanged (these limit MODEL claims, not fee math).
CATEGORY_EDGE_CAPS: dict[str, float] = {
    "sports":        0.08,   # Very efficient — Vegas lines
    "finance":       0.08,   # Very efficient — tracked indices
    "economics":     0.10,   # Somewhat efficient — consensus estimates
    "crypto":        0.12,   # Volatile but tracked
    "politics":      0.10,   # Polling-based, moderate efficiency
    "weather":       0.10,   # NWS forecasts are decent
    "entertainment": 0.12,   # Less efficient, fewer analysts
    "science":       0.12,   # Less efficient
    "culture":       0.12,   # Pop culture, social trends
    "social_media":  0.14,   # Twitter/X followers, influencer bets — least efficient
    "current_events":0.10,   # News-driven, moderate efficiency
    "tech":          0.10,   # Tech companies, product launches
    "legal":         0.10,   # Court cases, rulings
    "general":       0.10,   # Default
}

# ── Diversification limits ──────────────────────────────────────────
MAX_PER_EVENT = 2       # max 2 trades on same event per scan (tightened from 3 — correlated bets are risky)
MAX_PER_CATEGORY = 6    # max 6 trades in same category per scan (tightened from 8)

# ── Order lifecycle ─────────────────────────────────────────────────
ORDER_STALE_SECONDS = 240.0  # cancel unfilled orders after 4 min (was 5 — free capital faster)

# ── Phase 3: Smart Requoting ────────────────────────────────────────
# If the model's predicted edge drops below this AFTER a book change,
# cancel the resting order entirely (edge evaporated).
REQUOTE_EDGE_CANCEL_THRESHOLD = 0.015  # 1.5% edge = not worth it

# Spread-adaptive requote aggressiveness: when the spread is wider,
# we can afford to be more aggressive (bid+2¢ or bid+3¢) to improve
# queue position while still staying maker.
REQUOTE_AGGRESSION_BY_SPREAD: dict[int, int] = {
    # spread_cents → extra improvement beyond bid (in cents)
    1: 0,   # 1¢ spread: stay at bid (no room)
    2: 1,   # 2¢ spread: bid+1¢
    3: 1,   # 3¢ spread: bid+1¢
    5: 2,   # 5¢ spread: bid+2¢ (still 2¢ inside ask)
    10: 3,  # 10¢ spread: bid+3¢ (still 6¢ inside ask)
}

# Fill probability decay: orders aging without fill get cancelled earlier.
# After this many seconds, an unfilled order's stale timeout is halved.
FILL_PROB_DECAY_SECONDS = 120.0  # 2 min: start accelerating stale cleanup (before 4 min hard timeout)
FILL_PROB_MIN_STALE_SECONDS = 90.0   # floor: never stale-cancel before 90s — free capital faster

# ── Phase 4: Capital Recycling ──────────────────────────────────────
# Minimum available balance (after reservations) before we stop opening
# new positions. Prevents over-commitment.
CAPITAL_RECYCLE_MIN_BALANCE_CENTS = 300  # Phase 19: $3.00 minimum — deploy capital faster

# Maximum fraction of total balance that can be reserved in pending orders
MAX_RESERVED_CAPITAL_PCT = 0.70  # never reserve more than 70% of balance

# How often to reconcile fills with the exchange (catch missed WS fills)
FILL_RECONCILE_INTERVAL_S = 120.0  # every 2 min

# After CAPITAL_FREED, wait this long before triggering a re-scan
# (debounce: avoids scanning on every partial fill)
CAPITAL_FREED_RESCAN_DELAY_S = 2.0

# ── Phase 6: Multi-Level Quoting ────────────────────────────────
# Instead of placing one order at bid+1¢, spread contracts across
# multiple price levels to capture fills at different depths.
# Only activates when spread is wide enough to hold multiple levels.
MULTI_LEVEL_ENABLED = True

# Minimum spread (in cents) required to activate multi-level quoting.
# Below this, we fall back to single-order placement.
MULTI_LEVEL_MIN_SPREAD_CENTS = 4

# Maximum number of price levels to ladder across.
MULTI_LEVEL_MAX_LEVELS = 3

# Minimum contract count needed to split across levels.
# Single-contract orders can't be split.
MULTI_LEVEL_MIN_COUNT = 2

# Weight allocation per level (summed then normalized).
#   Level 0 = most aggressive (bid + N¢)  → best fill chance, least edge
#   Level 1 = standard (bid + 1¢)         → balanced
#   Level 2 = passive (bid)               → most edge, hardest fill
# For a 2-level scenario only levels 0 and 1 are used.
MULTI_LEVEL_WEIGHTS = [0.50, 0.30, 0.20]

# Price step between levels (cents).  Each level is this many cents
# deeper (cheaper) than the previous one.
MULTI_LEVEL_STEP_CENTS = 1


def round_trip_fee_pct(price_cents: int) -> float:
    """Round-trip fee as a percentage of contract cost.

    MAKER MODE (USE_MAKER_ORDERS=True): 0% — no fees!
    TAKER MODE:
      At 22¢: 14/22 = 63.6% (!!)
      At 50¢: 14/50 = 28.0%
      At 75¢: 14/75 = 18.7%

    Cheap contracts are fee DEATH TRAPS for takers — but free for makers.
    """
    if price_cents <= 0:
        return 1.0
    if USE_MAKER_ORDERS:
        return 0.0
    return ROUND_TRIP_FEE_CENTS / price_cents
