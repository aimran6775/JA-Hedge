"""
JA Hedge — Live In-Game Trading Engine (Phase S6).

Coordinates in-game trading decisions:
  - Score-based arbitrage (blowout → fade the market)
  - Momentum scalping (scoring runs)
  - Garbage time detection (reduce exposure)
  - Halftime adjustments
  - Tighter stop-losses for live positions
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from app.logging_config import get_logger

log = get_logger("sports.live_engine")


@dataclass
class LiveSignal:
    """A trading signal generated from live game analysis."""
    signal_type: str       # "score_arb", "momentum_scalp", "garbage_time_fade", "halftime_adj"
    ticker: str
    side: str              # "yes" or "no"
    strength: float        # 0.0 to 1.0
    reason: str
    urgency: float = 0.5   # 0 = can wait, 1 = execute now
    timestamp: float = field(default_factory=time.time)


class LiveTradingEngine:
    """
    In-game trading coordinator.
    
    Analyzes live game state and generates trading signals
    that Frankenstein can act on during its scan loop.
    """
    
    def __init__(self) -> None:
        self._signals: list[LiveSignal] = []
        self._max_signals = 100
        self._stats = {
            "score_arb_signals": 0,
            "momentum_signals": 0,
            "garbage_time_signals": 0,
            "halftime_signals": 0,
        }
    
    def analyze(
        self,
        game_state: dict[str, Any],
        sports_features: Any,  # SportsFeatures
        ticker: str,
    ) -> list[LiveSignal]:
        """
        Analyze a live game and generate trading signals.
        
        Called by Frankenstein during scan for each live sports position.
        """
        signals = []
        
        if not game_state or not game_state.get("is_live"):
            return signals
        
        progress = game_state.get("progress", 0.0)
        score_diff = game_state.get("score_differential", 0)
        momentum = game_state.get("momentum_home", 0.0)
        period = game_state.get("period", 0)
        
        # ── Score-based arbitrage ─────────────────────────────────
        # If a team is getting blown out in a late stage → the moneyline
        # should be heavily in one direction. Look for mispricing.
        if progress > 0.60 and abs(score_diff) > 0:
            sig = self._check_score_arbitrage(
                ticker, game_state, sports_features, progress, score_diff
            )
            if sig:
                signals.append(sig)
                self._stats["score_arb_signals"] += 1
        
        # ── Momentum scalping ────────────────────────────────────
        # If a team is on a scoring run, the market might not have adjusted yet
        if abs(momentum) > 3.0:
            sig = self._check_momentum(
                ticker, game_state, momentum, progress
            )
            if sig:
                signals.append(sig)
                self._stats["momentum_signals"] += 1
        
        # ── Garbage time detection ───────────────────────────────
        if progress > 0.80 and sports_features.is_blowout:
            sig = self._check_garbage_time(
                ticker, game_state, sports_features, progress, score_diff
            )
            if sig:
                signals.append(sig)
                self._stats["garbage_time_signals"] += 1
        
        # ── Halftime adjustments ─────────────────────────────────
        if game_state.get("is_halftime"):
            sig = self._check_halftime(
                ticker, game_state, sports_features
            )
            if sig:
                signals.append(sig)
                self._stats["halftime_signals"] += 1
        
        # Store signals
        self._signals.extend(signals)
        if len(self._signals) > self._max_signals:
            self._signals = self._signals[-self._max_signals:]
        
        return signals
    
    def _check_score_arbitrage(
        self,
        ticker: str,
        game_state: dict,
        sf: Any,
        progress: float,
        score_diff: int,
    ) -> LiveSignal | None:
        """
        Check for score-based arbitrage.
        
        Late in a blowout, the moneyline should be extreme (>90% or <10%).
        If Kalshi hasn't adjusted, there's free money.
        """
        typical_total = sf.typical_total or 100
        
        # Normalize score differential by sport's typical total
        normalized_diff = score_diff / max(typical_total * 0.1, 1)  # how many "scores" ahead
        
        # In a blowout (>2 scores ahead) in 4th quarter type situation
        if abs(normalized_diff) >= 2 and progress > 0.70:
            # The leading team should win >90% of the time
            if normalized_diff > 0:
                # Home team crushing it
                fair_prob_home = min(0.98, 0.80 + abs(normalized_diff) * 0.05)
                if sf.kalshi_price < fair_prob_home - 0.05:
                    return LiveSignal(
                        signal_type="score_arb",
                        ticker=ticker,
                        side="yes",  # buy YES (home winning)
                        strength=min(1.0, abs(sf.kalshi_price - fair_prob_home) * 5),
                        reason=f"Home +{score_diff}, {progress:.0%} done, Kalshi={sf.kalshi_price:.2f} < fair={fair_prob_home:.2f}",
                        urgency=0.8,
                    )
            else:
                # Away team crushing it
                fair_prob_home = max(0.02, 0.20 - abs(normalized_diff) * 0.05)
                if sf.kalshi_price > fair_prob_home + 0.05:
                    return LiveSignal(
                        signal_type="score_arb",
                        ticker=ticker,
                        side="no",  # buy NO (away winning)
                        strength=min(1.0, abs(sf.kalshi_price - fair_prob_home) * 5),
                        reason=f"Away +{abs(score_diff)}, {progress:.0%} done, Kalshi={sf.kalshi_price:.2f} > fair={fair_prob_home:.2f}",
                        urgency=0.8,
                    )
        
        return None
    
    def _check_momentum(
        self,
        ticker: str,
        game_state: dict,
        momentum: float,
        progress: float,
    ) -> LiveSignal | None:
        """
        Check for momentum-based trading signal.
        
        If a team is on a run, the market might lag.
        """
        if progress > 0.90:
            return None  # too late for momentum plays
        
        if momentum > 5.0:
            return LiveSignal(
                signal_type="momentum_scalp",
                ticker=ticker,
                side="yes",
                strength=min(1.0, momentum / 10.0),
                reason=f"Home on a run (momentum={momentum:.1f}), progress={progress:.0%}",
                urgency=0.6,
            )
        elif momentum < -5.0:
            return LiveSignal(
                signal_type="momentum_scalp",
                ticker=ticker,
                side="no",
                strength=min(1.0, abs(momentum) / 10.0),
                reason=f"Away on a run (momentum={momentum:.1f}), progress={progress:.0%}",
                urgency=0.6,
            )
        
        return None
    
    def _check_garbage_time(
        self,
        ticker: str,
        game_state: dict,
        sf: Any,
        progress: float,
        score_diff: int,
    ) -> LiveSignal | None:
        """
        Garbage time: blowout in late game.
        
        The losing team often scores "garbage time" points that don't
        affect the outcome. The market might overreact to these scores.
        """
        # Signal to hold/add to positions with the leading team
        if score_diff > 0:
            return LiveSignal(
                signal_type="garbage_time_fade",
                ticker=ticker,
                side="yes",  # hold with home (leading)
                strength=0.3,  # low strength — just a confirmation signal
                reason=f"Garbage time: Home +{score_diff}, {progress:.0%} done",
                urgency=0.3,
            )
        else:
            return LiveSignal(
                signal_type="garbage_time_fade",
                ticker=ticker,
                side="no",
                strength=0.3,
                reason=f"Garbage time: Away +{abs(score_diff)}, {progress:.0%} done",
                urgency=0.3,
            )
    
    def _check_halftime(
        self,
        ticker: str,
        game_state: dict,
        sf: Any,
    ) -> LiveSignal | None:
        """
        Halftime analysis.
        
        Halftime is a natural point to reassess — the market often
        overreacts to first-half results. Strong teams come back.
        """
        score_diff = game_state.get("score_differential", 0)
        
        # If the home team is behind at halftime but has home advantage
        if score_diff < 0 and sf.home_advantage > 0.02:
            return LiveSignal(
                signal_type="halftime_adj",
                ticker=ticker,
                side="yes",  # slight lean toward home comeback
                strength=0.2,
                reason=f"Halftime: Home behind by {abs(score_diff)}, home advantage={sf.home_advantage:.1%}",
                urgency=0.2,
            )
        
        return None
    
    def get_pending_signals(self, max_age_seconds: float = 300) -> list[LiveSignal]:
        """Get recent unprocessed signals."""
        cutoff = time.time() - max_age_seconds
        return [s for s in self._signals if s.timestamp > cutoff]
    
    def clear_signals(self) -> None:
        self._signals.clear()
    
    def stats(self) -> dict[str, Any]:
        return {
            "pending_signals": len(self._signals),
            **self._stats,
        }


# Singleton
live_engine = LiveTradingEngine()
