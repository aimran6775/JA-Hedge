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

# ── MINIMUM HOLD TIME ────────────────────────────────────────────────
# Phase 25: Prevent churn loop — positions must be held this long before
# any exit evaluation.  The old behavior was: enter → XGBoost retrains on
# cold-start data → model contradicts entry → exit in 5-35 seconds → repeat.
# Maker mode: hold 30 minutes minimum (entire strategy is hold-to-settlement).
# Learning mode: hold to settlement (no exits except catastrophic stop-loss).
MIN_HOLD_MINUTES_MAKER = 30   # 30 min minimum hold before ANY exit evaluation
MIN_HOLD_MINUTES_TAKER = 5    # 5 min for taker mode (active management)
LEARNING_MODE_CATASTROPHIC_STOP = -0.50  # only exit in learning mode at -50%

# ── TRAINING PIPELINE THRESHOLDS ─────────────────────────────────────
# Phase 25: Prevent training on garbage data.  Old: 20 samples min, retrain
# every 10.  Result: XGBoost trained on 10-20 cold-start trades with identical
# features (all zeros) → random predictions → contradicts heuristic → churn.
MIN_TRAINING_SAMPLES = 50      # Minimum resolved trades before first training (was 20)
RETRAIN_INTERVAL = 25          # Retrain every 25 new resolved trades (was 10)
MIN_CLASS_BALANCE = 0.15       # Minimum 15% minority class — skip if all same label

# ── RESOLUTION QUALITY ───────────────────────────────────────────────
# Phase 25: Fix label noise.  Method 3 at 0.95/0.05 is only 95% certain;
# Method 4 at 6h/0.75 is only 75% certain → 25% wrong labels pollute training.
EXTREME_PRICE_THRESHOLD_YES = 0.98  # resolve YES when price ≥ 0.98 (was 0.95)
EXTREME_PRICE_THRESHOLD_NO = 0.02   # resolve NO when price ≤ 0.02 (was 0.05)
TIMEOUT_HOURS = 24                   # timeout after 24h (was 6h)
TIMEOUT_PRICE_YES = 0.90             # timeout resolve YES when ≥ 0.90 (was 0.75)
TIMEOUT_PRICE_NO = 0.10              # timeout resolve NO when ≤ 0.10 (was 0.25)

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

# Phase 6+25+27+34: Hard daily trade cap.
# Phase 4 (RECOVERY): cut from 350->100. Volume was masking the fact that
# we were losing 100% of resolved trades. Quality > quantity until WR > 50%.
MAX_DAILY_TRADES = 100

# Phase 7+27: Price floor — minimum contract cost to avoid fee traps
# Phase 27: Lowered to 10¢ — maker has 0 fees, cheap contracts offer
# asymmetric payoff (risk 10¢ to win 90¢ = 9:1 reward/risk).
# Phase 4 (RECOVERY): Raised floor from 10c->18c. Bot was buying 1-9c
# extreme long-shot YES contracts and 100% settled NO. Stay above the
# long-shot bias zone where YES contracts are systematically overpriced.
MIN_PRICE_FLOOR_CENTS = 18             # 18c minimum - avoid YES long-shot trap
MIN_PRICE_FLOOR_LEARNING_CENTS = 15    # 15c minimum (learning mode)

# Phase 4: also cap upside - buying 90c+ contracts is just betting the
# favorite pays out. Edge there is usually noise.
MAX_PRICE_CEILING_CENTS = 82           # Don't buy above 82c

# Phase 15: Circuit breaker — pause trading if accuracy drops below threshold
# Phase 22: Lowered from 30→15 trades so breaker trips faster on bad streaks.
# Cooldown 4h→2h: resume sooner after retrain to collect fresh learning data.
CIRCUIT_BREAKER_MIN_TRADES = 15
CIRCUIT_BREAKER_MIN_ACCURACY = 0.40    # Phase 5: pause if accuracy < 40% (was 35%)
CIRCUIT_BREAKER_COOLDOWN_HOURS = 4     # Phase 5: 4h cooldown (was 2h) - let learner catch up

# Phase 5: Multi-level circuit breakers (NEW)
# Hard kill switch - stop trading entirely until manual reset.
KILL_SWITCH_MAX_DRAWDOWN_PCT = 0.08    # 8% account drawdown -> kill
KILL_SWITCH_MAX_CONSECUTIVE_LOSSES = 15 # 15 in a row -> kill
KILL_SWITCH_MAX_DAILY_LOSS_CENTS = 10000  # $100 lost in one day -> kill
KILL_SWITCH_COOLDOWN_HOURS = 24        # 24h forced cooldown after kill

# Soft pause - auto-resume after cooldown.
SOFT_PAUSE_CONSECUTIVE_LOSSES = 8      # 8 in a row -> 1h pause
SOFT_PAUSE_COOLDOWN_HOURS = 1

# Side-imbalance kill: if we trip side-balance gate >100 times/hour we have
# a systemic bias bug - pause and alert.
SIDE_IMBALANCE_RATE_LIMIT = 100        # rejections per hour

# ── Dynamic edge caps by market category ────────────────────────────
# Maximum edge the model is allowed to claim.  Edges above these caps
# are almost certainly model errors — markets are too efficient.
# MAKER MODE: caps unchanged (these limit MODEL claims, not fee math).
# Phase 25: Raised edge caps — intelligence data (Polymarket, news, crypto,
# social, weather) provides genuine signals that justify higher model claims.
# During learning mode, these caps are further raised by 50% to let more
# trades through for data collection.
CATEGORY_EDGE_CAPS: dict[str, float] = {
    "sports":        0.15,   # Phase 27: +3% — aggressive
    "finance":       0.14,   # Phase 27: +4%
    "economics":     0.15,   # Phase 27: +3%
    "crypto":        0.20,   # Phase 27: +5% — volatile = more edge
    "politics":      0.15,   # Phase 27: +3%
    "weather":       0.15,   # Phase 27: +3%
    "entertainment": 0.18,   # Phase 27: +4%
    "science":       0.18,   # Phase 27: +4%
    "culture":       0.18,   # Phase 27: +4%
    "social_media":  0.20,   # Phase 27: +4% — least efficient market
    "current_events":0.15,   # Phase 27: +3%
    "tech":          0.15,   # Phase 27: +3%
    "legal":         0.15,   # Phase 27: +3%
    "general":       0.15,   # Phase 27: +3%
}

# Phase 25: Learning mode edge cap multiplier — allow bigger edges during
# data collection phase so more trades flow through for model training.
LEARNING_MODE_EDGE_CAP_MULT = 2.0  # 100% higher caps during learning

# ── PHASE 1 (May 2026): SIDE BALANCE DEFENSE ─────────────────────────
# Critical fix: prior runs showed 1035/1035 trades all predicted YES.
# Symptom of broken heuristic + signal collusion. We now monitor recent
# side distribution and BLOCK further same-side trades when imbalance
# exceeds the threshold. Forces the bot to sample both sides for
# learning, prevents catastrophic single-side bias.
SIDE_BALANCE_WINDOW = 50            # Look at last N trades
SIDE_BALANCE_MAX_RATIO = 0.75       # Block if >75% of recent trades are one side
SIDE_BALANCE_MIN_TRADES = 10        # Only enforce after this many trades

# ── PHASE 2 (May 2026): FORCE TRAINING DESPITE IMBALANCE ─────────────
# When all resolved labels are one side (e.g. 100% NO), the old
# MIN_CLASS_BALANCE check blocks training forever. We now permit
# training with synthetic minority oversampling at lower thresholds.
MIN_CLASS_BALANCE_HARD = 0.05       # Below this, even SMOTE can't help
USE_SYNTHETIC_OVERSAMPLING = True   # Enable SMOTE-like oversampling

# ── Diversification limits ──────────────────────────────────────────
# Phase 4 (RECOVERY): Severe cap until WR proven.
MAX_PER_EVENT = 3       # Phase 4: only 3 contracts per event (was 15)
MAX_PER_CATEGORY = 15   # Phase 4: 15 per category (was 80) - diversify

# ── Order lifecycle ─────────────────────────────────────────────────
ORDER_STALE_SECONDS = 150.0  # Phase 27: cancel unfilled after 2.5 min — faster capital recycling

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
FILL_PROB_DECAY_SECONDS = 90.0   # Phase 27: 1.5 min — start accelerating cleanup
FILL_PROB_MIN_STALE_SECONDS = 60.0   # Phase 27: 1 min floor — recycle capital faster

# ── Phase 4: Capital Recycling ──────────────────────────────────────
# Minimum available balance (after reservations) before we stop opening
# new positions. Prevents over-commitment.
CAPITAL_RECYCLE_MIN_BALANCE_CENTS = 200000  # Phase 4: keep $2000 dry powder

# Maximum fraction of total balance that can be reserved in pending orders
MAX_RESERVED_CAPITAL_PCT = 0.50  # Phase 4: max 50% deployed (was 85%)

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
# Phase 28: Raised from 2→8 — don't split small orders across levels.
# With small counts (2-7), splitting wastes orders and reduces fill rate.
# Better to concentrate at one aggressive price for maximum fill probability.
MULTI_LEVEL_MIN_COUNT = 8

# Weight allocation per level (summed then normalized).
#   Level 0 = most aggressive (bid + N¢)  → best fill chance, least edge
#   Level 1 = standard (bid + 1¢)         → balanced
#   Level 2 = passive (bid)               → most edge, hardest fill
# For a 2-level scenario only levels 0 and 1 are used.
MULTI_LEVEL_WEIGHTS = [0.50, 0.30, 0.20]

# Price step between levels (cents).  Each level is this many cents
# deeper (cheaper) than the previous one.
MULTI_LEVEL_STEP_CENTS = 1

# ── Phase 28: Hybrid Taker Execution ────────────────────────────
# For highest-confidence trades (A/A+), use taker orders for 100% fill
# rate. The 7¢/contract fee is worth it on trades with strong edge.
HYBRID_TAKER_ENABLED = True
HYBRID_TAKER_MIN_GRADE = "A"       # Minimum grade for taker execution
HYBRID_TAKER_MIN_EDGE = 0.08       # Minimum edge (8%) to justify taker fees

# ── Phase 28: Poll-Based Requoting ──────────────────────────────
# Since WebSocket is unreliable, requote pending orders each scan cycle
# by polling current market prices and amending stale orders.
POLL_REQUOTE_ENABLED = True
POLL_REQUOTE_MAX_PER_SCAN = 10     # Max orders to requote per scan cycle
POLL_REQUOTE_MIN_AGE_SECONDS = 20  # Don't requote orders younger than 20s

# ── Phase 35c: Gap Fixes ────────────────────────────────────────
# Feature completeness thresholds (moved from hardcoded values)
FEATURE_COMPLETENESS_COLD_START = 0.98   # 98% features during cold start
FEATURE_COMPLETENESS_LEARNING = 0.90     # 90% during learning mode
FEATURE_COMPLETENESS_NORMAL = 0.75       # 75% in normal operation

# Scanner bounded dict limits — prevent memory leaks
MAX_PRICE_HISTORY_ENTRIES = 10000  # Max tickers to track price history
MAX_CATEGORY_CACHE_ENTRIES = 10000 # Max tickers for category cache

# Memory configuration
MAX_IMPORTANT_TRADES = 500         # Cap for pinned important trades
IMPORTANT_PNL_THRESHOLD_CENTS = 500  # $5 threshold for importance

# Order manager limits
MAX_PENDING_ORDERS = 500           # Absolute cap on pending_orders dict
ORDER_CANCELLATION_LOCK_SECONDS = 5  # Don't requote orders being cancelled

# Fill predictor configuration
FILL_PREDICTOR_RETRAIN_INTERVAL = 50  # Retrain after N observations

# Harvester configuration  
MAX_HARVEST_SNAPSHOTS = 20000      # Max pending snapshots
MAX_HARVEST_BUFFER = 50000         # Max harvested training records
HARVEST_SNAPSHOT_TTL_HOURS = 72    # Snapshot expiry

# LLM blend ratio (when LLM is enabled)
LLM_BLEND_RATIO = 0.30             # 30% LLM, 70% ML when LLM active

# Resolver batch timeout
RESOLVER_BATCH_TIMEOUT_SECONDS = 30.0  # Timeout for market fetch batches

# Strategy drift protection
MAX_STRATEGY_DRIFT_CYCLES = 1000   # Reset to defaults after N adaptations


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
