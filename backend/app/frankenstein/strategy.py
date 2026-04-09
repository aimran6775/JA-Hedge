"""
Frankenstein — Adaptive Strategy Engine.

Self-tuning trading parameters that adapt based on:
- Recent performance (win rate, Sharpe)
- Market regime (trending, mean-reverting, volatile, quiet)
- Model confidence calibration
- Risk conditions (drawdown, consecutive losses)

The strategy becomes more aggressive when winning and
more conservative when losing — like a sentient trader.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from app.frankenstein.memory import TradeMemory
from app.frankenstein.performance import PerformanceTracker, PerformanceSnapshot
from app.logging_config import get_logger

log = get_logger("frankenstein.strategy")


@dataclass
class StrategyParams:
    """Tunable strategy parameters — Frankenstein adjusts these live."""

    # Signal filters — MAKER-AWARE: edge only needs to beat spread (no fees)
    min_confidence: float = 0.35     # Phase 27: lowered from 0.40 — take more trades
    min_edge: float = 0.03           # Phase 27: lowered from 0.04 — 3% min edge for maker mode

    # Position sizing — AGGRESSIVE: deploy capital to make money
    kelly_fraction: float = 0.30     # Phase 27: doubled from 0.15 — bet bigger on edges
    max_position_size: int = 50      # Phase 28c: 50 contracts max per trade (aggressive)
    max_simultaneous_positions: int = 150   # Phase 27: 150 concurrent positions

    # Timing
    scan_interval: float = 15.0  # Phase 27: scan every 15s — catch more opportunities

    # Risk overrides
    max_daily_loss: float = 500.0    # Phase 27: $500 daily loss limit (was $150)
    stop_loss_pct: float = 0.15      # Not used in maker mode (hold to settlement)
    take_profit_pct: float = 0.20    # Not used in maker mode (hold to settlement)

    # Model thresholds
    max_spread_cents: int = 55   # Phase 27: wider spreads ok — maker creates liquidity
    min_volume: float = 0.0     # Maker creates liquidity — no volume requirement
    min_hours_to_expiry: float = 0.5  # Phase 27: 30 min minimum (was 1h) — trade closer to expiry

    # Aggression level (0.0 = ultra conservative, 1.0 = maximum aggression)
    aggression: float = 0.55         # Phase 27: high aggression (was 0.35)

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class AdaptationEvent:
    """Record of a parameter adaptation."""
    timestamp: float = field(default_factory=time.time)
    parameter: str = ""
    old_value: float = 0.0
    new_value: float = 0.0
    reason: str = ""
    regime: str = ""


class AdaptiveStrategy:
    """
    Frankenstein's self-tuning strategy engine.

    Adjusts trading parameters based on:
    - Recent performance metrics
    - Market regime classification
    - Risk conditions
    - Model quality indicators
    """

    def __init__(
        self,
        memory: TradeMemory,
        performance: PerformanceTracker,
        *,
        base_params: StrategyParams | None = None,
        adaptation_interval: float = 900.0,  # 15 minutes
    ):
        self.memory = memory
        self.performance = performance
        self.params = base_params or StrategyParams()
        self.adaptation_interval = adaptation_interval

        # Phase 32: TIGHT clamp bounds. The old bounds (MAX_CONF=0.55,
        # MAX_EDGE=0.12) let adaptation drift so far from defaults that
        # the system stopped trading entirely (min_conf 0.35→0.42, min_edge
        # 0.03→0.049 after 72 adaptations).  New bounds keep params within
        # a narrow band around the defaults so adaptation can't kill trade flow.
        self._MIN_CONFIDENCE = 0.32    # Floor: always take high-confidence trades
        self._MAX_CONFIDENCE = 0.43    # Cap: never require >43% confidence
        self._MIN_EDGE = 0.025         # Floor: 2.5% min edge
        self._MAX_EDGE = 0.06          # Cap: never require >6% edge (was 12%!)
        self._MIN_KELLY = 0.15         # Floor: bet meaningful amounts
        self._MAX_KELLY = 0.35         # Cap: don't over-concentrate
        self._MIN_AGGRESSION = 0.30    # Floor: stay aggressive
        self._MAX_AGGRESSION = 0.75    # Cap: not reckless

        # History
        self._adaptations: list[AdaptationEvent] = []
        self._last_adaptation: float = 0.0
        self._total_adaptations: int = 0

        # Enforce bounds on initial params (protects against stale persisted values)
        self._clamp_all_params()

        log.info("adaptive_strategy_initialized", params=self.params.to_dict())

    # ── Main Adaptation Loop ──────────────────────────────────────────

    def _clamp_all_params(self) -> None:
        """Enforce hard bounds on all tunable parameters.

        Called at init and after every adaptation cycle to guarantee
        no parameter ever escapes its declared min/max.
        """
        p = self.params
        p.min_confidence = max(self._MIN_CONFIDENCE, min(p.min_confidence, self._MAX_CONFIDENCE))
        p.min_edge = max(self._MIN_EDGE, min(p.min_edge, self._MAX_EDGE))
        p.kelly_fraction = max(self._MIN_KELLY, min(p.kelly_fraction, self._MAX_KELLY))
        p.aggression = max(self._MIN_AGGRESSION, min(p.aggression, self._MAX_AGGRESSION))

    def adapt(self, snapshot: PerformanceSnapshot | None = None) -> list[AdaptationEvent]:
        """
        Adapt strategy parameters based on current performance.

        Returns list of parameter changes made.
        """
        now = time.time()
        if now - self._last_adaptation < self.adaptation_interval:
            return []

        if snapshot is None:
            snapshot = self.performance.compute_snapshot()

        events: list[AdaptationEvent] = []

        # ── LEARNING MODE GUARD ──────────────────────────────────────
        # Phase 32: Raised from 500 → 1000. The system has been running
        # with mostly inherited trade data from prior buggy generations.
        # Adaptation on that data causes death spirals (72 adaptations
        # drove min_conf 0.35→0.42, killing trade flow). Wait for 1000
        # fresh trades before allowing any param changes.
        if snapshot.real_trades < 1000:
            log.info(
                "strategy_learning_mode_skip_adaptation",
                real_trades=snapshot.real_trades,
                remaining=500 - snapshot.real_trades,
            )
            # Only compute aggression (cosmetic) — no param changes
            self._compute_aggression(snapshot)
            self._last_adaptation = now
            self._total_adaptations += 1
            return events
        # ─────────────────────────────────────────────────────────────

        # 1. Adapt based on regime
        events.extend(self._adapt_to_regime(snapshot))

        # 2. Adapt based on win rate
        events.extend(self._adapt_to_win_rate(snapshot))

        # 3. Adapt based on drawdown
        events.extend(self._adapt_to_drawdown(snapshot))

        # 4. Adapt based on model quality
        events.extend(self._adapt_to_model_quality(snapshot))

        # 5. Adapt based on consecutive losses
        events.extend(self._adapt_to_streaks(snapshot))

        # 6. Compute overall aggression
        self._compute_aggression(snapshot)

        self._last_adaptation = now
        self._total_adaptations += 1

        # Hard-clamp after all adaptations — belt + suspenders
        self._clamp_all_params()

        if events:
            self._adaptations.extend(events)
            log.info(
                "🧟 FRANKENSTEIN ADAPTED",
                changes=len(events),
                aggression=f"{self.params.aggression:.2f}",
                regime=snapshot.regime,
                params={e.parameter: e.new_value for e in events},
            )

        return events

    # ── Regime Adaptation ─────────────────────────────────────────────

    def _adapt_to_regime(self, snap: PerformanceSnapshot) -> list[AdaptationEvent]:
        """Adjust parameters based on detected market regime.

        MAKER MODE PHILOSOPHY: 0 fees means volatility is OPPORTUNITY, not risk.
        Wider spreads → better maker fills. We should NEVER choke trade flow
        because of regime detection. Keep targets loose — the model's edge
        threshold is the real guard, not arbitrary regime tightening.
        """
        events = []
        regime = snap.regime

        if regime == "volatile":
            # Volatile = wider spreads = BETTER for makers. Slightly larger edge
            # requirement (spreads may be noisy), but keep trading.
            events.extend(self._adjust("min_confidence", 0.38, "volatile_regime"))
            events.extend(self._adjust("min_edge", 0.04, "volatile_regime"))
            events.extend(self._adjust("kelly_fraction", 0.22, "volatile_regime"))
            events.extend(self._adjust("max_position_size", 30, "volatile_regime"))

        elif regime == "quiet":
            # Quiet = tight spreads = harder for makers. Accept smaller edge,
            # but make more trades to accumulate small wins.
            events.extend(self._adjust("min_confidence", 0.35, "quiet_regime"))
            events.extend(self._adjust("min_edge", 0.03, "quiet_regime"))
            events.extend(self._adjust("kelly_fraction", 0.28, "quiet_regime"))
            events.extend(self._adjust("max_position_size", 40, "quiet_regime"))

        elif regime == "trending":
            # Trending = directional moves. Ride with conviction.
            events.extend(self._adjust("min_confidence", 0.37, "trending_regime"))
            events.extend(self._adjust("min_edge", 0.035, "trending_regime"))
            events.extend(self._adjust("kelly_fraction", 0.25, "trending_regime"))

        elif regime == "mean_reverting":
            # Mean-revert = great for makers. Post aggressive quotes.
            events.extend(self._adjust("min_confidence", 0.36, "mean_reverting_regime"))
            events.extend(self._adjust("min_edge", 0.03, "mean_reverting_regime"))
            events.extend(self._adjust("kelly_fraction", 0.25, "mean_reverting_regime"))

        return [e for e in events if e is not None]

    # ── Win Rate Adaptation ───────────────────────────────────────────

    def _adapt_to_win_rate(self, snap: PerformanceSnapshot) -> list[AdaptationEvent]:
        """Get more aggressive when winning, conservative when losing."""
        events = []

        if snap.real_trades < 30:
            return events  # Not enough data — learning mode

        if snap.win_rate > 0.55:
            # Winning: loosen entry, grow size
            events.extend(self._adjust("min_confidence", max(self.params.min_confidence - 0.02, self._MIN_CONFIDENCE), "high_win_rate"))
            events.extend(self._adjust("kelly_fraction", min(self.params.kelly_fraction + 0.02, self._MAX_KELLY), "high_win_rate"))

        elif snap.win_rate < 0.15:
            # Phase 32: Only tighten on truly catastrophic WR (<15%, was 25%)
            # Tiny steps to prevent compounding with other adaptations
            events.extend(self._adjust("min_confidence", min(self.params.min_confidence + 0.003, self._MAX_CONFIDENCE), "low_win_rate"))
            events.extend(self._adjust("kelly_fraction", max(self.params.kelly_fraction - 0.003, self._MIN_KELLY), "low_win_rate"))

        return [e for e in events if e is not None]

    # ── Drawdown Adaptation ───────────────────────────────────────────

    def _adapt_to_drawdown(self, snap: PerformanceSnapshot) -> list[AdaptationEvent]:
        """Reduce exposure during drawdowns."""
        events = []

        if snap.current_drawdown < -15:  # Only react to meaningful drawdowns (>$15)
            severity = min(abs(snap.current_drawdown) / 100.0, 0.4)  # Gentler: max 40% reduction, scale over $100
            new_kelly = max(self.params.kelly_fraction * (1.0 - severity), self._MIN_KELLY)
            # NEVER reduce max_positions below 40 — otherwise open positions block all new trades
            new_positions = max(int(self.params.max_simultaneous_positions * (1.0 - severity)), 40)

            events.extend(self._adjust("kelly_fraction", new_kelly, f"drawdown_${abs(snap.current_drawdown):.0f}"))
            events.extend(self._adjust("max_simultaneous_positions", new_positions, f"drawdown_${abs(snap.current_drawdown):.0f}"))

        elif snap.current_drawdown > -5:
            # Restore defaults
            events.extend(self._adjust("kelly_fraction", min(self.params.kelly_fraction + 0.02, 0.30), "recovery"))
            events.extend(self._adjust("max_simultaneous_positions", min(self.params.max_simultaneous_positions + 5, 150), "recovery"))

        return [e for e in events if e is not None]

    # ── Model Quality Adaptation ──────────────────────────────────────

    def _adapt_to_model_quality(self, snap: PerformanceSnapshot) -> list[AdaptationEvent]:
        """Adjust based on model's prediction accuracy."""
        events = []

        if snap.real_trades < 100:
            return events  # Need substantial data before judging accuracy

        if snap.prediction_accuracy < 0.20:
            # Phase 32: Only trigger on truly terrible accuracy (<20%, was 30%).
            # Targets lowered to stay within tight clamp bounds.
            events.extend(self._adjust("min_confidence", 0.40, "poor_accuracy"))
            events.extend(self._adjust("min_edge", 0.04, "poor_accuracy"))
            events.extend(self._adjust("kelly_fraction", 0.20, "poor_accuracy"))

        elif snap.prediction_accuracy > 0.55:
            # Model is good — open up
            events.extend(self._adjust("min_confidence", 0.34, "good_accuracy"))
            events.extend(self._adjust("min_edge", 0.03, "good_accuracy"))

        # Confidence calibration: nudge edge slightly if overconfident
        # Phase 32: Raised threshold 0.20→0.30, reduced bump 0.005→0.002
        if snap.confidence_calibration > 0.30:
            events.extend(self._adjust("min_edge", min(self.params.min_edge + 0.002, self._MAX_EDGE), "poor_calibration"))

        return [e for e in events if e is not None]

    # ── Streak Adaptation ─────────────────────────────────────────────

    def _adapt_to_streaks(self, snap: PerformanceSnapshot) -> list[AdaptationEvent]:
        """React to consecutive wins/losses.
        
        NOTE: This only fires AFTER learning mode (100+ real trades)
        because the main adapt() method returns early during learning.
        Even post-learning, we use bounded adjustments — never nuke params.
        """
        events = []

        if snap.consecutive_losses >= 8:
            # Phase 32: Gentler loss-streak handling. Old thresholds (5 losses,
            # 0.01 per loss) were too aggressive — 13 losses drove kelly from
            # 0.30 → 0.15 in one cycle. New: start at 8, 0.005 per loss.
            reduction = 0.005 * (snap.consecutive_losses - 7)
            new_kelly = max(self.params.kelly_fraction - reduction, self._MIN_KELLY)
            events.extend(self._adjust("kelly_fraction", new_kelly, f"loss_streak_{snap.consecutive_losses}"))

            if snap.consecutive_losses >= 12:
                # Only tighten confidence after a very long streak
                new_conf = min(self.params.min_confidence + 0.01, self._MAX_CONFIDENCE)
                events.extend(self._adjust("min_confidence", new_conf, "loss_streak_tighten"))

        # Always restore scan_interval toward baseline (don't let it bloat)
        if self.params.scan_interval > 30.0:
            new_scan = max(self.params.scan_interval - 3.0, 30.0)
            events.extend(self._adjust("scan_interval", new_scan, "scan_restore"))

        return [e for e in events if e is not None]

    # ── Aggression Score ──────────────────────────────────────────────

    def _compute_aggression(self, snap: PerformanceSnapshot) -> None:
        """Compute overall aggression level (0=conservative, 1=aggressive)."""
        score = 0.5  # Neutral

        # Win rate factor
        if snap.real_trades >= 10:
            score += (snap.win_rate - 0.5) * 0.3  # ±0.15

        # Drawdown factor
        if snap.current_drawdown < -20:
            score -= min(abs(snap.current_drawdown) / 200.0, 0.3)

        # Model accuracy factor
        if snap.real_trades >= 20:
            score += (snap.prediction_accuracy - 0.5) * 0.2  # ±0.10

        # Profit factor
        if snap.profit_factor > 2.0:
            score += 0.1
        elif snap.profit_factor < 0.5 and snap.real_trades >= 10:
            score -= 0.15

        # Clamp
        self.params.aggression = max(self._MIN_AGGRESSION, min(self._MAX_AGGRESSION, score))

    # ── Helpers ───────────────────────────────────────────────────────

    def _adjust(self, param: str, new_value: Any, reason: str) -> list[AdaptationEvent]:
        """Adjust a parameter and record the change.

        Phase 16: EMA-smooth changes to prevent oscillation.
        Instead of jumping directly to new_value, blend current → target
        with an EMA factor (alpha=0.3).  This means it takes ~3 adaptation
        cycles to converge on a new target, preventing whiplash between
        regime detections.
        """
        old_value = getattr(self.params, param, None)
        if old_value is None:
            return []

        # EMA smoothing for numeric parameters
        EMA_ALPHA = 0.3
        if isinstance(new_value, float) and isinstance(old_value, float):
            smoothed = old_value + EMA_ALPHA * (new_value - old_value)
            # Only record if actually changed (with tolerance)
            if abs(smoothed - old_value) < 0.001:
                return []
            new_value = smoothed
        elif isinstance(new_value, int) and isinstance(old_value, int):
            # For integers, use EMA then round
            smoothed = old_value + EMA_ALPHA * (new_value - old_value)
            smoothed_int = round(smoothed)
            if smoothed_int == old_value:
                return []
            new_value = smoothed_int
        elif new_value == old_value:
            return []

        setattr(self.params, param, new_value)

        event = AdaptationEvent(
            parameter=param,
            old_value=float(old_value) if isinstance(old_value, (int, float)) else 0.0,
            new_value=float(new_value) if isinstance(new_value, (int, float)) else 0.0,
            reason=reason,
        )

        return [event]

    def get_params(self) -> StrategyParams:
        """Get current strategy parameters."""
        return self.params

    def reset_to_defaults(self) -> None:
        """Reset all parameters to conservative defaults."""
        self.params = StrategyParams()
        self._adaptations.append(AdaptationEvent(
            parameter="ALL",
            reason="manual_reset",
        ))
        log.info("strategy_params_reset_to_defaults")

    # ── Statistics ────────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        """Full adaptive strategy statistics."""
        return {
            "current_params": self.params.to_dict(),
            "aggression": f"{self.params.aggression:.2f}",
            "total_adaptations": self._total_adaptations,
            "recent_adaptations": [
                {
                    "time": a.timestamp,
                    "param": a.parameter,
                    "old": a.old_value,
                    "new": a.new_value,
                    "reason": a.reason,
                }
                for a in self._adaptations[-20:]
            ],
        }
