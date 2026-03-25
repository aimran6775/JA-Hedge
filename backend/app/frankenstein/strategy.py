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

    # Signal filters — CONSERVATIVE: quality over quantity
    min_confidence: float = 0.45     # Phase 11: Higher floor — only trade strong signals
    min_edge: float = 0.06           # Phase 11: 6% min edge — must beat spread

    # Position sizing — small and cautious
    kelly_fraction: float = 0.15     # Phase 11: Conservative Kelly (was 0.25)
    max_position_size: int = 5       # Phase 11: Small positions (was 12)
    max_simultaneous_positions: int = 30   # Phase 11: Fewer concurrent (was 75)

    # Timing
    scan_interval: float = 30.0  # scan every 30s — patient, not frantic

    # Risk overrides — TIGHT
    max_daily_loss: float = 150.0    # Phase 11: Tighter loss cap (was 300)
    stop_loss_pct: float = 0.15      # Phase 11: Match brain.py (was 0.30)
    take_profit_pct: float = 0.15    # Phase 11: Match brain.py (was 0.25)

    # Model thresholds
    max_spread_cents: int = 20   # Phase 11: Tight spreads ONLY (was 40)
    min_volume: float = 10.0     # Phase 11: Need real liquidity (was 3)
    min_hours_to_expiry: float = 1.0  # Phase 11: No sub-1h expiry trades

    # Aggression level (0.0 = ultra conservative, 1.0 = maximum aggression)
    aggression: float = 0.35         # Phase 11: Conservative (was 0.70)

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

        # Defaults (never go below/above these) — TIGHT bounds to prevent over-trading
        self._MIN_CONFIDENCE = 0.35    # Phase 12: Never drop below 35% (was 0.15)
        self._MAX_CONFIDENCE = 0.65    # Phase 12: Can tighten up to 65% (was 0.55)
        self._MIN_EDGE = 0.04          # Phase 12: Never trade below 4% edge (was 0.02)
        self._MAX_EDGE = 0.15          # Phase 12: Raise max (was 0.12)
        self._MIN_KELLY = 0.05         # Phase 12: Smaller minimum kelly (was 0.08)
        self._MAX_KELLY = 0.25         # Phase 12: Cap kelly at 25% (was 0.50)
        self._MIN_AGGRESSION = 0.10    # Phase 12: Can go very conservative
        self._MAX_AGGRESSION = 0.60    # Phase 12: Never go full aggressive (was 0.85)

        # History
        self._adaptations: list[AdaptationEvent] = []
        self._last_adaptation: float = 0.0
        self._total_adaptations: int = 0

        log.info("adaptive_strategy_initialized", params=self.params.to_dict())

    # ── Main Adaptation Loop ──────────────────────────────────────────

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
        # During the first 100 real trades, we have NO statistical basis
        # to adapt parameters.  Keep defaults and just trade.
        if snapshot.real_trades < 100:
            log.info(
                "strategy_learning_mode_skip_adaptation",
                real_trades=snapshot.real_trades,
                remaining=100 - snapshot.real_trades,
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
        """Adjust parameters based on detected market regime."""
        events = []
        regime = snap.regime

        if regime == "volatile":
            # High vol: VERY conservative — wide thresholds, tiny sizes,
            # tighter stops (volatile markets move fast against you)
            events.extend(self._adjust("min_confidence", 0.55, "volatile_regime"))
            events.extend(self._adjust("min_edge", 0.10, "volatile_regime"))
            events.extend(self._adjust("kelly_fraction", 0.08, "volatile_regime"))
            events.extend(self._adjust("max_position_size", 2, "volatile_regime"))
            events.extend(self._adjust("stop_loss_pct", 0.10, "volatile_regime"))  # tighter stop
            events.extend(self._adjust("take_profit_pct", 0.12, "volatile_regime"))  # take profits early

        elif regime == "quiet":
            # Low vol: wider stops (less noise-triggered exits), be patient
            events.extend(self._adjust("min_confidence", 0.40, "quiet_regime"))
            events.extend(self._adjust("min_edge", 0.06, "quiet_regime"))
            events.extend(self._adjust("kelly_fraction", 0.18, "quiet_regime"))
            events.extend(self._adjust("max_position_size", 5, "quiet_regime"))
            events.extend(self._adjust("stop_loss_pct", 0.18, "quiet_regime"))  # wider — less noise
            events.extend(self._adjust("take_profit_pct", 0.20, "quiet_regime"))  # let winners run

        elif regime == "trending":
            # Trending: wider trailing stop to ride the trend
            events.extend(self._adjust("min_confidence", 0.45, "trending_regime"))
            events.extend(self._adjust("min_edge", 0.07, "trending_regime"))
            events.extend(self._adjust("kelly_fraction", 0.15, "trending_regime"))
            events.extend(self._adjust("stop_loss_pct", 0.15, "trending_regime"))  # standard
            events.extend(self._adjust("take_profit_pct", 0.25, "trending_regime"))  # wider — ride trend

        elif regime == "mean_reverting":
            # Mean-revert: tight take-profit (grab the bounce), tight stop
            events.extend(self._adjust("min_confidence", 0.50, "mean_reverting_regime"))
            events.extend(self._adjust("min_edge", 0.08, "mean_reverting_regime"))
            events.extend(self._adjust("kelly_fraction", 0.10, "mean_reverting_regime"))
            events.extend(self._adjust("stop_loss_pct", 0.12, "mean_reverting_regime"))  # tight stop
            events.extend(self._adjust("take_profit_pct", 0.10, "mean_reverting_regime"))  # quick scalp

        return [e for e in events if e is not None]

    # ── Win Rate Adaptation ───────────────────────────────────────────

    def _adapt_to_win_rate(self, snap: PerformanceSnapshot) -> list[AdaptationEvent]:
        """Get more aggressive when winning, conservative when losing."""
        events = []

        if snap.real_trades < 30:
            return events  # Not enough data — learning mode

        if snap.win_rate > 0.65:
            # Winning streak: slightly loosen entry, increase size (but never below floor)
            events.extend(self._adjust("min_confidence", max(self.params.min_confidence - 0.01, self._MIN_CONFIDENCE), "high_win_rate"))
            events.extend(self._adjust("kelly_fraction", min(self.params.kelly_fraction + 0.02, self._MAX_KELLY), "high_win_rate"))

        elif snap.win_rate < 0.40:
            # Losing: tighten everything hard
            events.extend(self._adjust("min_confidence", min(self.params.min_confidence + 0.04, self._MAX_CONFIDENCE), "low_win_rate"))
            events.extend(self._adjust("min_edge", min(self.params.min_edge + 0.02, self._MAX_EDGE), "low_win_rate"))
            events.extend(self._adjust("kelly_fraction", max(self.params.kelly_fraction - 0.05, self._MIN_KELLY), "low_win_rate"))

        return [e for e in events if e is not None]

    # ── Drawdown Adaptation ───────────────────────────────────────────

    def _adapt_to_drawdown(self, snap: PerformanceSnapshot) -> list[AdaptationEvent]:
        """Reduce exposure during drawdowns."""
        events = []

        if snap.current_drawdown < -10:  # Phase 13: trigger earlier at $10 (was $20)
            severity = min(abs(snap.current_drawdown) / 50.0, 0.7)  # Phase 13: scale harder, max 70% reduction
            new_kelly = max(self.params.kelly_fraction * (1.0 - severity), self._MIN_KELLY)
            new_positions = max(int(self.params.max_simultaneous_positions * (1.0 - severity)), 3)

            events.extend(self._adjust("kelly_fraction", new_kelly, f"drawdown_${abs(snap.current_drawdown):.0f}"))
            events.extend(self._adjust("max_simultaneous_positions", new_positions, f"drawdown_${abs(snap.current_drawdown):.0f}"))

        elif snap.current_drawdown > -3:  # Phase 13: tighter recovery threshold (was -5)
            # Slowly restore defaults — VERY slowly
            events.extend(self._adjust("kelly_fraction", min(self.params.kelly_fraction + 0.01, 0.20), "recovery"))  # Phase 13: cap at 0.20, +0.01 (was +0.02, cap 0.40)
            events.extend(self._adjust("max_simultaneous_positions", min(self.params.max_simultaneous_positions + 1, 30), "recovery"))  # Phase 13: cap at 30 (was 75)

        return [e for e in events if e is not None]

    # ── Model Quality Adaptation ──────────────────────────────────────

    def _adapt_to_model_quality(self, snap: PerformanceSnapshot) -> list[AdaptationEvent]:
        """Adjust based on model's prediction accuracy."""
        events = []

        if snap.real_trades < 50:
            return events  # Need substantial data before judging accuracy

        if snap.prediction_accuracy < 0.45:
            # Model is barely better than coin flip — be extremely careful
            events.extend(self._adjust("min_confidence", 0.55, "poor_accuracy"))
            events.extend(self._adjust("min_edge", 0.12, "poor_accuracy"))
            events.extend(self._adjust("kelly_fraction", 0.08, "poor_accuracy"))

        elif snap.prediction_accuracy > 0.60:
            # Model is good — trust it, but still require strong signals
            events.extend(self._adjust("min_confidence", 0.30, "good_accuracy"))
            events.extend(self._adjust("min_edge", 0.06, "good_accuracy"))

        # Confidence calibration: if model is overconfident, require more edge
        if snap.confidence_calibration > 0.15:
            events.extend(self._adjust("min_edge", min(self.params.min_edge + 0.02, self._MAX_EDGE), "poor_calibration"))

        return [e for e in events if e is not None]

    # ── Streak Adaptation ─────────────────────────────────────────────

    def _adapt_to_streaks(self, snap: PerformanceSnapshot) -> list[AdaptationEvent]:
        """React to consecutive wins/losses.
        
        NOTE: This only fires AFTER learning mode (100+ real trades)
        because the main adapt() method returns early during learning.
        Even post-learning, we use bounded adjustments — never nuke params.
        """
        events = []

        if snap.consecutive_losses >= 3:
            # Scale back kelly proportionally to streak length
            reduction = 0.03 * snap.consecutive_losses
            new_kelly = max(self.params.kelly_fraction - reduction, self._MIN_KELLY)
            events.extend(self._adjust("kelly_fraction", new_kelly, f"loss_streak_{snap.consecutive_losses}"))

            if snap.consecutive_losses >= 5:
                # Tighten — but use bounded adjustments, never exceed _MAX_CONFIDENCE
                new_conf = min(self.params.min_confidence + 0.05, self._MAX_CONFIDENCE)
                events.extend(self._adjust("min_confidence", new_conf, "loss_streak_tighten"))
                new_scan = min(self.params.scan_interval * 1.5, 60.0)  # cap at 60s, not 120
                events.extend(self._adjust("scan_interval", new_scan, "loss_streak_slow"))

        elif snap.consecutive_losses == 0 and self.params.scan_interval > 20.0:
            # Streak broken — gradually restore scan_interval
            new_scan = max(self.params.scan_interval - 5.0, 20.0)
            events.extend(self._adjust("scan_interval", new_scan, "streak_recovery"))

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
